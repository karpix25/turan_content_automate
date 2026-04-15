import os
import asyncio
import random
import logging
import re
from typing import List
from urllib.parse import urlparse, parse_qs
from celery import Celery
from .integrations.vizard import VizardClient
from .integrations.scrape_creators import ScrapeCreatorsClient
from .integrations.rapidapi_youtube import RapidAPIYoutubeClient
from .integrations.downloader import Downloader
from .integrations.postmypost import PostMyPostClient
from .processor import VideoProcessor
from .database import SessionLocal, init_database
from .publish_planner import plan_next_publish_times
from .telegram_progress import update_task_status_message
from . import models
from dotenv import load_dotenv

load_dotenv()
init_database()

celery_app = Celery('tasks', broker=(os.getenv("REDIS_URL") or "redis://localhost:6379/0").strip())

# Initialize clients
vizard = VizardClient(api_key=(os.getenv("VIZARD_API_KEY") or "").strip())
scraper = ScrapeCreatorsClient(api_key=(os.getenv("SCRAPE_CREATORS_API_KEY") or "").strip())
rapidapi_yt = RapidAPIYoutubeClient(
    api_key=os.getenv("RAPIDAPI_KEY", ""),
    host=os.getenv("YOUTUBE_DOWNLOAD_RAPIDAPI_HOST", "youtube-mp4-mp3-downloader.p.rapidapi.com"),
    video_format=os.getenv("YOUTUBE_DOWNLOAD_FORMAT", "720"),
    audio_quality=os.getenv("YOUTUBE_DOWNLOAD_AUDIO_QUALITY", "128"),
    poll_interval_seconds=float(os.getenv("YOUTUBE_DOWNLOAD_POLL_INTERVAL_SECONDS", "2")),
    timeout_seconds=float(os.getenv("YOUTUBE_DOWNLOAD_TIMEOUT_SECONDS", "90")),
)
downloader = Downloader(output_dir=(os.getenv("OUTPUT_DIR") or "./output").strip())
pmp_client = PostMyPostClient(api_key=(os.getenv("POSTMYPOST_API_KEY") or "").strip())
processor = VideoProcessor()

def _parse_env_account_ids(raw: str) -> List[int]:
    result: List[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            result.append(int(part))
        except ValueError:
            logging.warning(f"Skipping invalid account id in env: {part}")
    return result


def _normalize_platform_code(value: str | None) -> str:
    code = (value or "").strip().lower()
    if not code:
        return "universal"

    normalized = code.replace("-", "_").replace(" ", "_")
    aliases = {
        "ig": "instagram",
        "insta": "instagram",
        "yt": "youtube",
        "you_tube": "youtube",
        "youtube_shorts": "youtube",
        "instagram_reels": "instagram",
        "instagram_reel": "instagram",
    }
    normalized = aliases.get(normalized, normalized)

    if normalized in {"instagram", "youtube", "tiktok", "universal"}:
        return normalized

    # PostMyPost channel codes can vary by network/type; infer by tokens.
    tokens = set(re.split(r"[^a-z0-9]+", normalized))
    if "instagram" in normalized or {"ig", "insta", "instagram"} & tokens:
        return "instagram"
    if "youtube" in normalized or {"yt", "youtube"} & tokens:
        return "youtube"
    if "tiktok" in normalized or {"tt", "tiktok"} & tokens:
        return "tiktok"

    return "universal"


def _get_target_account_ids(db, user_id: int) -> List[int]:
    ids = [
        item.account_id
        for item in db.query(models.UserPublishChannel).filter(
            models.UserPublishChannel.user_id == user_id,
            models.UserPublishChannel.enabled.is_(True),
        ).order_by(models.UserPublishChannel.account_id.asc()).all()
    ]
    if ids:
        return ids

    env_ids = _parse_env_account_ids(os.getenv("POSTMYPOST_CHANNEL_IDS", ""))
    if env_ids:
        return env_ids

    # Fallback: if user did not configure channel toggles yet, use all
    # accounts available in the selected PostMyPost project.
    try:
        if pmp_client.api_key:
            project_id_raw = os.getenv("POSTMYPOST_PROJECT_ID", "").strip()
            project_id = int(project_id_raw) if project_id_raw else None
            project_id = pmp_client.ensure_project_id(project_id)
            accounts = pmp_client.get_accounts(project_id=project_id)
            account_ids = sorted(
                {
                    int(item["id"])
                    for item in accounts
                    if isinstance(item, dict) and item.get("id") is not None
                }
            )
            if account_ids:
                logging.info(
                    "No explicit enabled channels for user %s, fallback to all project accounts: %s",
                    user_id,
                    account_ids,
                )
                return account_ids
    except Exception as e:
        logging.warning("Failed to load fallback PostMyPost account ids: %s", e)

    return []


def _get_account_platform_map(account_ids: List[int]) -> dict[int, str]:
    if not account_ids or not pmp_client.api_key:
        return {}
    try:
        project_id_raw = os.getenv("POSTMYPOST_PROJECT_ID", "").strip()
        project_id = int(project_id_raw) if project_id_raw else None
        project_id = pmp_client.ensure_project_id(project_id)
        accounts = pmp_client.get_accounts(project_id=project_id)
        channels = pmp_client.get_channels()
        channels_by_id = {
            int(item["id"]): item
            for item in channels
            if isinstance(item, dict) and item.get("id") is not None
        }
        account_set = set(account_ids)
        result: dict[int, str] = {}
        for account in accounts:
            account_id = account.get("id")
            if account_id is None:
                continue
            account_id = int(account_id)
            if account_id not in account_set:
                continue
            channel_id_raw = account.get("chanel_id", account.get("channel_id"))
            channel_id = int(channel_id_raw) if channel_id_raw is not None else None
            channel_info = channels_by_id.get(channel_id) if channel_id is not None else None
            channel_code = channel_info.get("code") if channel_info else None
            channel_name = channel_info.get("name") if channel_info else None
            result[account_id] = _normalize_platform_code(channel_code or channel_name)
        return result
    except Exception as e:
        logging.warning(f"Failed to resolve account platform map from PostMyPost: {e}")
        return {}


def _get_channel_plate_config(
    db,
    user: models.User,
    account_id: int | None,
) -> tuple[str | None, int]:
    selected_plate_ids: list[int] = []
    if getattr(user, "selected_plate_id", None) is not None:
        selected_plate_ids = [int(user.selected_plate_id)]
    plate_start_percent = max(0, min(100, int(getattr(user, "plate_start_percent", 0) or 0)))

    if account_id is not None:
        row = db.query(models.UserPublishChannel).filter(
            models.UserPublishChannel.user_id == user.id,
            models.UserPublishChannel.account_id == account_id,
        ).first()
        if row:
            if isinstance(row.selected_plate_ids, list):
                selected_plate_ids = [int(item) for item in row.selected_plate_ids if item is not None]
            elif row.selected_plate_id is not None:
                selected_plate_ids = [int(row.selected_plate_id)]
            if row.plate_start_percent is not None:
                plate_start_percent = max(0, min(100, int(row.plate_start_percent or 0)))

    active_plate = None
    if selected_plate_ids:
        candidates = db.query(models.Plate).filter(models.Plate.id.in_(selected_plate_ids)).all()
        if candidates:
            active_plate = random.choice(candidates)
    plate_path = _resolve_media_file_path(active_plate.file_path if active_plate else None, media_kind="plates")
    return plate_path, plate_start_percent


def _pick_platform_ending(
    clips: List[models.CTAClip],
    platform: str,
    account_id: int | None,
    used_ids_by_platform: dict[str, set[int]],
) -> models.CTAClip | None:
    normalized = _normalize_platform_code(platform)
    exact_account = [
        clip for clip in clips
        if getattr(clip, "account_id", None) == account_id
        and _normalize_platform_code(getattr(clip, "platform", None)) == normalized
    ]
    exact_global = [
        clip for clip in clips
        if getattr(clip, "account_id", None) is None
        and _normalize_platform_code(getattr(clip, "platform", None)) == normalized
    ]
    universal_account = [
        clip for clip in clips
        if getattr(clip, "account_id", None) == account_id
        and _normalize_platform_code(getattr(clip, "platform", None)) == "universal"
    ]
    universal_global = [
        clip for clip in clips
        if getattr(clip, "account_id", None) is None
        and _normalize_platform_code(getattr(clip, "platform", None)) == "universal"
    ]
    fallback_any = [
        clip for clip in clips
        if getattr(clip, "account_id", None) in {None, account_id}
    ]
    pool = (
        exact_account
        if exact_account else exact_global
        if exact_global else universal_account
        if universal_account else universal_global
        if universal_global else fallback_any
    )
    if not pool:
        return None

    used_key = f"{account_id}:{normalized}" if pool is not fallback_any else f"{account_id}:fallback_any"
    used = used_ids_by_platform.setdefault(used_key, set())
    available = [clip for clip in pool if clip.id not in used]
    if available:
        choice = random.choice(available)
        used.add(choice.id)
        return choice
    return random.choice(pool)


def _build_account_variant_plan(
    account_ids: List[int],
    account_platform_map: dict[int, str],
) -> tuple[int, dict[int, int]]:
    if not account_ids:
        return 1, {}

    groups: dict[str, List[int]] = {}
    for account_id in account_ids:
        platform_code = _normalize_platform_code(account_platform_map.get(account_id))
        groups.setdefault(platform_code, []).append(account_id)

    variant_count = max((len(items) for items in groups.values()), default=1)
    account_variant_index: dict[int, int] = {}
    for account_group in groups.values():
        for slot_idx, account_id in enumerate(account_group, start=1):
            account_variant_index[account_id] = slot_idx

    return max(1, variant_count), account_variant_index


def _normalize_external_url(value: str) -> str:
    url = (value or "").strip().strip("<>()[]{}\"'.,;")
    if not url:
        return url
    if _extract_youtube_video_id(url):
        return url
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    return url


def _is_youtube_shorts_url(url: str) -> bool:
    raw = (url or "").strip()
    if not raw or re.fullmatch(r"[A-Za-z0-9_-]{11}", raw):
        return False

    parsed = urlparse(raw)
    host = parsed.netloc.lower()
    path_parts = [part for part in parsed.path.split("/") if part]
    return "youtube.com" in host and len(path_parts) >= 2 and path_parts[0] == "shorts"


def _resolve_media_file_path(path: str | None, media_kind: str) -> str | None:
    value = (path or "").strip()
    if not value:
        return None
    if os.path.isfile(value):
        return value

    normalized = value.lstrip("./")
    base_name = os.path.basename(normalized)
    candidates = [
        os.path.join("/app", normalized),
        os.path.join("/app/database/media", media_kind, base_name),
        os.path.join("/app/database/media", base_name),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def _extract_youtube_video_id(url: str) -> str | None:
    raw = (url or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", raw):
        return raw

    parsed = urlparse(raw)
    host = parsed.netloc.lower()
    path_parts = [part for part in parsed.path.split("/") if part]

    if "youtu.be" in host:
        candidate = path_parts[0] if path_parts else ""
        return candidate if len(candidate) == 11 else None

    if "youtube.com" in host:
        if len(path_parts) >= 2 and path_parts[0] == "shorts":
            candidate = path_parts[1]
            return candidate if len(candidate) == 11 else None
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [""])[0]
            return candidate if len(candidate) == 11 else None

    return None


def _validate_youtube_url_or_raise(url: str) -> None:
    if _extract_youtube_video_id(url) is None:
        raise Exception("Invalid YouTube URL (expected 11-char video id)")


def _build_youtube_watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _extract_vizard_project_id(url_or_id: str) -> str | None:
    raw = str(url_or_id).strip()
    # Remove accidental http(s) prefix if it was added to a pure numeric ID
    if raw.startswith("https://") and raw[8:].isdigit():
        raw = raw[8:]
    elif raw.startswith("http://") and raw[7:].isdigit():
        raw = raw[7:]

    match = re.search(r"vizard\.ai/(?:project|dashboard/editor)/(\d+)", raw, re.IGNORECASE)
    if match:
        return match.group(1)
    if raw.isdigit():
        return raw
    return None



def _extract_vizard_clip_title(clip: dict) -> str | None:
    if not isinstance(clip, dict):
        return None

    direct_keys = (
        "title",
        "headline",
        "headLine",
        "clipTitle",
        "videoTitle",
        "name",
    )
    for key in direct_keys:
        value = clip.get(key)
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                return normalized

    # Fallback: search nested dictionaries for title-like keys.
    for key, value in clip.items():
        key_text = str(key).lower()
        if not isinstance(value, str):
            continue
        if "title" in key_text or "headline" in key_text:
            normalized = value.strip()
            if normalized:
                return normalized
    return None


def _download_vizard_project_clips(db, task: models.VideoTask, source_url: str, **create_kwargs) -> List[tuple[str, str | None]]:
    logging.info(f"Task {task.id}: Processing vizard/youtube source: '{source_url}'")
    
    # Check if we already have a project ID or if source_url is a Vizard link
    existing_v_id = _extract_vizard_project_id(source_url)
    
    # If the task is explicitly of type 'vizard', we should NEVER try to create a new project
    # unless it's a YouTube URL that we chose to process with Vizard.
    # However, if it's a pure 'vizard' task, it usually means a project link was sent.
    is_vizard_project_link = (task.type == "vizard")
    
    if existing_v_id or is_vizard_project_link:
        p_id_str = existing_v_id or source_url
        if p_id_str.isdigit():
            p_id = int(p_id_str)
            logging.info(f"Task {task.id}: SUCCESS - Identified Vizard project ID {p_id}. Calling Retrieve Video Clips.")
        else:
            # Maybe it's a link that wasn't extracted? try extracting again
            p_id_str = _extract_vizard_project_id(p_id_str)
            if p_id_str and p_id_str.isdigit():
                p_id = int(p_id_str)
                logging.info(f"Task {task.id}: SUCCESS - Extracted Vizard project ID {p_id} from URL. Calling Retrieve Video Clips.")
            else:
                # If we still don't have a numeric ID but task was 'vizard', something is wrong
                if task.type == "vizard":
                    raise Exception(f"Task type is 'vizard' but could not find a numeric PROJECT ID in '{source_url}'. Please send a valid vizard.ai link.")
                
                logging.info(f"Task {task.id}: No numeric Vizard ID found in '{source_url}'. Proceeding to create new project.")
                p_id = asyncio.run(vizard.create_project(source_url, **create_kwargs))
    else:
        logging.info(f"Task {task.id}: Standard creation flow for: {source_url}")
        p_id = asyncio.run(vizard.create_project(source_url, **create_kwargs))

    if not p_id:
        raise Exception(f"Failed to resolve Vizard project ID for: {source_url}")




    task.vizard_project_id = p_id
    db.commit()

    clips = asyncio.run(vizard.poll_until_complete(p_id))
    if not clips:
        raise Exception("Vizard conversion timed out or failed")

    input_videos: List[tuple[str, str | None]] = []
    for i, clip in enumerate(clips):
        url = clip.get("videoUrl")
        if not url:
            raise Exception(f"Vizard clip #{i} has no download URL")
        clip_title = _extract_vizard_clip_title(clip)
        local_file = downloader.download_video(url, f"vizard_{p_id}_{i}")
        if not local_file:
            raise Exception(f"Failed to download Vizard clip #{i}")
        input_videos.append((local_file, clip_title))
    return input_videos


def _build_youtube_download_headers(watch_url: str) -> dict[str, str]:
    return {
        "Origin": "https://www.youtube.com",
        "Referer": watch_url,
    }


def _plan_publish_times_for_outputs(db, user: models.User, output_platforms: list[str], manual_publish_at):
    outputs_count = len(output_platforms)
    if outputs_count < 1:
        return []
    if manual_publish_at is not None:
        return [manual_publish_at] * outputs_count
    if not bool(getattr(user, "auto_schedule_enabled", False)):
        return [None] * outputs_count

    planned: list[datetime.datetime | None] = [None] * outputs_count
    grouped_indices: dict[str, list[int]] = {}
    for index, platform_code in enumerate(output_platforms):
        normalized = _normalize_platform_code(platform_code)
        grouped_indices.setdefault(normalized, []).append(index)

    for platform_code, indices in grouped_indices.items():
        times = plan_next_publish_times(
            db=db,
            user=user,
            count=len(indices),
            platform_code=platform_code,
        )
        for idx, planned_time in zip(indices, times):
            planned[idx] = planned_time

    return planned


def _get_base_source_label(source_url: str) -> str:
    base = (source_url or "").split(" [slot ", 1)[0]
    base = base.split(" [variant ", 1)[0]
    base = base.split(" [clip ", 1)[0]
    base = base.split(" [account ", 1)[0]
    return base


def _resolve_publishing_status(publish_at, should_sync: bool) -> str:
    if publish_at:
        return "scheduled"
    return "in_progress" if should_sync else "not_published"


def _build_source_label(
    base_source: str,
    *,
    clip_index: int | None = None,
    slot_index: int | None = None,
    account_id: int | None = None,
) -> str:
    label = base_source
    if clip_index is not None:
        label += f" [clip {clip_index}]"
    if slot_index is not None:
        label += f" [slot {slot_index}]"
    if account_id is not None:
        label += f" [account {account_id}]"
    return label


def _upsert_variant_task(
    db,
    base_task: models.VideoTask,
    output_path: str,
    variant_index: int,
    publish_at,
    target_account_id: int | None,
    target_platform: str | None,
) -> models.VideoTask:
    base_source = _get_base_source_label(base_task.source_url)
    existing = db.query(models.VideoTask).filter(
        models.VideoTask.user_id == base_task.user_id,
        models.VideoTask.output_path == output_path,
        models.VideoTask.id != base_task.id,
    ).first()

    publishing_status = _resolve_publishing_status(publish_at, should_sync=True)

    if existing:
        existing.type = base_task.type
        existing.status = "completed"
        existing.vizard_project_id = base_task.vizard_project_id
        existing.source_url = f"{base_source} [slot {variant_index}] [account {target_account_id}]"
        existing.publish_at = publish_at
        existing.target_account_id = target_account_id
        existing.target_platform = target_platform
        existing.publishing_status = publishing_status
        db.commit()
        db.refresh(existing)
        return existing

    variant_task = models.VideoTask(
        user_id=base_task.user_id,
        source_url=f"{base_source} [slot {variant_index}] [account {target_account_id}]",
        type=base_task.type,
        status="completed",
        vizard_project_id=base_task.vizard_project_id,
        output_path=output_path,
        publish_at=publish_at,
        target_account_id=target_account_id,
        target_platform=target_platform,
        publishing_status=publishing_status,
    )
    db.add(variant_task)
    db.commit()
    db.refresh(variant_task)
    return variant_task


def _upsert_processed_task(
    db,
    base_task: models.VideoTask,
    output_path: str,
    source_label: str,
    source_title: str | None,
    publish_at,
    target_account_id: int | None,
    target_platform: str | None,
    should_sync: bool,
) -> models.VideoTask:
    existing = db.query(models.VideoTask).filter(
        models.VideoTask.user_id == base_task.user_id,
        models.VideoTask.output_path == output_path,
        models.VideoTask.id != base_task.id,
    ).first()

    publishing_status = _resolve_publishing_status(publish_at, should_sync=should_sync)

    if existing:
        existing.type = base_task.type
        existing.status = "completed"
        existing.vizard_project_id = base_task.vizard_project_id
        existing.source_url = source_label
        existing.source_title = source_title
        existing.publish_at = publish_at
        existing.target_account_id = target_account_id
        existing.target_platform = target_platform
        existing.postmypost_id = None
        existing.postmypost_file_id = None
        existing.preview_url = None
        existing.publishing_status = publishing_status
        db.commit()
        db.refresh(existing)
        return existing

    clip_task = models.VideoTask(
        user_id=base_task.user_id,
        source_url=source_label,
        type=base_task.type,
        status="completed",
        vizard_project_id=base_task.vizard_project_id,
        output_path=output_path,
        source_title=source_title,
        publish_at=publish_at,
        target_account_id=target_account_id,
        target_platform=target_platform,
        publishing_status=publishing_status,
    )
    db.add(clip_task)
    db.commit()
    db.refresh(clip_task)
    return clip_task

@celery_app.task(name="process_content_task")
def process_content_task(task_id: int):
    db = SessionLocal()
    task = db.query(models.VideoTask).get(task_id)
    if not task:
        return
    
    user = db.query(models.User).get(task.user_id)
    task.status = "processing"
    db.commit()
    update_task_status_message(db, task, stage="Обработка началась", detail="Подготавливаю видео к обработке.")
    input_videos: List[str] = []
    input_video_titles: List[str | None] = []

    try:
        source_url = _normalize_external_url(task.source_url)
        if not source_url:
            raise Exception("Source URL is empty")

        if task.type == "vizard":
            update_task_status_message(db, task, stage="Vizard", detail="Отправляю видео в Vizard и жду клипы.")
            clips = _download_vizard_project_clips(db, task, source_url)
            input_videos.extend(path for path, _title in clips)
            input_video_titles.extend(title for _path, title in clips)

        elif task.type == "instagram":
            update_task_status_message(db, task, stage="Скачивание", detail="Скачиваю видео из Instagram.")
            details = scraper.get_instagram_details(source_url)
            download_url = _normalize_external_url((details or {}).get("download_url") or "")
            if not download_url:
                error_text = (details or {}).get("error") or "Failed to get Instagram download link"
                raise Exception(error_text)

            local_file = downloader.download_video(download_url, f"insta_{task_id}")
            if not local_file:
                raise Exception("Failed to download Instagram video from ScrapeCreators URL")
            input_videos.append(local_file)
            input_video_titles.append(None)

        elif task.type == "youtube":
            _validate_youtube_url_or_raise(source_url)
            youtube_video_id = _extract_youtube_video_id(source_url)
            if not youtube_video_id:
                raise Exception("Failed to normalize YouTube video id")
            if _is_youtube_shorts_url(source_url):
                update_task_status_message(db, task, stage="Скачивание", detail="Скачиваю YouTube Shorts.")
                provider_source_url = f"https://www.youtube.com/shorts/{youtube_video_id}"
                details = rapidapi_yt.get_youtube_details(provider_source_url)
                download_url = _normalize_external_url((details or {}).get("download_url") or "")
                if not download_url:
                    rapidapi_error = (details or {}).get("error")
                    raise Exception(
                        f"Failed to download YouTube Shorts via configured RapidAPI provider: "
                        f"{rapidapi_error or 'No downloadable media URL'}"
                    )

                logging.info(
                    "Task %s: routed YouTube Shorts to RapidAPI status=%s progress_id=%s",
                    task_id,
                    (details or {}).get("status"),
                    (details or {}).get("progress_id"),
                )

                local_file = downloader.download_media(
                    download_url,
                    f"yt_{task_id}",
                    headers=_build_youtube_download_headers(provider_source_url),
                )

                if not local_file:
                    raise Exception("Failed to download YouTube Shorts from provider URL")
                input_videos.append(local_file)
                input_video_titles.append(None)
            else:
                logging.info("Task %s: routed full YouTube video to Vizard", task_id)
                update_task_status_message(db, task, stage="Vizard", detail="Полное YouTube-видео отправлено в Vizard.")
                clips = _download_vizard_project_clips(
                    db,
                    task,
                    source_url,
                    video_type=2,
                    prefer_length=[1],
                    lang="auto",
                    ratio_of_clip=1,
                    get_clips=1,
                    highlight_switch=0,
                    subtitle_switch=1,
                    auto_broll_switch=0,
                    headline_switch=0,
                    remove_silence_switch=1,
                )
                input_videos.extend(path for path, _title in clips)
                input_video_titles.extend(title for _path, title in clips)

        if not input_videos:
            raise Exception("No input videos were downloaded")
        update_task_status_message(db, task, stage="Монтаж", detail="Собираю финальные ролики.")
        process_all_clips = bool(task.vizard_project_id)
        if process_all_clips:
            source_items = [
                (index, input_videos[index - 1], input_video_titles[index - 1] if len(input_video_titles) >= index else None)
                for index in range(1, len(input_videos) + 1)
            ]
        else:
            source_items = [(1, input_videos[0], input_video_titles[0] if input_video_titles else None)]
        if not process_all_clips and len(input_videos) > 1:
            logging.info(f"Task {task_id}: got {len(input_videos)} source clips, processing first clip only")

        subtitles_enabled = False
        ass_path = None
        target_account_ids = _get_target_account_ids(db, user.id)
        if task.type in {"instagram", "youtube"} and not target_account_ids and not process_all_clips:
            raise Exception(
                "No PostMyPost accounts configured/enabled for this user. "
                "Enable channels in UI or set POSTMYPOST_CHANNEL_IDS."
            )

        if not target_account_ids and task.target_account_id:
            target_account_ids = [int(task.target_account_id)]
        elif task.target_account_id and int(task.target_account_id) not in target_account_ids:
            target_account_ids = [int(task.target_account_id)] + target_account_ids
        target_account_ids = list(dict.fromkeys(target_account_ids))

        account_platform_map = _get_account_platform_map(target_account_ids)
        variants_count, account_variant_index = _build_account_variant_plan(
            account_ids=target_account_ids,
            account_platform_map=account_platform_map,
        )
        ending_clips = db.query(models.CTAClip).filter(
            models.CTAClip.user_id == user.id
        ).order_by(models.CTAClip.id.desc()).all()
        logging.info(
            "Task %s: user_id=%s telegram_id=%s accounts=%s variants_count=%s endings_loaded=%s",
            task_id,
            user.id,
            getattr(user, "telegram_id", None),
            target_account_ids,
            variants_count,
            len(ending_clips),
        )
        output_platforms: list[str] = []
        if target_account_ids:
            for _clip_index, _video_path, _clip_title in source_items:
                for account_id in target_account_ids:
                    output_platforms.append(_normalize_platform_code(account_platform_map.get(account_id, "universal")))
        else:
            for _clip_index, _video_path, _clip_title in source_items:
                output_platforms.append(_normalize_platform_code(task.type))
        publish_times = _plan_publish_times_for_outputs(
            db=db,
            user=user,
            output_platforms=output_platforms,
            manual_publish_at=None if process_all_clips else task.publish_at,
        )

        should_sync_outputs = bool(target_account_ids)
        base_source = _get_base_source_label(task.source_url)
        rendered_outputs: List[dict] = []
        publish_index = 0

        for clip_index, video_path, clip_title in source_items:
            if not video_path:
                raise Exception("Downloaded video path is empty")

            video_root, _ = os.path.splitext(video_path)
            clip_used_ending_ids_by_platform: dict[str, set[int]] = {}

            if target_account_ids:
                for account_id in target_account_ids:
                    slot_idx = account_variant_index.get(account_id, 1)
                    platform_code = account_platform_map.get(account_id, "universal")
                    plate_path, plate_start_percent = _get_channel_plate_config(db, user, account_id)
                    ending = _pick_platform_ending(
                        clips=ending_clips,
                        platform=platform_code,
                        account_id=account_id,
                        used_ids_by_platform=clip_used_ending_ids_by_platform,
                    )
                    ending_path = _resolve_media_file_path(ending.file_path if ending else None, media_kind="cta")
                    if ending and ending.file_path and not ending_path:
                        logging.warning(
                            "Task %s: ending file missing for clip=%s account=%s platform=%s ending_id=%s path=%s",
                            task_id,
                            clip_index,
                            account_id,
                            platform_code,
                            getattr(ending, "id", None),
                            ending.file_path,
                        )
                    logging.info(
                        "Task %s: clip=%s account=%s platform=%s slot=%s ending_id=%s ending_path=%s",
                        task_id,
                        clip_index,
                        account_id,
                        platform_code,
                        slot_idx,
                        getattr(ending, "id", None),
                        ending_path,
                    )
                    account_output = f"{video_root}_final_s{slot_idx}_a{account_id}.mp4"
                    processor.process_video(
                        input_path=video_path,
                        output_path=account_output,
                        plate_path=plate_path,
                        plate_start_percent=plate_start_percent,
                        ass_path=ass_path,
                        cta_path=ending_path,
                        subtitles_enabled=subtitles_enabled,
                        unique_seed=(clip_index * 1000) + slot_idx if process_all_clips else slot_idx,
                    )
                    publish_at = publish_times[publish_index] if len(publish_times) > publish_index else None
                    publish_index += 1
                    rendered_outputs.append(
                        {
                            "output_path": account_output,
                            "publish_at": publish_at,
                            "target_account_id": account_id,
                            "target_platform": platform_code,
                            "source_title": clip_title,
                            "source_label": _build_source_label(
                                base_source,
                                clip_index=clip_index if process_all_clips else None,
                                slot_index=slot_idx,
                                account_id=account_id,
                            ),
                        }
                    )
            else:
                base_output = f"{video_root}_final.mp4"
                plate_path, plate_start_percent = _get_channel_plate_config(db, user, None)
                processor.process_video(
                    input_path=video_path,
                    output_path=base_output,
                    plate_path=plate_path,
                    plate_start_percent=plate_start_percent,
                    ass_path=ass_path,
                    cta_path=None,
                    subtitles_enabled=subtitles_enabled,
                    unique_seed=clip_index if process_all_clips else 1,
                )
                publish_at = publish_times[publish_index] if len(publish_times) > publish_index else None
                publish_index += 1
                rendered_outputs.append(
                    {
                        "output_path": base_output,
                        "publish_at": publish_at,
                        "target_account_id": None,
                        "target_platform": _normalize_platform_code(task.type),
                        "source_title": clip_title,
                        "source_label": _build_source_label(
                            base_source,
                            clip_index=clip_index if process_all_clips else None,
                        ),
                    }
                )

        if not rendered_outputs:
            raise Exception("No rendered outputs were produced")

        primary_output = rendered_outputs[0]
        task.output_path = primary_output["output_path"]
        task.target_account_id = primary_output["target_account_id"]
        task.target_platform = primary_output["target_platform"]
        task.source_url = primary_output["source_label"]
        task.source_title = primary_output["source_title"]
        task.publish_at = primary_output["publish_at"]
        task.status = "completed"
        task.postmypost_id = None
        task.postmypost_file_id = None
        task.preview_url = None
        task.publishing_status = _resolve_publishing_status(primary_output["publish_at"], should_sync=should_sync_outputs)
        db.commit()
        db.refresh(task)
        if should_sync_outputs:
            update_task_status_message(
                db,
                task,
                stage="Готово",
                detail=f"Подготовлено роликов: {len(rendered_outputs)}. Передаю в очередь публикации.",
                ok=True,
            )
        else:
            update_task_status_message(
                db,
                task,
                stage="Готово",
                detail=f"Финальный файл собран. Роликов: {len(rendered_outputs)}.",
                ok=True,
            )

        if should_sync_outputs:
            logging.info(
                "Task %s: enqueue sync_publication_task for primary output account=%s publish_at=%s",
                task.id,
                primary_output["target_account_id"],
                primary_output["publish_at"],
            )
            celery_app.send_task("sync_publication_task", args=[task.id])

        for derived_output in rendered_outputs[1:]:
            derived_task = _upsert_processed_task(
                db=db,
                base_task=task,
                output_path=derived_output["output_path"],
                source_label=derived_output["source_label"],
                source_title=derived_output["source_title"],
                publish_at=derived_output["publish_at"],
                target_account_id=derived_output["target_account_id"],
                target_platform=derived_output["target_platform"],
                should_sync=should_sync_outputs,
            )
            if should_sync_outputs:
                logging.info(
                    "Task %s: enqueue sync_publication_task for derived output account=%s publish_at=%s",
                    derived_task.id,
                    derived_output["target_account_id"],
                    derived_output["publish_at"],
                )
                celery_app.send_task("sync_publication_task", args=[derived_task.id])

    except Exception as e:
        logging.exception(f"Task {task_id} failed: {e}")
        task.status = "failed"
        db.commit()
        update_task_status_message(
            db,
            task,
            stage="Ошибка",
            detail=f"Обработка остановилась: {str(e)[:300]}",
            failed=True,
        )
        raise
    finally:
        for path in input_videos:
            if not path:
                continue
            try:
                if os.path.isfile(path):
                    os.remove(path)
                    logging.info("Removed temporary source file: %s", path)
            except OSError as e:
                logging.warning("Failed to remove temporary source file %s: %s", path, e)
        db.close()

# Import scheduler to register publication sync tasks on the same Celery app.
from . import scheduler  # noqa: E402,F401
