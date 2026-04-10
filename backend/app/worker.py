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
from . import models
from dotenv import load_dotenv

load_dotenv()
init_database()

celery_app = Celery('tasks', broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"))

# Initialize clients
vizard = VizardClient(api_key=os.getenv("VIZARD_API_KEY", ""))
scraper = ScrapeCreatorsClient(api_key=os.getenv("SCRAPE_CREATORS_API_KEY", ""))
rapidapi_yt = RapidAPIYoutubeClient(
    api_key=os.getenv("RAPIDAPI_KEY", ""),
    host=os.getenv("RAPIDAPI_HOST", "youtube-media-downloader.p.rapidapi.com"),
)
downloader = Downloader(output_dir=os.getenv("OUTPUT_DIR", "./output"))
pmp_client = PostMyPostClient(api_key=os.getenv("POSTMYPOST_API_KEY", ""))
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
    for clip in pool:
        if clip.id not in used:
            used.add(clip.id)
            return clip
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


def _build_youtube_download_headers(watch_url: str) -> dict[str, str]:
    return {
        "Origin": "https://www.youtube.com",
        "Referer": watch_url,
    }


def _track_temp_path(paths: list[str], path: str | None) -> str | None:
    if path:
        paths.append(path)
    return path


def _download_rapidapi_youtube_media(
    task_id: int,
    watch_url: str,
    details: dict,
    temp_paths: list[str],
) -> str | None:
    video_stream = details.get("video_stream") or {}
    audio_stream = details.get("audio_stream") or {}
    progressive_stream = details.get("progressive_stream") or {}

    video_url = _normalize_external_url((details or {}).get("video_download_url") or "")
    audio_url = _normalize_external_url((details or {}).get("audio_download_url") or "")
    progressive_url = _normalize_external_url((details or {}).get("progressive_download_url") or "")
    headers = _build_youtube_download_headers(watch_url)

    if video_url:
        logging.info(
            "Task %s: selected YouTube video stream quality=%s size=%s has_audio=%s itag=%s",
            task_id,
            video_stream.get("quality"),
            video_stream.get("size_text"),
            video_stream.get("has_audio"),
            video_stream.get("itag"),
        )
    if audio_url:
        logging.info(
            "Task %s: selected YouTube audio stream mime=%s xtags=%s itag=%s",
            task_id,
            audio_stream.get("mime_type"),
            audio_stream.get("xtags"),
            audio_stream.get("itag"),
        )
    if progressive_url:
        logging.info(
            "Task %s: selected YouTube progressive fallback quality=%s size=%s itag=%s",
            task_id,
            progressive_stream.get("quality"),
            progressive_stream.get("size_text"),
            progressive_stream.get("itag"),
        )

    if video_url and audio_url:
        video_path = _track_temp_path(
            temp_paths,
            downloader.download_media(video_url, f"yt_{task_id}_video", headers=headers),
        )
        if video_path:
            audio_path = _track_temp_path(
                temp_paths,
                downloader.download_media(audio_url, f"yt_{task_id}_audio", headers=headers),
            )
            if audio_path:
                muxed_path = os.path.join(downloader.output_dir, f"yt_{task_id}_source.mp4")
                try:
                    return _track_temp_path(
                        temp_paths,
                        processor.mux_video_and_audio(video_path, audio_path, muxed_path),
                    )
                except Exception as e:
                    logging.warning("Task %s: failed to mux YouTube A/V streams: %s", task_id, e)

    if progressive_url:
        return _track_temp_path(
            temp_paths,
            downloader.download_media(progressive_url, f"yt_{task_id}_progressive", headers=headers),
        )

    return None


def _plan_publish_times_for_outputs(db, user: models.User, outputs_count: int, manual_publish_at):
    if outputs_count < 1:
        return []
    if manual_publish_at is not None:
        return [manual_publish_at] * outputs_count
    if not bool(getattr(user, "auto_schedule_enabled", False)):
        return [None] * outputs_count
    return plan_next_publish_times(db=db, user=user, count=outputs_count)

def _upsert_variant_task(
    db,
    base_task: models.VideoTask,
    output_path: str,
    variant_index: int,
    publish_at,
    target_account_id: int | None,
) -> models.VideoTask:
    base_source = base_task.source_url.split(" [slot ", 1)[0].split(" [variant ", 1)[0]
    existing = db.query(models.VideoTask).filter(
        models.VideoTask.user_id == base_task.user_id,
        models.VideoTask.output_path == output_path,
        models.VideoTask.id != base_task.id,
    ).first()

    publishing_status = "scheduled" if publish_at else "in_progress"

    if existing:
        existing.type = base_task.type
        existing.status = "completed"
        existing.vizard_project_id = base_task.vizard_project_id
        existing.source_url = f"{base_source} [slot {variant_index}] [account {target_account_id}]"
        existing.publish_at = publish_at
        existing.target_account_id = target_account_id
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
        publishing_status=publishing_status,
    )
    db.add(variant_task)
    db.commit()
    db.refresh(variant_task)
    return variant_task

@celery_app.task(name="process_content_task")
def process_content_task(task_id: int):
    db = SessionLocal()
    task = db.query(models.VideoTask).get(task_id)
    if not task:
        return
    
    user = db.query(models.User).get(task.user_id)
    task.status = "processing"
    db.commit()
    input_videos: List[str] = []
    temp_paths: List[str] = []

    try:
        source_url = _normalize_external_url(task.source_url)
        if not source_url:
            raise Exception("Source URL is empty")

        if task.type == "vizard":
            # 1. Send to Vizard
            p_id = asyncio.run(vizard.create_project(source_url))
            if not p_id:
                raise Exception("Failed to create Vizard project")
            task.vizard_project_id = p_id
            db.commit()

            # 2. Poll Vizard
            clips = asyncio.run(vizard.poll_until_complete(p_id))
            if not clips:
                raise Exception("Vizard conversion timed out or failed")
            
            # 3. Download clips
            for i, clip in enumerate(clips):
                url = clip.get("videoUrl")
                if not url:
                    raise Exception(f"Vizard clip #{i} has no download URL")
                local_file = downloader.download_video(url, f"vizard_{p_id}_{i}")
                if not local_file:
                    raise Exception(f"Failed to download Vizard clip #{i}")
                input_videos.append(local_file)

        elif task.type == "instagram":
            details = scraper.get_instagram_details(source_url)
            download_url = _normalize_external_url((details or {}).get("download_url") or "")
            if not download_url:
                error_text = (details or {}).get("error") or "Failed to get Instagram download link"
                raise Exception(error_text)

            local_file = downloader.download_video(download_url, f"insta_{task_id}")
            if not local_file:
                raise Exception("Failed to download Instagram video from ScrapeCreators URL")
            input_videos.append(local_file)

        elif task.type == "youtube":
            _validate_youtube_url_or_raise(source_url)
            youtube_video_id = _extract_youtube_video_id(source_url)
            if not youtube_video_id:
                raise Exception("Failed to normalize YouTube video id")
            provider_source_url = _build_youtube_watch_url(youtube_video_id)

            details = rapidapi_yt.get_youtube_details(provider_source_url)
            local_file = _download_rapidapi_youtube_media(
                task_id=task_id,
                watch_url=provider_source_url,
                details=details or {},
                temp_paths=temp_paths,
            )

            if not local_file:
                rapidapi_error = (details or {}).get("error") or "RapidAPI media download failed"
                logging.warning(
                    "RapidAPI YouTube download failed. Fallback to ScrapeCreators. Reason: %s",
                    rapidapi_error,
                )
                sc_details = scraper.get_youtube_details(provider_source_url)
                download_url = _normalize_external_url((sc_details or {}).get("download_url") or "")
                if download_url:
                    local_file = _track_temp_path(
                        temp_paths,
                        downloader.download_media(
                            download_url,
                            f"yt_{task_id}_fallback",
                            headers=_build_youtube_download_headers(provider_source_url),
                        ),
                    )
                if not local_file:
                    sc_error = (sc_details or {}).get("error")
                    raise Exception(
                        f"Failed to download YouTube video: RapidAPI={rapidapi_error}; "
                        f"ScrapeCreators={sc_error or 'No downloadable media URL'}"
                    )

            if not local_file:
                raise Exception("Failed to download YouTube video from provider URL")
            input_videos.append(local_file)

        if not input_videos:
            raise Exception("No input videos were downloaded")

        video_path = input_videos[0]
        if len(input_videos) > 1:
            logging.info(f"Task {task_id}: got {len(input_videos)} source clips, processing first clip only")
        if not video_path:
            raise Exception("Downloaded video path is empty")

        video_root, _ = os.path.splitext(video_path)
        base_output = f"{video_root}_final.mp4"

        subtitles_enabled = False
        ass_path = None
        plate_start_percent = max(0, min(100, int(getattr(user, "plate_start_percent", 0) or 0)))

        active_plate = db.query(models.Plate).filter(models.Plate.id == user.selected_plate_id).first()
        plate_path = _resolve_media_file_path(active_plate.file_path if active_plate else None, media_kind="plates")
        if active_plate and active_plate.file_path and not plate_path:
            logging.warning(
                "Task %s: selected plate file missing plate_id=%s path=%s",
                task_id,
                active_plate.id,
                active_plate.file_path,
            )
        target_account_ids = _get_target_account_ids(db, user.id)
        if task.type in {"instagram", "youtube"} and not target_account_ids:
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
        used_ending_ids_by_platform: dict[str, set[int]] = {}
        if target_account_ids:
            account_outputs: List[tuple[int, str, int]] = []
            for account_id in target_account_ids:
                slot_idx = account_variant_index.get(account_id, 1)
                platform_code = account_platform_map.get(account_id, "universal")
                ending = _pick_platform_ending(
                    clips=ending_clips,
                    platform=platform_code,
                    account_id=account_id,
                    used_ids_by_platform=used_ending_ids_by_platform,
                )
                ending_path = _resolve_media_file_path(ending.file_path if ending else None, media_kind="cta")
                if ending and ending.file_path and not ending_path:
                    logging.warning(
                        "Task %s: ending file missing for account=%s platform=%s ending_id=%s path=%s",
                        task_id,
                        account_id,
                        platform_code,
                        getattr(ending, "id", None),
                        ending.file_path,
                    )
                logging.info(
                    "Task %s: account=%s platform=%s slot=%s ending_id=%s ending_path=%s",
                    task_id,
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
                    unique_seed=slot_idx,
                )
                account_outputs.append((account_id, account_output, slot_idx))

            publish_times = _plan_publish_times_for_outputs(
                db=db,
                user=user,
                outputs_count=len(account_outputs),
                manual_publish_at=task.publish_at,
            )

            primary_account_id, primary_output, primary_slot = account_outputs[0]
            primary_publish_at = publish_times[0] if publish_times else None
            task.output_path = primary_output
            task.target_account_id = primary_account_id
            task.source_url = f"{task.source_url.split(' [slot ', 1)[0]} [slot {primary_slot}]"
            task.publish_at = primary_publish_at
            task.status = "completed"
            task.publishing_status = "scheduled" if primary_publish_at else "in_progress"
            db.commit()
            db.refresh(task)

            logging.info(
                "Task %s: enqueue sync_publication_task for primary account %s (publish_at=%s)",
                task.id,
                primary_account_id,
                primary_publish_at,
            )
            celery_app.send_task("sync_publication_task", args=[task.id])

            for index, (account_id, account_output, slot_idx) in enumerate(account_outputs[1:], start=1):
                publish_at = publish_times[index] if len(publish_times) > index else task.publish_at
                variant_task = _upsert_variant_task(
                    db=db,
                    base_task=task,
                    output_path=account_output,
                    variant_index=slot_idx,
                    publish_at=publish_at,
                    target_account_id=account_id,
                )
                logging.info(
                    "Task %s: enqueue sync_publication_task for variant account %s (publish_at=%s)",
                    variant_task.id,
                    account_id,
                    publish_at,
                )
                celery_app.send_task("sync_publication_task", args=[variant_task.id])
        else:
            # No connected publication accounts; render a single local-ready output.
            processor.process_video(
                input_path=video_path,
                output_path=base_output,
                plate_path=plate_path,
                plate_start_percent=plate_start_percent,
                ass_path=ass_path,
                cta_path=None,
                subtitles_enabled=subtitles_enabled,
                unique_seed=1,
            )
            task.output_path = base_output
            task.target_account_id = None
            task.status = "completed"
            task.publishing_status = "scheduled" if task.publish_at else "not_published"
            db.commit()

    except Exception as e:
        logging.exception(f"Task {task_id} failed: {e}")
        task.status = "failed"
        db.commit()
        raise
    finally:
        for path in list(dict.fromkeys(input_videos + temp_paths)):
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
