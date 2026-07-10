import os
import asyncio
import random
import logging
import json
import re
import shutil
import datetime
import time
import math
import selectors
import uuid
import subprocess
import glob
import httpx
from typing import List
from urllib.parse import urlparse, parse_qs
from billiard.exceptions import SoftTimeLimitExceeded
from celery import Celery
from celery.signals import worker_process_init
import redis
from .integrations.vizard import VizardClient
from .integrations.scrape_creators import ScrapeCreatorsClient
from .integrations.rapidapi_youtube import RapidAPIYoutubeClient
from .integrations.llm import LLMClient
from .integrations.downloader import Downloader
from .integrations.postmypost import PostMyPostClient
from .processor import VideoProcessor
from .database import SessionLocal, engine, init_database
from .telegram_progress import (
    build_task_context_text,
    update_task_status_message,
    send_avatar_video_to_telegram,
    send_thumbnail_to_telegram,
    send_thumbnail_prompt_review_to_telegram,
    send_yandex_disk_links_to_telegram,
)
from .integrations.elevenlabs_client import ElevenLabsClient
from .integrations.heygen_client import HeyGenClient
from .integrations.thumbnail_generator import ThumbnailGeneratorClient
from .integrations.yandex_disk import YandexDiskClient
from .integrations.deepgram_client import DeepgramClient

# Utilities
from .utils.platform_utils import (
    _get_connected_postmypost_account_ids,
    _get_target_account_ids,
    _get_account_platform_map,
    _pick_platform_ending,
    _get_channel_plate_config,
    _build_account_variant_plan,
    _normalize_platform_code,
)
from .utils.youtube_utils import (
    _validate_youtube_url_or_raise,
    _extract_youtube_video_id,
    _build_youtube_watch_url,
    _build_youtube_download_headers,
    _normalize_external_url,
    _is_youtube_shorts_url,
)
from .utils.vizard_utils import (
    _extract_vizard_project_id,
    _download_vizard_project_clips,
)
from .utils.task_utils import (
    _plan_publish_times_for_outputs,
    _get_base_source_label,
    _build_source_label,
    _upsert_processed_task,
    _resolve_publishing_status,
    _should_publish_immediately,
)
from .utils.media_utils import (
    _estimate_script_minutes,
    _resolve_local_input_video_path,
    _resolve_media_file_path,
)
from .utils.image_data_url import image_file_to_data_url
from .utils.avatar_overlay import apply_transparent_avatar_overlays
from .utils.voice_calibration import (
    count_script_chars,
    get_audio_duration_seconds,
    get_cached_voice_speed,
    get_or_calibrate_voice_speed,
)
from . import models
from dotenv import load_dotenv

load_dotenv()
init_database()

celery_app = Celery('tasks', broker=(os.getenv("REDIS_URL") or "redis://localhost:6379/0").strip())
redis_client = redis.Redis.from_url((os.getenv("REDIS_URL") or "redis://localhost:6379/0").strip())
PROCESS_TASK_SOFT_LIMIT_SECONDS = 21600
PROCESS_TASK_HARD_LIMIT_SECONDS = 25200
YANDEX_UPLOAD_SOFT_TIME_LIMIT_SECONDS = int(os.getenv("YANDEX_UPLOAD_SOFT_TIME_LIMIT_SECONDS", "21600"))
YANDEX_UPLOAD_TIME_LIMIT_SECONDS = int(os.getenv("YANDEX_UPLOAD_TIME_LIMIT_SECONDS", "25200"))
YANDEX_UPLOAD_LOCK_TTL_SECONDS = max(
    600,
    int(os.getenv("YANDEX_UPLOAD_LOCK_TTL_SECONDS", "28800")),
)
AVATAR_INSERT_MONTAGE_TIMEOUT_SECONDS = max(
    60,
    int(os.getenv("AVATAR_INSERT_MONTAGE_TIMEOUT_SECONDS", "1500")),
)
AVATAR_INSERT_MONTAGE_MIN_REMAINING_SECONDS = max(
    120,
    int(os.getenv("AVATAR_INSERT_MONTAGE_MIN_REMAINING_SECONDS", "300")),
)
THUMBNAIL_GENERATION_LOCK_TTL_SECONDS = max(
    300,
    int(os.getenv("THUMBNAIL_GENERATION_LOCK_TTL_SECONDS", "7200")),
)
CELERY_BROKER_VISIBILITY_TIMEOUT_SECONDS = max(
    PROCESS_TASK_HARD_LIMIT_SECONDS + 3600,
    int(os.getenv("CELERY_BROKER_VISIBILITY_TIMEOUT_SECONDS", "28800")),
)
POSTMYPOST_PUBLICATION_RATE_LIMIT = (os.getenv("POSTMYPOST_PUBLICATION_RATE_LIMIT") or "4/m").strip() or "4/m"
celery_app.conf.update(
    broker_connection_retry_on_startup=True,
    broker_transport_options={
        "visibility_timeout": CELERY_BROKER_VISIBILITY_TIMEOUT_SECONDS,
    },
    result_backend_transport_options={
        "visibility_timeout": CELERY_BROKER_VISIBILITY_TIMEOUT_SECONDS,
    },
    visibility_timeout=CELERY_BROKER_VISIBILITY_TIMEOUT_SECONDS,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_annotations={
        "process_content_task": {
            "acks_late": True,
            "reject_on_worker_lost": True,
            "soft_time_limit": PROCESS_TASK_SOFT_LIMIT_SECONDS,
            "time_limit": PROCESS_TASK_HARD_LIMIT_SECONDS,
        },
        "sync_publication_task": {
            "rate_limit": POSTMYPOST_PUBLICATION_RATE_LIMIT,
        },
    },
    beat_schedule={
        "rescue-stale-content-tasks": {
            "task": "rescue_stale_content_tasks",
            "schedule": float(os.getenv("TASK_RESCUE_INTERVAL_SECONDS", "300")),
        },
        "sync-postmypost-publication-statuses": {
            "task": "sync_postmypost_publication_statuses",
            "schedule": float(os.getenv("POSTMYPOST_STATUS_SYNC_INTERVAL_SECONDS", "300")),
        },
    },
)


@worker_process_init.connect
def reset_database_pool_after_worker_fork(**_kwargs):
    engine.dispose()

# Initialize clients
vizard = VizardClient(api_key=(os.getenv("VIZARD_API_KEY") or "").strip())
pmp_client = PostMyPostClient(api_key=(os.getenv("POSTMYPOST_API_KEY") or "").strip())
scraper = ScrapeCreatorsClient(api_key=(os.getenv("SCRAPE_CREATORS_API_KEY") or "").strip())
youtube_downloader = RapidAPIYoutubeClient(
    api_key=(os.getenv("RAPIDAPI_KEY") or "").strip(),
    host=(
        os.getenv("YOUTUBE_DOWNLOAD_RAPIDAPI_HOST")
        or os.getenv("RAPIDAPI_HOST")
        or "youtube-mp4-mp3-downloader.p.rapidapi.com"
    ),
    video_format=os.getenv("YOUTUBE_DOWNLOAD_FORMAT", "720"),
    audio_quality=os.getenv("YOUTUBE_DOWNLOAD_AUDIO_QUALITY", "128"),
    poll_interval_seconds=float(os.getenv("YOUTUBE_DOWNLOAD_POLL_INTERVAL_SECONDS", "2")),
    timeout_seconds=float(os.getenv("YOUTUBE_DOWNLOAD_TIMEOUT_SECONDS", "90")),
)
llm = LLMClient(api_key=(os.getenv("OPENROUTER_API_KEY") or "").strip())
elevenlabs_client = ElevenLabsClient(api_key=(os.getenv("ELEVENLABS_API_KEY") or "").strip())
heygen_client = HeyGenClient(api_key=(os.getenv("HEYGEN_API_KEY") or "").strip())
thumbnail_generator = ThumbnailGeneratorClient()
deepgram_client = DeepgramClient(api_key=(os.getenv("DEEPGRAM_API_KEY") or "").strip())
yandex_disk = YandexDiskClient(
    token=(
        os.getenv("YANDEX_DISK_TOKEN")
        or os.getenv("YADISK_TOKEN")
        or os.getenv("YANDEX_TOKEN")
        or ""
    ).strip()
)


def _fallback_youtube_title_from_context(context_text: str | None) -> str:
    source = re.sub(r"\s+", " ", (context_text or "")).strip()
    if not source:
        return "Видео"
    first_sentence = re.split(r"(?<=[.!?])\s+", source, maxsplit=1)[0].strip()
    title = first_sentence or source
    title = re.sub(r"^(ну|и|а|так|в общем|смотрите)[,\s]+", "", title, flags=re.IGNORECASE).strip()
    return title[:90].strip(" .,;:!?") or "Видео"


def _generate_youtube_title_from_context(task_id: int, context_text: str | None, clip_title: str | None = None) -> str:
    context = re.sub(r"\s+", " ", (context_text or "")).strip()
    generated_title = None
    if context:
        try:
            generated_title = llm.generate_youtube_publication_title(context)
        except Exception as exc:
            logging.warning("Task %s: failed to generate YouTube title from existing context: %s", task_id, exc)

    title = (generated_title or _fallback_youtube_title_from_context(context)).strip()
    logging.info(
        "Task %s: generated YouTube publication title from existing context title=%s context_chars=%s source_clip_title_present=%s",
        task_id,
        title,
        len(context),
        bool((clip_title or "").strip()),
    )
    return title or "Видео"


def _collect_yandex_disk_upload_paths(task: models.VideoTask, rendered_items: List[dict] | None = None) -> List[str]:
    file_paths: List[str] = []
    for item in rendered_items or []:
        local_output = (item.get("output_path") or "").strip()
        if local_output and os.path.isfile(local_output):
            file_paths.append(local_output)
    if not file_paths:
        local_output = (getattr(task, "output_path", None) or "").strip()
        if local_output and os.path.isfile(local_output):
            file_paths.append(local_output)

    try:
        thumbnail_path = (
            ((task.script_meta or {}).get("thumbnail") or {}).get("output_path")
            or ""
        ).strip()
        description_txt_path = (
            ((task.script_meta or {}).get("youtube_description") or {}).get("txt_path")
            or ""
        ).strip()
        instagram_post_description_txt_path = (
            ((task.script_meta or {}).get("instagram_post_5s") or {}).get("description_txt_path")
            or ""
        ).strip()
    except Exception:
        thumbnail_path = ""
        description_txt_path = ""
        instagram_post_description_txt_path = ""

    if thumbnail_path and os.path.isfile(thumbnail_path):
        file_paths.append(thumbnail_path)
    if description_txt_path and os.path.isfile(description_txt_path):
        file_paths.append(description_txt_path)
    if instagram_post_description_txt_path and os.path.isfile(instagram_post_description_txt_path):
        file_paths.append(instagram_post_description_txt_path)

    deduped: List[str] = []
    seen = set()
    for path in file_paths:
        if path in seen:
            continue
        seen.add(path)
        deduped.append(path)
    return deduped


def _extract_instagram_reel_video_url(item: dict) -> str | None:
    if not isinstance(item, dict):
        return None
    candidates = [item]
    if isinstance(item.get("media"), dict):
        candidates.append(item["media"])
    for candidate in candidates:
        for key in ("video_url", "download_url", "url"):
            value = candidate.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")) and ".mp4" in value:
                return value
        versions = candidate.get("video_versions") or []
        if isinstance(versions, list):
            for version in versions:
                if not isinstance(version, dict):
                    continue
                value = version.get("url")
                if isinstance(value, str) and value.startswith(("http://", "https://")):
                    return value
    return None


def _download_url_to_file(url: str, output_path: str, *, timeout_seconds: float = 120.0) -> str | None:
    try:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                with open(output_path, "wb") as fh:
                    for chunk in response.iter_bytes():
                        if chunk:
                            fh.write(chunk)
        return output_path if os.path.isfile(output_path) and os.path.getsize(output_path) > 0 else None
    except Exception as exc:
        logging.warning("Failed to download %s to %s: %s", url, output_path, exc)
        return None


def _extract_audio_track_from_video(video_path: str, output_path: str, *, max_seconds: float = 30.0) -> str | None:
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        video_path,
        "-vn",
        "-t",
        f"{max_seconds:.3f}",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        output_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except Exception as exc:
        logging.warning("Failed to extract Instagram 5s audio from %s: %s", video_path, exc)
        return None
    if result.returncode != 0 or not os.path.isfile(output_path) or os.path.getsize(output_path) < 1024:
        logging.warning(
            "ffmpeg failed to extract Instagram 5s audio from %s: return=%s stderr=%s",
            video_path,
            result.returncode,
            (result.stderr or "")[-1000:],
        )
        return None
    return output_path


@celery_app.task(bind=True, name="refresh_instagram_post_5s_audio_library", soft_time_limit=900, time_limit=960)
def refresh_instagram_post_5s_audio_library(self, user_id: int, profile: str):
    db = SessionLocal()
    user = None
    profile_value = (profile or "").strip()
    try:
        user = db.query(models.User).get(user_id)
        if not user:
            return {"status": "missing_user", "created": 0}
        user.instagram_post_5s_audio_profile = profile_value
        user.instagram_post_5s_audio_status = "refreshing"
        user.instagram_post_5s_audio_error = None
        db.commit()

        reels_payload = scraper.get_instagram_user_reels(profile_value, max_items=20)
        reels = (reels_payload or {}).get("items") or []
        if not reels:
            raise RuntimeError((reels_payload or {}).get("error") or "No reels found for Instagram profile")

        audio_dir = (os.getenv("INSTAGRAM_POST_5S_AUDIO_DIR") or "/app/database/media/instagram-post-5s/audio").strip()
        temp_dir = os.path.join(audio_dir, "tmp")
        os.makedirs(audio_dir, exist_ok=True)
        os.makedirs(temp_dir, exist_ok=True)

        created = 0
        new_tracks: list[dict] = []
        for index, item in enumerate(reels[:20], start=1):
            if not isinstance(item, dict):
                continue
            media = item.get("media") if isinstance(item.get("media"), dict) else item
            if item.get("has_audio") is False or media.get("has_audio") is False:
                continue
            video_url = _extract_instagram_reel_video_url(item)
            if not video_url:
                continue
            code = str(
                media.get("code")
                or media.get("shortcode")
                or item.get("code")
                or item.get("shortcode")
                or media.get("id")
                or media.get("pk")
                or item.get("id")
                or f"reel_{index}"
            )
            safe_code = re.sub(r"[^a-zA-Z0-9_-]+", "_", code).strip("_")[:80] or f"reel_{index}"
            video_path = os.path.join(temp_dir, f"u{user.id}_{safe_code}.mp4")
            audio_path = os.path.join(audio_dir, f"u{user.id}_{safe_code}.m4a")
            if not _download_url_to_file(video_url, video_path, timeout_seconds=180):
                continue
            extracted = _extract_audio_track_from_video(video_path, audio_path)
            try:
                os.remove(video_path)
            except OSError:
                pass
            if not extracted:
                continue
            new_tracks.append(
                {
                    "user_id": user.id,
                    "source_profile": profile_value,
                    "source_url": item.get("url") or f"https://www.instagram.com/reel/{safe_code}/",
                    "source_code": code,
                    "file_path": audio_path,
                }
            )
            created += 1

        if created <= 0:
            raise RuntimeError("No usable audio tracks were extracted from the latest reels")

        old_tracks = db.query(models.InstagramPost5sAudioTrack).filter(
            models.InstagramPost5sAudioTrack.user_id == user.id
        ).all()
        old_paths = [track.file_path for track in old_tracks if track.file_path]
        db.query(models.InstagramPost5sAudioTrack).filter(
            models.InstagramPost5sAudioTrack.user_id == user.id
        ).delete()
        for track_data in new_tracks:
            db.add(
                models.InstagramPost5sAudioTrack(**track_data)
            )

        for old_path in old_paths:
            if old_path and os.path.isfile(old_path):
                try:
                    os.remove(old_path)
                except OSError:
                    logging.warning("Failed to remove old Instagram 5s audio: %s", old_path)

        user.instagram_post_5s_audio_status = "ready"
        user.instagram_post_5s_audio_error = None
        user.instagram_post_5s_audio_refreshed_at = datetime.datetime.utcnow()
        db.commit()
        return {"status": "ready", "created": created}
    except Exception as exc:
        logging.exception("Failed to refresh Instagram post 5s audio library for user=%s profile=%s", user_id, profile_value)
        if user:
            user.instagram_post_5s_audio_status = "failed"
            user.instagram_post_5s_audio_error = str(exc)[:500]
            db.commit()
        return {"status": "failed", "created": 0, "error": str(exc)[:500]}
    finally:
        db.close()


def _upload_files_to_yandex_disk(file_paths: List[str]) -> List[dict]:
    if not yandex_disk.is_configured:
        raise Exception("YANDEX_DISK_TOKEN is not configured for avatar upload")

    target_root = (os.getenv("YANDEX_DISK_AVATAR_DIR") or "disk:/").strip()
    target_dir = target_root.rstrip("/") or "disk:/"
    ensured_dir = yandex_disk.ensure_directory(target_dir)

    uploaded: List[dict] = []
    for local_path in file_paths:
        if not local_path or not os.path.isfile(local_path):
            logging.warning("Skipping missing Yandex.Disk upload file: %s", local_path)
            continue
        remote_path = f"{ensured_dir.rstrip('/')}/{os.path.basename(local_path)}"
        remote_saved_path = yandex_disk.upload_file(local_path=local_path, remote_path=remote_path, overwrite=True)
        public_url = yandex_disk.publish_and_get_public_url(remote_saved_path)
        uploaded.append(
            {
                "local_output_path": local_path,
                "remote_path": remote_saved_path,
                "public_url": public_url,
            }
        )
    return uploaded


def _release_redis_lock(lock_key: str, lock_token: str) -> None:
    try:
        current = redis_client.get(lock_key)
        if current and current.decode("utf-8", errors="ignore") == lock_token:
            redis_client.delete(lock_key)
    except Exception as exc:
        logging.warning("Failed to release Redis lock %s: %s", lock_key, exc)


@celery_app.task(
    name="upload_yandex_disk_task",
    bind=True,
    max_retries=3,
    soft_time_limit=YANDEX_UPLOAD_SOFT_TIME_LIMIT_SECONDS,
    time_limit=YANDEX_UPLOAD_TIME_LIMIT_SECONDS,
)
def upload_yandex_disk_task(self, task_id: int, file_paths: List[str] | None = None):
    lock_key = f"yandex_disk_upload:{task_id}"
    lock_token = str(uuid.uuid4())
    lock_acquired = False
    db = SessionLocal()
    task = db.query(models.VideoTask).get(task_id)
    if not task:
        db.close()
        return
    try:
        try:
            lock_acquired = bool(
                redis_client.set(lock_key, lock_token, nx=True, ex=YANDEX_UPLOAD_LOCK_TTL_SECONDS)
            )
        except Exception as exc:
            logging.warning("Task %s: Redis upload lock unavailable, continuing without lock: %s", task_id, exc)
            lock_acquired = True
        if not lock_acquired:
            logging.info("Task %s: Yandex.Disk upload is already locked by another worker; skipping duplicate.", task_id)
            return

        paths = _collect_yandex_disk_upload_paths(task) if file_paths is None else list(file_paths)
        if not paths:
            logging.warning("Task %s: no files available for Yandex.Disk upload", task_id)
            return
        current_meta = dict(task.script_meta or {})
        if current_meta.get("yandex_disk_upload_status") == "completed":
            logging.info("Task %s: Yandex.Disk upload is already completed; skipping duplicate upload.", task_id)
            return
        if current_meta.get("yandex_disk_upload_status") == "in_progress":
            logging.warning(
                "Task %s: Yandex.Disk upload was marked in_progress but no active lock was found; resuming upload.",
                task_id,
            )
        current_meta["yandex_disk_upload_status"] = "in_progress"
        current_meta["yandex_disk_upload_started_at"] = datetime.datetime.utcnow().isoformat()
        current_meta["yandex_disk_upload_lock_key"] = lock_key
        current_meta["yandex_disk_upload_attempt"] = int(self.request.retries or 0) + 1
        task.script_meta = current_meta
        db.commit()

        update_task_status_message(
            db,
            task,
            stage="Выгрузка",
            detail="Сохраняю готовые файлы в Яндекс.Диск.",
        )
        uploads = _upload_files_to_yandex_disk(paths)

        current_meta = dict(task.script_meta or {})
        current_meta["yandex_disk_uploads"] = uploads
        current_meta.pop("yandex_disk_upload_error", None)
        current_meta["yandex_disk_upload_status"] = "completed"
        current_meta["yandex_disk_uploaded_at"] = datetime.datetime.utcnow().isoformat()
        task.script_meta = current_meta
        db.commit()
        db.refresh(task)

        send_yandex_disk_links_to_telegram(task, uploads)
        update_task_status_message(
            db,
            task,
            stage="Готово",
            detail="Финальный файл собран и сохранен в Яндекс.Диск.",
            ok=True,
        )
    except SoftTimeLimitExceeded as exc:
        logging.exception("Task %s: Yandex.Disk async upload exceeded soft time limit", task_id)
        try:
            db.rollback()
        except Exception:
            pass
        task = db.query(models.VideoTask).get(task_id)
        if task:
            current_meta = dict(task.script_meta or {})
            current_meta["yandex_disk_upload_status"] = "retrying" if self.request.retries < self.max_retries else "failed"
            current_meta["yandex_disk_upload_error"] = "Yandex.Disk upload exceeded soft time limit"
            current_meta["yandex_disk_upload_failed_at"] = datetime.datetime.utcnow().isoformat()
            task.script_meta = current_meta
            db.commit()
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))
        raise
    except Exception as exc:
        logging.exception("Task %s: Yandex.Disk async upload failed: %s", task_id, exc)
        try:
            db.rollback()
        except Exception:
            pass
        task = db.query(models.VideoTask).get(task_id)
        if task:
            current_meta = dict(task.script_meta or {})
            current_meta["yandex_disk_upload_status"] = (
                "retrying" if self.request.retries < self.max_retries else "failed"
            )
            current_meta["yandex_disk_upload_error"] = str(exc)[:500]
            current_meta["yandex_disk_upload_failed_at"] = datetime.datetime.utcnow().isoformat()
            task.script_meta = current_meta
            db.commit()
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))
        if task:
            update_task_status_message(
                db,
                task,
                stage="Готово",
                detail=f"Финальный файл собран. Выгрузка в Яндекс.Диск не удалась: {str(exc)[:220]}",
                ok=True,
            )
    finally:
        if lock_acquired:
            _release_redis_lock(lock_key, lock_token)
        db.close()


downloader = Downloader(output_dir=(os.getenv("OUTPUT_DIR") or "./output").strip())
processor = VideoProcessor()
INSTAGRAM_POST_FIVE_SECOND_TASK_TYPES = {"avatar_instagram_post_5s"}
INFOGRAPHIC_REELS_TASK_TYPES = {"infographic_reels"}
READY_TO_PUBLISH_VIDEO_TASK_TYPES = {*INSTAGRAM_POST_FIVE_SECOND_TASK_TYPES, *INFOGRAPHIC_REELS_TASK_TYPES}
AVATAR_VERTICAL_TASK_TYPES = {"avatar_vertical", "avatar_instagram", "avatar_shorts", *INSTAGRAM_POST_FIVE_SECOND_TASK_TYPES}
AVATAR_HORIZONTAL_TASK_TYPES = {"avatar_horizontal", "avatar_youtube"}
AVATAR_READY_HEYGEN_TASK_TYPES = {"avatar_heygen", *AVATAR_VERTICAL_TASK_TYPES, *AVATAR_HORIZONTAL_TASK_TYPES}
SHORT_AVATAR_TASK_TYPES = AVATAR_VERTICAL_TASK_TYPES
AVATAR_TASK_TYPES = {*AVATAR_READY_HEYGEN_TASK_TYPES}
AVATAR_HORIZONTAL_RENDERER = (os.getenv("AVATAR_HORIZONTAL_RENDERER") or "hyperframes_only").strip().lower()
AVATAR_HORIZONTAL_REMOTION_FALLBACK_RENDERERS = {
    "auto",
    "hybrid",
    "hyperframes_fallback",
    "hyperframes-with-remotion-fallback",
    "hyperframes_with_remotion_fallback",
    "remotion_fallback",
    "remotion-fallback",
}
AVATAR_SCRIPT_MIN_MINUTES = int(os.getenv("AVATAR_SCRIPT_MIN_MINUTES", "4"))
AVATAR_SCRIPT_MAX_MINUTES = int(os.getenv("AVATAR_SCRIPT_MAX_MINUTES", "6"))
AVATAR_SCRIPT_WPM = int(os.getenv("AVATAR_SCRIPT_WORDS_PER_MINUTE", "110"))
HYPERFRAMES_RENDER_TIMEOUT_SECONDS = max(
    300,
    int(
        os.getenv(
            "HYPERFRAMES_RENDER_TIMEOUT_SECONDS",
            str(max(300, PROCESS_TASK_SOFT_LIMIT_SECONDS - 300)),
        )
    ),
)
HYPERFRAMES_VERTICAL_RENDER_TIMEOUT_SECONDS = max(
    300,
    int(os.getenv("HYPERFRAMES_VERTICAL_RENDER_TIMEOUT_SECONDS", "3600")),
)
REMOTION_RENDER_TIMEOUT_SECONDS = max(
    600,
    int(os.getenv("REMOTION_RENDER_TIMEOUT_SECONDS", "7200")),
)
REMOTION_RENDER_MAX_RUNTIME_SECONDS = max(
    REMOTION_RENDER_TIMEOUT_SECONDS,
    int(os.getenv("REMOTION_RENDER_MAX_RUNTIME_SECONDS", str(REMOTION_RENDER_TIMEOUT_SECONDS))),
)
REMOTION_RENDER_IDLE_TIMEOUT_SECONDS = max(
    300,
    int(os.getenv("REMOTION_RENDER_IDLE_TIMEOUT_SECONDS", "1200")),
)
HYPERFRAMES_STEP_TIMEOUT_SECONDS = max(
    120,
    int(os.getenv("HYPERFRAMES_STEP_TIMEOUT_SECONDS", "3600")),
)
HYPERFRAMES_VERTICAL_MAX_FULL_RENDER_SECONDS = max(
    0,
    int(os.getenv("HYPERFRAMES_VERTICAL_MAX_FULL_RENDER_SECONDS", "900")),
)
if AVATAR_SCRIPT_MIN_MINUTES < 1:
    AVATAR_SCRIPT_MIN_MINUTES = 1
if AVATAR_SCRIPT_MAX_MINUTES < AVATAR_SCRIPT_MIN_MINUTES:
    AVATAR_SCRIPT_MAX_MINUTES = AVATAR_SCRIPT_MIN_MINUTES
if AVATAR_SCRIPT_WPM < 80:
    AVATAR_SCRIPT_WPM = 80


def _is_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


ENABLE_HEYGEN_READY_TRANSCRIBE = _is_truthy(os.getenv("AVATAR_HEYGEN_READY_TRANSCRIBE", "1"))
THUMBNAIL_PROMPT_REVIEW_ENABLED = _is_truthy(os.getenv("THUMBNAIL_PROMPT_REVIEW_ENABLED", "1"))
THUMBNAIL_PROMPT_REVIEW_TIMEOUT_SECONDS = max(
    60,
    int(os.getenv("THUMBNAIL_PROMPT_REVIEW_TIMEOUT_SECONDS", str(24 * 60 * 60))),
)
THUMBNAIL_PROMPT_REVIEW_POLL_SECONDS = max(
    2,
    int(os.getenv("THUMBNAIL_PROMPT_REVIEW_POLL_SECONDS", "5")),
)
VERTICAL_THUMBNAIL_INTRO_SECONDS = max(
    0.01,
    min(0.10, float(os.getenv("VERTICAL_THUMBNAIL_INTRO_SECONDS", "0.10"))),
)
REELS_VERTICAL_COVER_SECONDS = max(
    0.01,
    min(0.10, float(os.getenv("REELS_VERTICAL_COVER_SECONDS", "0.10"))),
)


def _is_deadlock_error(exc: Exception) -> bool:
    current: BaseException | None = exc
    while current is not None:
        if getattr(current, "pgcode", None) == "40P01":
            return True
        current = getattr(current, "__cause__", None) or getattr(current, "__context__", None)
    return "deadlock detected" in str(exc).lower()


def _extract_heygen_video_id(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    if raw.lower().startswith("heygen:"):
        raw = raw.split(":", 1)[1].strip()
    if re.fullmatch(r"[0-9a-fA-F]{32}", raw):
        return raw
    parsed = urlparse(raw)
    if parsed.query:
        video_id = parse_qs(parsed.query).get("video_id", [""])[0].strip()
        if re.fullmatch(r"[0-9a-fA-F]{32}", video_id):
            return video_id
    return None


def _extract_hook_from_text(value: str | None) -> str:
    text = re.sub(r"\s+", " ", (value or "")).strip()
    if not text:
        return ""
    sentences = re.split(r"(?<=[.!?…])\s+", text)
    selected_sentences = []
    for sentence in sentences[:2]:
        clean_sentence = sentence.strip()
        if clean_sentence:
            selected_sentences.append(clean_sentence)
        if len(" ".join(selected_sentences)) >= 120:
            break
    hook = " ".join(selected_sentences).strip() if selected_sentences else text
    hook = hook.strip(" \"'«»")
    if not hook:
        return ""
    words = hook.split()
    if len(words) > 24:
        hook = " ".join(words[:24]).strip()
    if len(hook) > 170:
        hook = hook[:170].rsplit(" ", 1)[0].strip()
    if hook and hook[-1] not in ".!?…":
        hook = f"{hook}."
    return hook


def _adapt_hook_for_cta(hook_text: str, context_text: str) -> str:
    source_hook = (hook_text or "").strip()
    if not source_hook:
        return ""
    try:
        adapted = llm._complete(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты редактор YouTube-описаний. "
                        "Адаптируй хук под CTA для описания, сохраняя смысл первых 10 секунд.\n"
                        "Требования:\n"
                        "- Не копируй исходную фразу дословно, перефразируй.\n"
                        "- Не добавляй новых фактов.\n"
                        "- 8-18 слов, 1 предложение, русский язык.\n"
                        "- Без эмодзи, без кавычек, без списков.\n"
                        "- Верни только финальную фразу."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Исходный хук:\n{source_hook}\n\n"
                        f"Контекст:\n{(context_text or source_hook)[:1200]}"
                    ),
                },
            ],
            temperature=0.45,
        )
    except Exception:
        adapted = None

    clean = re.sub(r"\s+", " ", (adapted or "")).strip().strip("\"'«»")
    if not clean:
        return source_hook
    if len(clean) > 170:
        clean = clean[:170].rsplit(" ", 1)[0].strip()
    if clean and clean[-1] not in ".!?…":
        clean = f"{clean}."
    return clean


def _build_cta_from_hook(hook_text: str) -> str:
    hook = (hook_text or "").strip().rstrip(".!?…")
    if hook:
        return f"Смотри до конца: {hook}."
    return "Смотри до конца — в видео главный разбор по теме."


def _build_trigger_title_from_hook(hook_text: str, context_text: str) -> str:
    source_hook = (hook_text or "").strip()
    fallback = "Это касается каждого"
    if not source_hook:
        return fallback
    try:
        generated = llm._complete(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты YouTube-редактор. Сгенерируй триггерный заголовок ролика.\n"
                        "Требования:\n"
                        "- 4-9 слов.\n"
                        "- Высокий CTR, но без обмана и выдумывания фактов.\n"
                        "- Сохраняй тему хука и контекста.\n"
                        "- Без эмодзи, без кавычек, без двоеточий, без точки в конце.\n"
                        "- Верни только заголовок."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Хук:\n{source_hook}\n\n"
                        f"Контекст:\n{(context_text or source_hook)[:1200]}"
                    ),
                },
            ],
            temperature=0.65,
        )
    except Exception:
        generated = None

    title = re.sub(r"\s+", " ", (generated or "")).strip().strip("\"'«»")
    if not title:
        title = source_hook
    title = title.replace(":", " ").strip()
    title = title.rstrip(".!?…")
    words = [w for w in title.split(" ") if w]
    if len(words) > 9:
        title = " ".join(words[:9]).strip()
    if len(title) > 90:
        title = title[:90].rsplit(" ", 1)[0].strip()
    return title or fallback


def _build_avatar_description_text(
    *,
    script_text: str,
    factual_outline: str,
    source_title: str | None,
    description_template: str | None,
) -> tuple[str, str, str, str]:
    base_for_hook = (script_text or factual_outline or source_title or "").strip()
    raw_hook_text = _extract_hook_from_text(base_for_hook)
    adapted_hook_text = _adapt_hook_for_cta(raw_hook_text, base_for_hook)
    trigger_title = _build_trigger_title_from_hook(adapted_hook_text, base_for_hook)
    cta_text = _build_cta_from_hook(adapted_hook_text)
    template = (description_template or "").strip()
    final_text = f"{trigger_title}\n\n{cta_text}\n\n{template}".strip()
    return adapted_hook_text, trigger_title, cta_text, final_text


def _write_avatar_description_file(task_id: int, description_text: str) -> str | None:
    content = (description_text or "").strip()
    if not content:
        return None
    output_dir = os.getenv("OUTPUT_DIR", "./output").strip()
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"youtube_description_{task_id}.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content + "\n")
    return path


def _write_publication_description_file(task_id: int, description_text: str, *, prefix: str = "publication_description") -> str | None:
    content = (description_text or "").strip()
    if not content:
        return None
    output_dir = os.getenv("OUTPUT_DIR", "./output").strip()
    os.makedirs(output_dir, exist_ok=True)
    safe_prefix = re.sub(r"[^a-zA-Z0-9_-]+", "_", prefix).strip("_") or "publication_description"
    path = os.path.join(output_dir, f"{safe_prefix}_{task_id}.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content + "\n")
    return path


def _strip_cta_fallback(text: str | None) -> str:
    content = (text or "").strip()
    if not content:
        return ""
    cta_patterns = [
        r"\bподпиш\w*\b.*?(?:[.!?…]|$)",
        r"\bлайк\w*\b.*?(?:[.!?…]|$)",
        r"\bкоммент\w*\b.*?(?:[.!?…]|$)",
        r"\bсохран\w*\b.*?(?:[.!?…]|$)",
        r"\bрепост\w*\b.*?(?:[.!?…]|$)",
        r"\bдирект\b.*?(?:[.!?…]|$)",
        r"\bссылк\w*\b.*?(?:[.!?…]|$)",
        r"\bпромокод\w*\b.*?(?:[.!?…]|$)",
        r"\bжми\w*\b.*?(?:[.!?…]|$)",
        r"\bпереход\w*\b.*?(?:[.!?…]|$)",
        r"\bfollow\b.*?(?:[.!?…]|$)",
        r"\blike\b.*?(?:[.!?…]|$)",
        r"\bsubscribe\b.*?(?:[.!?…]|$)",
        r"\blink in bio\b.*?(?:[.!?…]|$)",
    ]
    cleaned = content
    for pattern in cta_patterns:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE | re.UNICODE)
    return re.sub(r"\s+", " ", cleaned).strip()


def _run_remotion_pipeline(
    task_id: int,
    input_video: str,
    script: str,
    transcript_json_path: str | None = None,
    overlay_coverage_percent: int = 50,
) -> str | None:
    import subprocess
    import json

    logging.info("Task %s: Starting Remotion pipeline on %s", task_id, input_video)
    montage_script = "/app/hf-montage-test/tools/smart_montage_pipeline.py"
    remotion_dir = "/app/remotion-auto"
    scene_plan_index = "/app/hf-montage-test/index.html"

    out_dir = os.getenv("OUTPUT_DIR", "./output").strip()
    out_plan = os.path.join(out_dir, f"scene-plan_{task_id}.json")
    out_words = os.path.join(out_dir, f"scene-word-cues_{task_id}.json")
    out_transcript = os.path.join(out_dir, f"transcript.deepgram_{task_id}.json")
    script_context_path = os.path.join(out_dir, f"scenario_context_{task_id}.txt")
    os.makedirs(out_dir, exist_ok=True)

    render_max_runtime_seconds = min(
        REMOTION_RENDER_MAX_RUNTIME_SECONDS,
        max(300, PROCESS_TASK_SOFT_LIMIT_SECONDS - 600),
    )
    render_idle_timeout_seconds = min(
        REMOTION_RENDER_IDLE_TIMEOUT_SECONDS,
        max(300, render_max_runtime_seconds),
    )
    step_timeout_seconds = min(
        HYPERFRAMES_STEP_TIMEOUT_SECONDS,
        max(120, PROCESS_TASK_SOFT_LIMIT_SECONDS - 600),
    )
    overlay_coverage_percent = max(0, min(100, int(overlay_coverage_percent or 0)))

    def probe_duration_seconds(path: str) -> float | None:
        if not os.path.exists(path):
            return None
        try:
            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    path,
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )
            if probe.returncode != 0:
                logging.warning(
                    "Task %s: ffprobe duration failed for %s. STDERR: %s",
                    task_id,
                    path,
                    probe.stderr[-1000:],
                )
                return None
            duration = float((probe.stdout or "").strip() or 0)
            return duration if duration > 0 else None
        except Exception as exc:
            logging.warning("Task %s: Failed to probe duration for %s: %s", task_id, path, exc)
            return None

    expected_render_duration = probe_duration_seconds(input_video)

    def is_usable_remotion_output(path: str) -> bool:
        if not os.path.exists(path):
            return False
        try:
            file_size = os.path.getsize(path)
        except OSError:
            return False
        if file_size < 128 * 1024:
            logging.warning("Task %s: Remotion output is too small: %s bytes", task_id, file_size)
            return False

        actual_duration = probe_duration_seconds(path)
        if actual_duration is None:
            return False
        if expected_render_duration and expected_render_duration > 1:
            min_duration = max(1.0, expected_render_duration * 0.90)
            if actual_duration < min_duration:
                logging.warning(
                    "Task %s: Remotion output duration is too short: %.3fs < %.3fs expected minimum",
                    task_id,
                    actual_duration,
                    min_duration,
                )
                return False
        logging.info(
            "Task %s: Remotion output validated: path=%s size=%s duration=%.3fs expected=%.3fs",
            task_id,
            path,
            file_size,
            actual_duration,
            expected_render_duration or 0,
        )
        return True

    cmd_plan = [
        "python3",
        montage_script,
        "--video",
        input_video,
        "--index",
        scene_plan_index,
        "--out-plan",
        out_plan,
        "--out-transcript",
        out_transcript,
        "--overlay-coverage-percent",
        str(overlay_coverage_percent),
        "--deepgram-intelligence",
        "--plan-target",
        "remotion",
    ]
    clean_script_context = re.sub(r"\s+", " ", (script or "")).strip()
    if clean_script_context:
        with open(script_context_path, "w", encoding="utf-8") as fp:
            fp.write(clean_script_context)
        cmd_plan.extend(["--script-text-file", script_context_path])
    if transcript_json_path and os.path.exists(transcript_json_path):
        cmd_plan.extend(["--reuse-transcript", transcript_json_path])

    def run_scene_planner(cmd: list[str], label: str):
        logging.info("Task %s: %s: %s", task_id, label, " ".join(cmd))
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=step_timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            logging.error(
                "Task %s: %s timed out after %ss. STDOUT: %s\nSTDERR: %s",
                task_id,
                label,
                step_timeout_seconds,
                (exc.stdout or "")[-4000:],
                (exc.stderr or "")[-4000:],
            )
            return None

    res = run_scene_planner(cmd_plan, "Running Remotion scene planner")
    if res is None:
        return None
    if res.returncode != 0:
        combined_error = f"{res.stdout or ''}\n{res.stderr or ''}"
        fallback_cmd_plan = [*cmd_plan, "--skip-llm"]
        logging.warning(
            "Task %s: Remotion scene planner failed; retrying with deterministic planner. STDERR: %s",
            task_id,
            combined_error[-4000:],
        )
        res = run_scene_planner(fallback_cmd_plan, "Running Remotion deterministic scene planner")
        if res is None:
            return None
        if res.returncode != 0:
            logging.error("Task %s: Remotion scene planner failed. STDOUT: %s\nSTDERR: %s", task_id, res.stdout, res.stderr)
            return None

    out_words_generated = out_plan.replace("scene-plan_", "scene-word-cues_")
    if os.path.exists(out_words_generated):
        if out_words_generated != out_words:
            os.rename(out_words_generated, out_words)
    else:
        out_words_generated = os.path.join(os.path.dirname(out_plan), "scene-word-cues.generated.json")
        if os.path.exists(out_words_generated):
            os.rename(out_words_generated, out_words)

    if not os.path.exists(out_words):
        try:
            with open(out_plan, "r", encoding="utf-8") as fp:
                scenes = json.load(fp)
            scene_count = len(scenes) if isinstance(scenes, list) else 0
        except Exception:
            scene_count = 0
        fallback_cues = [[] for _ in range(scene_count)]
        with open(out_words, "w", encoding="utf-8") as fp:
            json.dump(fallback_cues, fp, ensure_ascii=False, indent=2)
        logging.warning(
            "Task %s: Remotion scene word cues were missing after planner run. "
            "Created fallback cues file: %s (scenes=%s)",
            task_id,
            out_words,
            scene_count,
        )

    final_output = os.path.join(out_dir, f"remotion_{task_id}.mp4")
    cmd_render = [
        "npm",
        "run",
        "render:auto",
        "--",
        "--video",
        input_video,
        "--scene-plan",
        out_plan,
        "--word-cues",
        out_words,
        "--out",
        final_output,
    ]
    progress_re = re.compile(r"\b(?:Rendered|Encoded)\s+(\d+)/(\d+)\b")

    def run_remotion_render_with_progress_watchdog() -> tuple[int | None, str]:
        output_tail: list[str] = []
        max_tail_lines = 250
        started_at = time.monotonic()
        last_progress_at = started_at
        last_activity_at = started_at
        last_log_at = started_at
        best_done = 0
        best_total = 0

        logging.info(
            "Task %s: Running Remotion render with progress watchdog: %s "
            "(max_runtime=%ss idle_timeout=%ss)",
            task_id,
            " ".join(cmd_render),
            render_max_runtime_seconds,
            render_idle_timeout_seconds,
        )

        process = subprocess.Popen(
            cmd_render,
            cwd=remotion_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        selector = selectors.DefaultSelector()
        if process.stdout:
            selector.register(process.stdout, selectors.EVENT_READ)

        try:
            while True:
                now = time.monotonic()
                return_code = process.poll()
                events = selector.select(timeout=1.0)

                for key, _ in events:
                    line = key.fileobj.readline()
                    if not line:
                        continue
                    last_activity_at = now
                    output_tail.append(line)
                    if len(output_tail) > max_tail_lines:
                        output_tail = output_tail[-max_tail_lines:]
                    match = progress_re.search(line)
                    if match:
                        done = int(match.group(1))
                        total = int(match.group(2))
                        if done > best_done or total != best_total:
                            best_done = done
                            best_total = total
                            last_progress_at = now

                if return_code is not None:
                    if process.stdout:
                        for line in process.stdout.readlines():
                            output_tail.append(line)
                    return return_code, "".join(output_tail[-max_tail_lines:])

                runtime = now - started_at
                idle_for = now - last_progress_at
                activity_idle_for = now - last_activity_at
                if best_total and now - last_log_at >= 60:
                    logging.info(
                        "Task %s: Remotion still rendering: %s/%s frames, runtime=%ss, progress_idle=%ss",
                        task_id,
                        best_done,
                        best_total,
                        int(runtime),
                        int(idle_for),
                    )
                    last_log_at = now

                if runtime > render_max_runtime_seconds:
                    process.kill()
                    process.wait(timeout=30)
                    logging.error(
                        "Task %s: Remotion render exceeded max runtime %ss. "
                        "Last progress: %s/%s frames. Output tail: %s",
                        task_id,
                        render_max_runtime_seconds,
                        best_done,
                        best_total,
                        "".join(output_tail[-120:])[-4000:],
                    )
                    return None, "".join(output_tail[-max_tail_lines:])

                if best_done > 0 and idle_for > render_idle_timeout_seconds:
                    process.kill()
                    process.wait(timeout=30)
                    logging.error(
                        "Task %s: Remotion render stalled for %ss with no frame progress. "
                        "Last progress: %s/%s frames. Output tail: %s",
                        task_id,
                        render_idle_timeout_seconds,
                        best_done,
                        best_total,
                        "".join(output_tail[-120:])[-4000:],
                    )
                    return None, "".join(output_tail[-max_tail_lines:])
                if best_done == 0 and activity_idle_for > render_idle_timeout_seconds:
                    process.kill()
                    process.wait(timeout=30)
                    logging.error(
                        "Task %s: Remotion render produced no frame progress or output for %ss. "
                        "Output tail: %s",
                        task_id,
                        render_idle_timeout_seconds,
                        "".join(output_tail[-120:])[-4000:],
                    )
                    return None, "".join(output_tail[-max_tail_lines:])
        finally:
            selector.close()
            if process.poll() is None:
                process.kill()
                process.wait(timeout=30)

    render_returncode, render_output_tail = run_remotion_render_with_progress_watchdog()
    if render_output_tail:
        logging.info("Task %s: Remotion output tail: %s", task_id, render_output_tail[-4000:])
    if render_returncode is None:
        if is_usable_remotion_output(final_output):
            logging.warning(
                "Task %s: Remotion render watchdog stopped, but output MP4 is already valid. Accepting: %s",
                task_id,
                final_output,
            )
            return final_output
        return None
    if render_returncode != 0:
        logging.error(
            "Task %s: Remotion render failed with exit code %s. Output tail: %s",
            task_id,
            render_returncode,
            render_output_tail,
        )
        return None
    if is_usable_remotion_output(final_output):
        return final_output
    logging.error("Task %s: Remotion render produced no usable output.", task_id)
    return None


def _run_hyperframes_pipeline(
    task_id: int,
    input_video: str,
    script: str,
    transcript_json_path: str | None = None,
    overlay_coverage_percent: int = 50,
    layout: str = "vertical_reels",
) -> str | None:
    import subprocess
    import json
    logging.info("Task %s: Starting Hyperframes pipeline layout=%s on %s", task_id, layout, input_video)
    montage_script = "/app/hf-montage-test/tools/smart_montage_pipeline.py"
    hyperframes_dir = "/app/hyperframes-auto"
    scene_plan_index = "/app/hf-montage-test/index.html"
    
    out_dir = os.getenv("OUTPUT_DIR", "./output").strip()
    out_plan = os.path.join(out_dir, f"scene-plan_{task_id}.json")
    out_words = os.path.join(out_dir, f"scene-word-cues_{task_id}.json")
    out_transcript = os.path.join(out_dir, f"transcript.deepgram_{task_id}.json")
    out_semantic_blocks = os.path.join(out_dir, f"semantic-blocks_{task_id}.json")
    script_context_path = os.path.join(out_dir, f"scenario_context_{task_id}.txt")
    os.makedirs(out_dir, exist_ok=True)

    def save_hyperframes_heartbeat(
        stage: str,
        *,
        progress_percent: int | None = None,
        status: str = "rendering",
    ) -> None:
        heartbeat_db = SessionLocal()
        try:
            row = heartbeat_db.query(models.VideoTask).get(task_id)
            if not row:
                return
            current_meta = dict(row.script_meta or {})
            render_meta = dict(current_meta.get("hyperframes_render") or {})
            render_meta.update(
                {
                    "status": status,
                    "layout": layout,
                    "stage": str(stage or "")[:180],
                    "progress_percent": progress_percent,
                    "updated_at": datetime.datetime.utcnow().isoformat() + "Z",
                }
            )
            current_meta["hyperframes_render"] = render_meta
            row.script_meta = current_meta
            row.updated_at = datetime.datetime.utcnow()
            heartbeat_db.commit()
        except Exception as exc:
            logging.warning("Task %s: failed to save Hyperframes heartbeat: %s", task_id, exc)
            try:
                heartbeat_db.rollback()
            except Exception:
                pass
        finally:
            heartbeat_db.close()

    def probe_duration_seconds(path: str) -> float | None:
        if not os.path.exists(path):
            return None
        try:
            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    path,
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )
            if probe.returncode != 0:
                logging.warning(
                    "Task %s: ffprobe duration failed for %s. STDERR: %s",
                    task_id,
                    path,
                    probe.stderr[-1000:],
                )
                return None
            duration = float((probe.stdout or "").strip() or 0)
            return duration if duration > 0 else None
        except Exception as exc:
            logging.warning("Task %s: Failed to probe duration for %s: %s", task_id, path, exc)
            return None

    def probe_audio_codec(path: str) -> str | None:
        if not os.path.exists(path):
            return None
        try:
            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "a:0",
                    "-show_entries",
                    "stream=codec_name",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    path,
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )
            if probe.returncode != 0:
                return None
            codec = (probe.stdout or "").strip().lower()
            return codec or None
        except Exception as exc:
            logging.warning("Task %s: Failed to probe audio codec for %s: %s", task_id, path, exc)
            return None

    def normalize_video_for_hyperframes(path: str) -> str | None:
        normalized_path = os.path.join(out_dir, f"hyperframes_source_{task_id}.mp4")
        temp_path = f"{normalized_path}.tmp.mp4"
        audio_codec = probe_audio_codec(path)
        audio_args = ["-c:a", "copy"] if audio_codec == "aac" else ["-c:a", "aac", "-b:a", "256k"]
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            path,
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            "-g",
            "30",
            "-keyint_min",
            "30",
            "-sc_threshold",
            "0",
            "-movflags",
            "+faststart",
            *audio_args,
            temp_path,
        ]
        logging.info("Task %s: Normalizing video for Hyperframes: %s", task_id, " ".join(cmd))
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=step_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            logging.error(
                "Task %s: Hyperframes source normalization timed out after %ss. STDOUT: %s\nSTDERR: %s",
                task_id,
                step_timeout_seconds,
                (exc.stdout or "")[-4000:],
                (exc.stderr or "")[-4000:],
            )
            return None
        if result.returncode != 0:
            logging.error(
                "Task %s: Hyperframes source normalization failed. STDOUT: %s\nSTDERR: %s",
                task_id,
                result.stdout[-4000:],
                result.stderr[-4000:],
            )
            return None
        try:
            os.replace(temp_path, normalized_path)
        except OSError as exc:
            logging.error("Task %s: Failed to move normalized Hyperframes source into place: %s", task_id, exc)
            return None
        return normalized_path

    overlay_coverage_percent = max(0, min(100, int(overlay_coverage_percent or 0)))
    configured_render_timeout_seconds = (
        HYPERFRAMES_VERTICAL_RENDER_TIMEOUT_SECONDS
        if layout == "vertical_reels"
        else HYPERFRAMES_RENDER_TIMEOUT_SECONDS
    )
    render_timeout_seconds = min(
        configured_render_timeout_seconds,
        max(300, PROCESS_TASK_SOFT_LIMIT_SECONDS - 300),
    )
    step_timeout_seconds = min(
        HYPERFRAMES_STEP_TIMEOUT_SECONDS,
        max(120, PROCESS_TASK_SOFT_LIMIT_SECONDS - 600),
    )
    render_input_video = normalize_video_for_hyperframes(input_video)
    if not render_input_video:
        return None
    expected_render_duration = probe_duration_seconds(render_input_video)

    if (
        layout == "vertical_reels"
        and HYPERFRAMES_VERTICAL_MAX_FULL_RENDER_SECONDS > 0
        and expected_render_duration
        and expected_render_duration > HYPERFRAMES_VERTICAL_MAX_FULL_RENDER_SECONDS
    ):
        logging.error(
            "Task %s: refusing vertical Hyperframes full render for %.1fs video; limit is %ss. "
            "Use a shorter source or horizontal/simple render path.",
            task_id,
            expected_render_duration,
            HYPERFRAMES_VERTICAL_MAX_FULL_RENDER_SECONDS,
        )
        return None

    def is_usable_hyperframes_output(path: str) -> bool:
        if not os.path.exists(path):
            return False
        try:
            file_size = os.path.getsize(path)
        except OSError:
            return False
        if file_size < 128 * 1024:
            logging.warning("Task %s: Hyperframes output is too small: %s bytes", task_id, file_size)
            return False

        actual_duration = probe_duration_seconds(path)
        if actual_duration is None:
            return False

        if expected_render_duration and expected_render_duration > 1:
            min_duration = max(1.0, expected_render_duration * 0.90)
            if actual_duration < min_duration:
                logging.warning(
                    "Task %s: Hyperframes output duration is too short: %.3fs < %.3fs expected minimum",
                    task_id,
                    actual_duration,
                    min_duration,
                )
                return False

        logging.info(
            "Task %s: Hyperframes output validated: path=%s size=%s duration=%.3fs expected=%.3fs",
            task_id,
            path,
            file_size,
            actual_duration,
            expected_render_duration or 0,
        )
        return True
    
    # 1. Run AI Scene Planner
    cmd_plan = [
        "python3", montage_script,
        "--video", render_input_video,
        "--index", scene_plan_index,
        "--out-plan", out_plan,
        "--out-semantic-blocks", out_semantic_blocks,
        "--out-transcript", out_transcript,
        "--overlay-coverage-percent", str(overlay_coverage_percent),
        "--deepgram-intelligence"
    ]
    if layout == "horizontal_youtube":
        cmd_plan.extend([
            "--plan-target", "hyperframes",
            "--max-scenes", os.getenv("HYPERFRAMES_YOUTUBE_MAX_SCENES", "12"),
            "--block-min-sentences", os.getenv("HYPERFRAMES_YOUTUBE_BLOCK_MIN_SENTENCES", "4"),
            "--block-max-sentences", os.getenv("HYPERFRAMES_YOUTUBE_BLOCK_MAX_SENTENCES", "8"),
            "--llm-plan-attempts", os.getenv("HYPERFRAMES_SCENE_PLAN_MAX_ATTEMPTS", "4"),
        ])
    elif layout == "horizontal_simple":
        cmd_plan.extend(["--plan-target", "remotion"])
    clean_script_context = re.sub(r"\s+", " ", (script or "")).strip()
    if clean_script_context:
        os.makedirs(os.path.dirname(script_context_path), exist_ok=True)
        with open(script_context_path, "w", encoding="utf-8") as fp:
            fp.write(clean_script_context)
        cmd_plan.extend(["--script-text-file", script_context_path])
    if transcript_json_path and os.path.exists(transcript_json_path):
        cmd_plan.extend(["--reuse-transcript", transcript_json_path])
    logging.info(f"Task {task_id}: Running scene planner: {' '.join(cmd_plan)}")
    try:
        res = subprocess.run(cmd_plan, capture_output=True, text=True, timeout=step_timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        logging.error(
            "Task %s: Scene planner timed out after %ss. STDOUT: %s\nSTDERR: %s",
            task_id,
            step_timeout_seconds,
            (exc.stdout or "")[-4000:],
            (exc.stderr or "")[-4000:],
        )
        return None
    if res.returncode != 0:
        logging.error(f"Task {task_id}: Scene planner failed. STDOUT: {res.stdout}\nSTDERR: {res.stderr}")
        return None
        
    out_words_generated = out_plan.replace("scene-plan_", "scene-word-cues_")
    if os.path.exists(out_words_generated):
        if out_words_generated != out_words:
            os.rename(out_words_generated, out_words)
    else:
        out_words_generated = os.path.join(os.path.dirname(out_plan), "scene-word-cues.generated.json")
        if os.path.exists(out_words_generated):
            os.rename(out_words_generated, out_words)

    if not os.path.exists(out_words):
        try:
            with open(out_plan, "r", encoding="utf-8") as fp:
                scenes = json.load(fp)
            scene_count = len(scenes) if isinstance(scenes, list) else 0
        except Exception:
            scene_count = 0
        fallback_cues = [[] for _ in range(scene_count)]
        with open(out_words, "w", encoding="utf-8") as fp:
            json.dump(fallback_cues, fp, ensure_ascii=False, indent=2)
        logging.warning(
            f"Task {task_id}: Scene word cues were missing after planner run. "
            f"Created fallback cues file: {out_words} (scenes={scene_count})"
        )

    hyperframes_input_dir = os.path.join(hyperframes_dir, "assets", "input")
    os.makedirs(hyperframes_input_dir, exist_ok=True)
    shutil.copy2(out_plan, os.path.join(hyperframes_input_dir, "scene-plan.generated.json"))
    shutil.copy2(out_words, os.path.join(hyperframes_input_dir, "scene-word-cues.generated.json"))
    if os.path.exists(out_semantic_blocks):
        shutil.copy2(out_semantic_blocks, os.path.join(hyperframes_input_dir, "semantic-blocks.generated.json"))
    if os.path.exists(out_transcript):
        shutil.copy2(out_transcript, os.path.join(hyperframes_input_dir, "transcript.deepgram.json"))
    else:
        logging.warning("Task %s: Deepgram transcript file is missing; word captions may be unavailable.", task_id)

    def build_hf_env() -> dict:
        env = os.environ.copy()
        browser_path = (
            env.get("HYPERFRAMES_BROWSER_PATH")
            or env.get("PRODUCER_HEADLESS_SHELL_PATH")
            or env.get("PUPPETEER_EXECUTABLE_PATH")
            or env.get("CHROME_BIN")
            or "/usr/bin/chromium-headless-shell"
        )
        if browser_path and os.path.exists(browser_path):
            # HyperFrames checks its cached browser before system Chrome unless
            # this is set. In containers, the cached binary can miss shared libs.
            env["HYPERFRAMES_BROWSER_PATH"] = browser_path
            env["PRODUCER_HEADLESS_SHELL_PATH"] = browser_path
        env["HYPERFRAMES_OVERLAY_COVERAGE_PERCENT"] = str(overlay_coverage_percent)
        env["PRODUCER_ENABLE_STREAMING_ENCODE"] = env.get("PRODUCER_ENABLE_STREAMING_ENCODE", "false")
        env["PRODUCER_ENABLE_CHUNKED_ENCODE"] = env.get("PRODUCER_ENABLE_CHUNKED_ENCODE", "true")
        env["PRODUCER_CHUNK_SIZE_FRAMES"] = env.get("PRODUCER_CHUNK_SIZE_FRAMES", "180")
        env["PRODUCER_FORCE_SCREENSHOT"] = env.get("PRODUCER_FORCE_SCREENSHOT", "true")
        env["PRODUCER_BROWSER_GPU_MODE"] = env.get("PRODUCER_BROWSER_GPU_MODE", "software")
        env["FFMPEG_ENCODE_TIMEOUT_MS"] = env.get("FFMPEG_ENCODE_TIMEOUT_MS", "7200000")
        env["FFMPEG_PROCESS_TIMEOUT_MS"] = env.get("FFMPEG_PROCESS_TIMEOUT_MS", "7200000")
        env["HYPERFRAMES_YOUTUBE_KIE_MAX_IMAGES"] = env.get("HYPERFRAMES_YOUTUBE_KIE_MAX_IMAGES", "12")
        env["HYPERFRAMES_YOUTUBE_REQUIRE_ALL_IMAGES"] = env.get("HYPERFRAMES_YOUTUBE_REQUIRE_ALL_IMAGES", "true")
        env["KIE_IMAGE_MAX_ATTEMPTS"] = env.get("KIE_IMAGE_MAX_ATTEMPTS", "3")
        env["KIE_JOB_TIMEOUT_MS"] = env.get("KIE_JOB_TIMEOUT_MS", str(20 * 60 * 1000))
        env["HYPERFRAMES_YOUTUBE_CAPTIONS"] = env.get("HYPERFRAMES_YOUTUBE_CAPTIONS", "false")
        env["HYPERFRAMES_YOUTUBE_CHAPTER_RIBBON"] = env.get("HYPERFRAMES_YOUTUBE_CHAPTER_RIBBON", "false")
        env["HYPERFRAMES_YOUTUBE_COMPOSITE_SOURCE_VIDEO"] = env.get(
            "HYPERFRAMES_YOUTUBE_COMPOSITE_SOURCE_VIDEO",
            "true",
        )
        env["HYPERFRAMES_YOUTUBE_FPS"] = env.get("HYPERFRAMES_YOUTUBE_FPS", "24")
        env["HYPERFRAMES_RENDER_QUALITY"] = env.get("HYPERFRAMES_RENDER_QUALITY", "high")
        env["HYPERFRAMES_RENDER_CRF"] = env.get("HYPERFRAMES_RENDER_CRF", "18")
        return env

    if layout in {"horizontal_simple", "horizontal_youtube"}:
        if layout == "horizontal_youtube":
            generated_dir = os.path.join(hyperframes_dir, "assets", "generated")
            os.makedirs(generated_dir, exist_ok=True)
            for file_name in os.listdir(generated_dir):
                if file_name.startswith("youtube-scene-") and file_name.lower().endswith(".png"):
                    try:
                        os.remove(os.path.join(generated_dir, file_name))
                    except OSError as exc:
                        logging.warning(
                            "Task %s: failed to remove stale YouTube KIE image %s: %s",
                            task_id,
                            file_name,
                            exc,
                        )

        def run_horizontal_step(label: str, cmd: list[str]) -> bool:
            logging.info("Task %s: %s: %s", task_id, label, " ".join(cmd))
            try:
                result = subprocess.run(
                    cmd,
                    cwd=hyperframes_dir,
                    capture_output=True,
                    text=True,
                    env=build_hf_env(),
                    timeout=step_timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                logging.error(
                    "Task %s: %s timed out after %ss. STDOUT: %s\nSTDERR: %s",
                    task_id,
                    label,
                    step_timeout_seconds,
                    (exc.stdout or "")[-4000:],
                    (exc.stderr or "")[-4000:],
                )
                return False
            if result.stdout:
                logging.info("Task %s: %s stdout: %s", task_id, label, result.stdout[-4000:])
            if result.stderr:
                logging.info("Task %s: %s stderr: %s", task_id, label, result.stderr[-4000:])
            if result.returncode != 0:
                logging.error(
                    "Task %s: %s failed. STDOUT: %s\nSTDERR: %s",
                    task_id,
                    label,
                    result.stdout,
                    result.stderr,
                )
                return False
            return True

        if layout == "horizontal_youtube":
            if (os.getenv("KIE_API_KEY") or "").strip():
                prompts_ready = run_horizontal_step(
                    "Hyperframes YouTube prompt generation",
                    ["npm", "run", "generate:youtube-prompts"],
                )
                if prompts_ready:
                    images_ready = run_horizontal_step(
                        "Hyperframes YouTube image generation",
                        ["npm", "run", "generate:images"],
                    )
                    if not images_ready:
                        logging.error(
                            "Task %s: KIE image generation failed; refusing to render horizontal "
                            "YouTube video with missing visual inserts.",
                            task_id,
                        )
                        return None
                else:
                    logging.error(
                        "Task %s: YouTube KIE prompt generation failed; refusing to render horizontal "
                        "YouTube video with missing visual inserts.",
                        task_id,
                    )
                    return None
            else:
                logging.error(
                    "Task %s: KIE_API_KEY is not configured; refusing to render horizontal "
                    "YouTube video with missing visual inserts.",
                    task_id,
                )
                return None

        final_output = os.path.join(
            out_dir,
            f"hyperframes_youtube_{task_id}.mp4" if layout == "horizontal_youtube" else f"hyperframes_horizontal_{task_id}.mp4",
        )
        if is_usable_hyperframes_output(final_output):
            logging.info("Task %s: reusing existing Hyperframes %s output: %s", task_id, layout, final_output)
            save_hyperframes_heartbeat("reused_existing_output", progress_percent=100, status="ready")
            return final_output
        cmd = [
            "npm", "run", "render:auto", "--",
            "--layout", layout,
            "--video", render_input_video,
            "--scene-plan", out_plan,
            "--word-cues", out_words,
            "--out", final_output,
        ]
        progress_re = re.compile(r"(\d{1,3})%\s*([^\r\n]*)")

        def run_hyperframes_horizontal_render_with_watchdog() -> tuple[int | None, str]:
            output_tail = ""
            started_at = time.monotonic()
            last_log_at = started_at
            best_percent = 0
            stage = "starting"

            logging.info(
                "Task %s: Hyperframes %s render with watchdog: %s (timeout=%ss)",
                task_id,
                layout,
                " ".join(cmd),
                render_timeout_seconds,
            )
            save_hyperframes_heartbeat("starting", progress_percent=0)
            process = subprocess.Popen(
                cmd,
                cwd=hyperframes_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=build_hf_env(),
                bufsize=0,
            )
            selector = selectors.DefaultSelector()
            if process.stdout:
                selector.register(process.stdout, selectors.EVENT_READ)

            try:
                while True:
                    now = time.monotonic()
                    return_code = process.poll()
                    events = selector.select(timeout=1.0)

                    for key, _ in events:
                        try:
                            chunk_bytes = os.read(key.fileobj.fileno(), 8192)
                        except OSError:
                            chunk_bytes = b""
                        if not chunk_bytes:
                            continue
                        chunk = chunk_bytes.decode("utf-8", errors="replace")
                        output_tail = (output_tail + chunk)[-16000:]
                        for match in progress_re.finditer(chunk.replace("\r", "\n")):
                            percent = int(match.group(1))
                            if 0 <= percent <= 100 and percent >= best_percent:
                                best_percent = percent
                                next_stage = re.sub(r"\s+", " ", match.group(2)).strip()
                                if next_stage:
                                    stage = next_stage[:160]

                    if return_code is not None:
                        if process.stdout:
                            try:
                                remaining = process.stdout.read() or b""
                                output_tail = (output_tail + remaining.decode("utf-8", errors="replace"))[-16000:]
                            except Exception:
                                pass
                        return return_code, output_tail

                    runtime = now - started_at
                    if now - last_log_at >= 60:
                        logging.info(
                            "Task %s: Hyperframes %s still rendering: progress=%s%% stage=%s runtime=%ss",
                            task_id,
                            layout,
                            best_percent,
                            stage,
                            int(runtime),
                        )
                        save_hyperframes_heartbeat(stage, progress_percent=best_percent)
                        last_log_at = now

                    if runtime > render_timeout_seconds:
                        process.kill()
                        process.wait(timeout=30)
                        logging.error(
                            "Task %s: Hyperframes %s render exceeded timeout %ss. "
                            "Last progress=%s%% stage=%s. Output tail: %s",
                            task_id,
                            layout,
                            render_timeout_seconds,
                            best_percent,
                            stage,
                            output_tail[-4000:],
                        )
                        return None, output_tail
            except SoftTimeLimitExceeded:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=30)
                logging.exception(
                    "Task %s: soft time limit while Hyperframes %s render was running. "
                    "Last progress=%s%% stage=%s. Output tail: %s",
                    task_id,
                    layout,
                    best_percent,
                    stage,
                    output_tail[-4000:],
                )
                raise
            finally:
                selector.close()
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=30)

        render_returncode, render_output_tail = run_hyperframes_horizontal_render_with_watchdog()
        if render_output_tail:
            logging.info("Task %s: Hyperframes %s output tail: %s", task_id, layout, render_output_tail[-4000:])
        if render_returncode is None:
            if is_usable_hyperframes_output(final_output):
                logging.warning(
                    "Task %s: Hyperframes %s render watchdog stopped, but output MP4 is valid. Accepting: %s",
                    task_id,
                    layout,
                    final_output,
                )
                save_hyperframes_heartbeat("completed_after_watchdog_stop", progress_percent=100, status="ready")
                return final_output
            return None
        if render_returncode != 0:
            logging.error(
                "Task %s: Hyperframes %s render failed with exit code %s. Output tail: %s",
                task_id,
                layout,
                render_returncode,
                render_output_tail,
            )
            return None
        if is_usable_hyperframes_output(final_output):
            save_hyperframes_heartbeat("completed", progress_percent=100, status="ready")
            return final_output
        logging.error("Task %s: Hyperframes %s render produced no usable output.", task_id, layout)
        return None

    def run_hf_step(label: str, cmd: list[str]) -> bool:
        logging.info("Task %s: %s: %s", task_id, label, " ".join(cmd))
        try:
            save_hyperframes_heartbeat(f"{label} started", progress_percent=0)
            result = subprocess.run(
                cmd,
                cwd=hyperframes_dir,
                capture_output=True,
                text=True,
                env=build_hf_env(),
                timeout=step_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            logging.error(
                "Task %s: %s timed out after %ss. STDOUT: %s\nSTDERR: %s",
                task_id,
                label,
                step_timeout_seconds,
                (exc.stdout or "")[-4000:],
                (exc.stderr or "")[-4000:],
            )
            return False
        if result.returncode != 0:
            logging.error(
                "Task %s: %s failed. STDOUT: %s\nSTDERR: %s",
                task_id,
                label,
                result.stdout,
                result.stderr,
            )
            return False
        if result.stdout:
            logging.info("Task %s: %s stdout: %s", task_id, label, result.stdout[-4000:])
        if result.stderr:
            logging.info("Task %s: %s stderr: %s", task_id, label, result.stderr[-4000:])
        return True

    # 2. Prepare the vertical HeyGen source and sync duration/FPS.
    if not run_hf_step("Hyperframes prepare", ["npm", "run", "prepare:heygen", "--", "--video", render_input_video]):
        return None

    # 3. Apply scene text to cards and let the timeline director place cutaways.
    if not run_hf_step("Hyperframes apply scene plan", ["npm", "run", "apply:scene-plan"]):
        return None
    if not run_hf_step("Hyperframes timeline director", ["npm", "run", "direct:timeline"]):
        return None
    if not run_hf_step("Hyperframes prompt generation", ["npm", "run", "generate:prompts"]):
        return None

    if (os.getenv("KIE_API_KEY") or "").strip():
        if not run_hf_step("Hyperframes image generation", ["npm", "run", "generate:images"]):
            return None
    else:
        logging.warning("Task %s: KIE_API_KEY is not configured; Hyperframes will render fallback HTML visuals.", task_id)

    # 4. Run Hyperframes render.
    final_output = os.path.join(out_dir, f"hyperframes_{task_id}.mp4")
    retry_output = os.path.join(out_dir, f"hyperframes_{task_id}_retry.mp4")

    def render_failure_needs_stable_retry(result) -> bool:
        combined = f"{result.stdout or ''}\n{result.stderr or ''}".lower()
        retry_markers = (
            "epipe",
            "browsergpumode auto → software",
            "browsergpumode auto -> software",
            "webgl unavailable",
            "beginframe unavailable",
            "falling back to screenshot mode",
            "chrome compositor starvation",
            "streaming encode failed",
            "ffmpeg exited with code 255",
        )
        return any(marker in combined for marker in retry_markers)

    def build_stable_render_env() -> dict:
        env = build_hf_env()
        # Streaming encode pipes screenshots directly into ffmpeg. In slow
        # server-side screenshot mode ffmpeg can close stdin near the end,
        # which surfaces as Node write EPIPE. Disk-frame encode is slower but
        # avoids that fragile pipe and works inside containers without Docker.
        return env

    def run_hyperframes_render(
        label: str,
        output_path: str,
        extra_args: list[str] | None = None,
        *,
        stable: bool = True,
    ):
        render_quality = (
            os.getenv("HYPERFRAMES_AVATAR_RENDER_QUALITY")
            or os.getenv("HYPERFRAMES_RENDER_QUALITY")
            or "high"
        ).strip().lower()
        if render_quality not in {"draft", "standard", "high"}:
            logging.warning(
                "Task %s: invalid Hyperframes avatar render quality %r; using high.",
                task_id,
                render_quality,
            )
            render_quality = "high"
        try:
            render_workers = max(1, int((os.getenv("HYPERFRAMES_RENDER_WORKERS") or "1").strip() or "1"))
        except ValueError:
            logging.warning(
                "Task %s: invalid HYPERFRAMES_RENDER_WORKERS=%r; using 1.",
                task_id,
                os.getenv("HYPERFRAMES_RENDER_WORKERS"),
            )
            render_workers = 1
        cmd = [
            "npm", "run", "render", "--",
            "--output", output_path,
            "--quality", render_quality,
            "--workers", str(render_workers),
            *(extra_args or []),
        ]
        logging.info("Task %s: %s: %s", task_id, label, " ".join(cmd))
        try:
            result = subprocess.run(
                cmd,
                cwd=hyperframes_dir,
                capture_output=True,
                text=True,
                env=build_stable_render_env() if stable else None,
                timeout=render_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            logging.error(
                "Task %s: %s timed out after %ss. STDOUT: %s\nSTDERR: %s",
                task_id,
                label,
                render_timeout_seconds,
                (exc.stdout or "")[-4000:],
                (exc.stderr or "")[-4000:],
            )
            timeout_result = subprocess.CompletedProcess(
                args=cmd,
                returncode=124,
                stdout=exc.stdout or "",
                stderr=exc.stderr or f"Timed out after {render_timeout_seconds}s",
            )
            save_hyperframes_heartbeat("timeout", progress_percent=0, status="failed")
            return cmd, timeout_result
        if result.stdout:
            logging.info("Task %s: %s stdout: %s", task_id, label, result.stdout[-4000:])
        if result.stderr:
            logging.info("Task %s: %s stderr: %s", task_id, label, result.stderr[-4000:])
        save_hyperframes_heartbeat(
            "completed" if result.returncode == 0 else f"failed_exit_{result.returncode}",
            progress_percent=100 if result.returncode == 0 else 0,
            status="ready" if result.returncode == 0 else "failed",
        )
        return cmd, result

    cmd_render, render_result = run_hyperframes_render("Hyperframes render", final_output)
    if render_result.returncode != 0:
        logging.error(
            "Task %s: Hyperframes render failed. STDOUT: %s\nSTDERR: %s",
            task_id,
            render_result.stdout,
            render_result.stderr,
        )
        if is_usable_hyperframes_output(final_output):
            logging.warning(
                "Task %s: Hyperframes render command failed with code %s, but output MP4 is valid. "
                "Accepting completed render.",
                task_id,
                render_result.returncode,
            )
            return final_output
        if render_failure_needs_stable_retry(render_result):
            logging.warning(
                "Task %s: Hyperframes render hit a browser/streaming failure. "
                "Retrying with stable disk-frame renderer and one worker.",
                task_id,
            )
            _, retry_result = run_hyperframes_render("Hyperframes render fallback", retry_output)
            if retry_result.returncode == 0 and is_usable_hyperframes_output(retry_output):
                return retry_output
            if is_usable_hyperframes_output(retry_output):
                logging.warning(
                    "Task %s: Stable render command failed with code %s, but output MP4 is valid. "
                    "Accepting completed render.",
                    task_id,
                    retry_result.returncode,
                )
                return retry_output
            logging.error(
                "Task %s: Hyperframes stable fallback failed. STDOUT: %s\nSTDERR: %s",
                task_id,
                retry_result.stdout,
                retry_result.stderr,
            )
        return None

    if is_usable_hyperframes_output(final_output):
        return final_output
    if render_failure_needs_stable_retry(render_result):
        logging.warning(
            "Task %s: Hyperframes render exited successfully but output was not usable after "
            "a browser/streaming warning. Retrying with stable disk-frame renderer.",
            task_id,
        )
        _, retry_result = run_hyperframes_render("Hyperframes render fallback", retry_output)
        if is_usable_hyperframes_output(retry_output):
            return retry_output
        logging.error(
            "Task %s: Hyperframes stable fallback produced no usable output. STDOUT: %s\nSTDERR: %s",
            task_id,
            retry_result.stdout,
            retry_result.stderr,
        )
    return None


@celery_app.task(name="process_content_task", bind=True, max_retries=3)
def process_content_task(self, task_id: int):
    task_started_monotonic = time.monotonic()
    db = SessionLocal()
    task = db.query(models.VideoTask).get(task_id)
    if not task:
        db.close()
        return
    if task.vizard_project_id and task.status in {"pending", "processing"}:
        child_count = db.query(models.VideoTask).filter(
            models.VideoTask.id != task.id,
            models.VideoTask.user_id == task.user_id,
            models.VideoTask.vizard_project_id == task.vizard_project_id,
            models.VideoTask.status == "completed",
            models.VideoTask.output_path.isnot(None),
        ).count()
        if child_count > 0:
            logging.warning(
                "Task %s: skipping duplicate Vizard parent processing because %s child output(s) already exist",
                task_id,
                child_count,
            )
            current_meta = dict(task.script_meta or {})
            duplicate_meta = dict(current_meta.get("duplicate_processing_guard") or {})
            duplicate_meta.update(
                {
                    "skipped_at": datetime.datetime.utcnow().isoformat(),
                    "reason": "vizard_parent_has_child_outputs",
                    "child_output_count": child_count,
                }
            )
            current_meta["duplicate_processing_guard"] = duplicate_meta
            task.script_meta = current_meta
            task.status = "completed"
            db.commit()
            db.close()
            return
    if task.status == "completed" and (task.output_path or "").strip():
        logging.info("Task %s is already completed with output_path=%s; skipping duplicate processing.", task_id, task.output_path)
        existing_meta = dict(task.script_meta or {})
        if (
            task.type in AVATAR_TASK_TYPES
            and task.type not in INSTAGRAM_POST_FIVE_SECOND_TASK_TYPES
            and existing_meta.get("yandex_disk_upload_status") in {"pending", "queued", "retrying", "failed"}
            and yandex_disk.is_configured
        ):
            upload_paths = _collect_yandex_disk_upload_paths(task)
            if upload_paths:
                celery_app.send_task("upload_yandex_disk_task", args=[task.id, upload_paths])
        db.close()
        return
    
    user = db.query(models.User).get(task.user_id)
    task.status = "processing"
    db.commit()
    update_task_status_message(db, task, stage="Обработка началась", detail="Подготавливаю видео к обработке.")
    input_videos: List[str] = []
    input_video_titles: List[str | None] = []
    input_video_contexts: List[str | None] = []
    avatar_clean_audio_path: str | None = None

    def _remaining_task_budget_seconds() -> float:
        return max(0.0, PROCESS_TASK_SOFT_LIMIT_SECONDS - (time.monotonic() - task_started_monotonic))

    def _probe_video_file_meta(path: str, *, min_size_bytes: int = 128 * 1024, min_duration_seconds: float = 0.5) -> dict:
        meta = {
            "path": path,
            "exists": bool(path and os.path.isfile(path)),
            "size": None,
            "duration": None,
            "min_size_bytes": min_size_bytes,
            "min_duration_seconds": min_duration_seconds,
            "valid": False,
        }
        if not meta["exists"]:
            return meta
        try:
            size = os.path.getsize(path)
            probe = processor._probe_media(path)
            duration = float(probe.get("format", {}).get("duration") or 0.0)
            meta.update(
                {
                    "size": size,
                    "duration": round(duration, 3),
                    "valid": size >= min_size_bytes and duration > min_duration_seconds,
                }
            )
        except Exception as exc:
            meta["error"] = str(exc)
        return meta

    def _get_reusable_avatar_render_path(renderer: str) -> str | None:
        render_meta = dict((task.script_meta or {}).get("avatar_render") or {})
        if render_meta.get("renderer") != renderer or render_meta.get("status") != "ready":
            return None
        candidate = str(render_meta.get("output_path") or "").strip()
        file_meta = _probe_video_file_meta(candidate)
        if file_meta.get("valid"):
            logging.info("Task %s: reusing ready %s render checkpoint: %s", task_id, renderer, candidate)
            return candidate
        return None

    def _save_avatar_render_checkpoint(renderer: str, output_path: str) -> None:
        file_meta = _probe_video_file_meta(output_path)
        current_meta = dict(task.script_meta or {})
        current_meta["avatar_render"] = {
            "status": "ready" if file_meta.get("valid") else "invalid",
            "renderer": renderer,
            "output_path": output_path,
            "file": file_meta,
            "updated_at": datetime.datetime.utcnow().isoformat() + "Z",
        }
        task.script_meta = current_meta
        db.commit()

    def _replace_video_audio_with_elevenlabs(
        video_path: str,
        audio_path: str | None,
        *,
        stage: str,
    ) -> tuple[str, dict]:
        meta = {
            "status": "skipped",
            "stage": stage,
            "video_path": video_path,
            "audio_path": audio_path,
            "reason": None,
            "output_path": None,
        }
        if (os.getenv("AVATAR_REMUX_ELEVENLABS_AUDIO", "true") or "").strip().lower() in {"0", "false", "no", "off"}:
            meta["reason"] = "disabled_by_env"
            return video_path, meta
        if not video_path or not os.path.exists(video_path):
            meta["reason"] = "video_missing"
            return video_path, meta
        if not audio_path or not os.path.exists(audio_path):
            meta["reason"] = "audio_missing"
            return video_path, meta

        base, ext = os.path.splitext(video_path)
        output_path = f"{base}_elevenlabs_audio{ext or '.mp4'}"
        temp_path = f"{output_path}.tmp.mp4"
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            video_path,
            "-i",
            audio_path,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "256k",
            "-shortest",
            "-movflags",
            "+faststart",
            temp_path,
        ]
        logging.info("Task %s: remuxing %s audio from ElevenLabs: %s", task_id, stage, " ".join(cmd))
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=min(900, max(120, PROCESS_TASK_SOFT_LIMIT_SECONDS - 600)),
            )
        except subprocess.TimeoutExpired as exc:
            meta["status"] = "failed"
            meta["reason"] = "timeout"
            meta["stderr"] = (exc.stderr or "")[-2000:]
            logging.error("Task %s: ElevenLabs audio remux timed out. STDERR: %s", task_id, meta["stderr"])
            return video_path, meta
        if result.returncode != 0:
            meta["status"] = "failed"
            meta["reason"] = f"ffmpeg_exit_{result.returncode}"
            meta["stderr"] = (result.stderr or "")[-3000:]
            logging.error("Task %s: ElevenLabs audio remux failed. STDERR: %s", task_id, meta["stderr"])
            return video_path, meta
        try:
            os.replace(temp_path, output_path)
        except OSError as exc:
            meta["status"] = "failed"
            meta["reason"] = f"replace_failed: {exc}"
            logging.error("Task %s: failed to move remuxed ElevenLabs audio output: %s", task_id, exc)
            return video_path, meta

        file_meta = _probe_video_file_meta(output_path)
        if not file_meta.get("valid"):
            meta["status"] = "failed"
            meta["reason"] = "output_invalid"
            meta["file"] = file_meta
            logging.error("Task %s: remuxed ElevenLabs audio output is invalid: %s", task_id, file_meta)
            return video_path, meta

        meta["status"] = "ready"
        meta["output_path"] = output_path
        meta["file"] = file_meta
        return output_path, meta

    def _replace_video_audio_stream_copy(
        video_path: str,
        audio_path: str | None,
        *,
        stage: str,
        audio_offset_seconds: float = 0.0,
    ) -> tuple[str, dict]:
        meta = {
            "status": "skipped",
            "stage": stage,
            "video_path": video_path,
            "audio_path": audio_path,
            "audio_offset_seconds": round(float(audio_offset_seconds or 0.0), 3),
            "copy_audio": True,
            "reason": None,
            "output_path": None,
        }
        if (os.getenv("AVATAR_REMUX_ORIGINAL_AUDIO", "true") or "").strip().lower() in {"0", "false", "no", "off"}:
            meta["reason"] = "disabled_by_env"
            return video_path, meta
        if not video_path or not os.path.exists(video_path):
            meta["reason"] = "video_missing"
            return video_path, meta
        if not audio_path or not os.path.exists(audio_path):
            meta["reason"] = "audio_missing"
            return video_path, meta

        safe_offset = max(0.0, float(audio_offset_seconds or 0.0))
        base, ext = os.path.splitext(video_path)
        output_path = f"{base}_original_audio{ext or '.mp4'}"
        temp_path = f"{output_path}.tmp.mp4"
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            video_path,
        ]
        if safe_offset > 0:
            cmd.extend(["-itsoffset", f"{safe_offset:.3f}"])
        cmd.extend([
            "-i",
            audio_path,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-shortest",
            "-avoid_negative_ts",
            "make_zero",
            "-movflags",
            "+faststart",
            temp_path,
        ])
        logging.info("Task %s: remuxing %s audio with stream copy: %s", task_id, stage, " ".join(cmd))
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=min(900, max(120, PROCESS_TASK_SOFT_LIMIT_SECONDS - 600)),
            )
        except subprocess.TimeoutExpired as exc:
            meta["status"] = "failed"
            meta["reason"] = "timeout"
            meta["stderr"] = (exc.stderr or "")[-2000:]
            logging.error("Task %s: original audio remux timed out. STDERR: %s", task_id, meta["stderr"])
            return video_path, meta
        if result.returncode != 0:
            meta["status"] = "failed"
            meta["reason"] = f"ffmpeg_exit_{result.returncode}"
            meta["stderr"] = (result.stderr or "")[-3000:]
            logging.error("Task %s: original audio remux failed. STDERR: %s", task_id, meta["stderr"])
            return video_path, meta
        try:
            os.replace(temp_path, output_path)
        except OSError as exc:
            meta["status"] = "failed"
            meta["reason"] = f"replace_failed: {exc}"
            logging.error("Task %s: failed to move original-audio remux output: %s", task_id, exc)
            return video_path, meta

        file_meta = _probe_video_file_meta(output_path)
        if not file_meta.get("valid"):
            meta["status"] = "failed"
            meta["reason"] = "output_invalid"
            meta["file"] = file_meta
            logging.error("Task %s: original-audio remux output is invalid: %s", task_id, file_meta)
            return video_path, meta

        meta["status"] = "ready"
        meta["output_path"] = output_path
        meta["file"] = file_meta
        return output_path, meta

    def _extract_denoised_audio_track(source_video_path: str, *, stage: str) -> tuple[str | None, dict]:
        output_dir = os.getenv("OUTPUT_DIR", "./output").strip()
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"ready_heygen_clean_audio_{task_id}_{stage}.m4a")
        meta = {
            "status": "skipped",
            "stage": stage,
            "source_video_path": source_video_path,
            "output_path": output_path,
            "reason": None,
        }
        if (os.getenv("AVATAR_READY_HEYGEN_DENOISE_AUDIO", "false") or "").strip().lower() in {"0", "false", "no", "off"}:
            meta["reason"] = "disabled_by_env"
            return None, meta
        if not source_video_path or not os.path.exists(source_video_path):
            meta["reason"] = "source_missing"
            return None, meta

        audio_filter = (os.getenv("AVATAR_READY_HEYGEN_AUDIO_FILTER", "").strip() or "highpass=f=80,lowpass=f=12000,afftdn=nf=-25")
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            source_video_path,
            "-vn",
            "-af",
            audio_filter,
            "-c:a",
            "aac",
            "-b:a",
            "256k",
            output_path,
        ]
        logging.info("Task %s: extracting denoised ready-HeyGen audio: %s", task_id, " ".join(cmd))
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=min(900, max(120, PROCESS_TASK_SOFT_LIMIT_SECONDS - 600)),
            )
        except subprocess.TimeoutExpired as exc:
            meta["status"] = "failed"
            meta["reason"] = "timeout"
            meta["stderr"] = (exc.stderr or "")[-2000:]
            logging.error("Task %s: ready-HeyGen audio denoise timed out. STDERR: %s", task_id, meta["stderr"])
            return None, meta
        if result.returncode != 0 or not os.path.isfile(output_path):
            meta["status"] = "failed"
            meta["reason"] = f"ffmpeg_exit_{result.returncode}"
            meta["stderr"] = (result.stderr or "")[-3000:]
            logging.error("Task %s: ready-HeyGen audio denoise failed. STDERR: %s", task_id, meta["stderr"])
            return None, meta
        meta["status"] = "ready"
        meta["filter"] = audio_filter
        meta["duration_seconds"] = get_audio_duration_seconds(output_path)
        return output_path, meta

    def _render_avatar_with_graphics(
        input_video: str,
        script_text: str,
        *,
        transcript_json_path: str | None = None,
    ) -> tuple[str | None, str]:
        is_short_avatar = task.type in SHORT_AVATAR_TASK_TYPES
        use_hyperframes = is_short_avatar or (
            task.type in AVATAR_HORIZONTAL_TASK_TYPES
            and AVATAR_HORIZONTAL_RENDERER not in {"remotion", "remotion_only", "remotion-only"}
        )
        renderer_name = "Hyperframes" if use_hyperframes else "Remotion"
        render_output = _get_reusable_avatar_render_path(renderer_name)
        overlay_coverage = int(getattr(user, "reels_broll_coverage_percent", 50) or 50)

        if not render_output and use_hyperframes:
            render_output = _run_hyperframes_pipeline(
                task_id,
                input_video,
                script_text,
                transcript_json_path=transcript_json_path,
                overlay_coverage_percent=overlay_coverage,
                layout="vertical_reels" if is_short_avatar else "horizontal_youtube",
            )

        if (
            not render_output
            and not is_short_avatar
            and AVATAR_HORIZONTAL_RENDERER in AVATAR_HORIZONTAL_REMOTION_FALLBACK_RENDERERS
        ):
            logging.warning(
                "Task %s: horizontal Hyperframes render failed or disabled; falling back to Remotion.",
                task_id,
            )
            renderer_name = "Remotion"
            render_output = _get_reusable_avatar_render_path(renderer_name)
            if not render_output:
                render_output = _run_remotion_pipeline(
                    task_id,
                    input_video,
                    script_text,
                    transcript_json_path=transcript_json_path,
                    overlay_coverage_percent=overlay_coverage,
                )

        return render_output, renderer_name

    def _parse_iso_timestamp(value: str | None) -> float | None:
        raw = (value or "").strip()
        if not raw:
            return None
        try:
            parsed = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=datetime.timezone.utc)
            return parsed.timestamp()
        except Exception:
            return None

    def _apply_avatar_insert_montage(base_video_path: str) -> tuple[str, dict]:
        start_percent = int(getattr(user, "avatar_insert_start_percent", 50) or 50)
        end_percent = int(getattr(user, "avatar_insert_end_percent", 95) or 95)
        clips_count = int(getattr(user, "avatar_insert_clips_count", 0) or 0)
        insert_rows = (
            db.query(models.AvatarInsertClip)
            .filter(models.AvatarInsertClip.user_id == user.id)
            .order_by(models.AvatarInsertClip.created_at.desc(), models.AvatarInsertClip.id.desc())
            .all()
        )
        insert_paths = []
        for row in insert_rows:
            resolved = _resolve_media_file_path(row.file_path, media_kind="avatar-inserts")
            if resolved:
                insert_paths.append(resolved)

        if clips_count <= 0 or not insert_paths:
            return base_video_path, {
                "status": "skipped",
                "reason": "no_clips_or_count_zero",
                "requested_count": clips_count,
                "available_clips": len(insert_paths),
            }

        update_task_status_message(
            db,
            task,
            stage="Монтаж",
            detail="Встраиваю дополнительные видео-вставки в финальный ролик.",
        )
        montage_output = os.path.join(
            os.getenv("OUTPUT_DIR", "./output").strip(),
            f"avatar_inserted_{task_id}.mp4",
        )
        existing_output_meta = _probe_video_file_meta(montage_output)
        if existing_output_meta.get("valid"):
            logging.info("Task %s: reusing existing avatar insert montage output: %s", task_id, montage_output)
            return montage_output, {
                "status": "applied",
                "reason": "reused_existing_output",
                "output_path": montage_output,
                "file": existing_output_meta,
                "requested_count": clips_count,
                "available_clips": len(insert_paths),
            }

        remaining_budget = _remaining_task_budget_seconds()
        if remaining_budget < AVATAR_INSERT_MONTAGE_MIN_REMAINING_SECONDS:
            logging.warning(
                "Task %s: skipping avatar insert montage because remaining Celery budget is %.1fs "
                "(minimum required %.1fs)",
                task_id,
                remaining_budget,
                AVATAR_INSERT_MONTAGE_MIN_REMAINING_SECONDS,
            )
            return base_video_path, {
                "status": "skipped",
                "reason": "insufficient_task_time_budget",
                "remaining_budget_seconds": round(remaining_budget, 3),
                "minimum_required_seconds": AVATAR_INSERT_MONTAGE_MIN_REMAINING_SECONDS,
                "requested_count": clips_count,
                "available_clips": len(insert_paths),
            }

        current_meta = dict(task.script_meta or {})
        current_meta["avatar_insert_montage"] = {
            "status": "in_progress",
            "input_path": base_video_path,
            "output_path": montage_output,
            "timeout_seconds": AVATAR_INSERT_MONTAGE_TIMEOUT_SECONDS,
            "remaining_budget_seconds": round(remaining_budget, 3),
            "updated_at": datetime.datetime.utcnow().isoformat() + "Z",
        }
        task.script_meta = current_meta
        db.commit()

        max_insert_seconds = float(os.getenv("AVATAR_INSERT_CLIP_MAX_SECONDS", "0"))
        try:
            inserted_path, insert_meta = apply_transparent_avatar_overlays(
                input_path=base_video_path,
                overlay_paths=insert_paths,
                start_percent=start_percent,
                end_percent=end_percent,
                clips_count=clips_count,
                output_path=montage_output,
                x_percent=int(getattr(user, "avatar_overlay_x_percent", 70) or 70),
                y_percent=int(getattr(user, "avatar_overlay_y_percent", 100) or 100),
                size_percent=int(getattr(user, "avatar_overlay_size_percent", 61) or 61),
                opacity_percent=int(getattr(user, "avatar_overlay_opacity_percent", 100) or 100),
                seed=task_id,
                max_insert_seconds=max_insert_seconds,
                timeout_seconds=AVATAR_INSERT_MONTAGE_TIMEOUT_SECONDS,
            )
        except SoftTimeLimitExceeded:
            logging.exception("Task %s: soft time limit while applying avatar insert montage; keeping base video.", task_id)
            return base_video_path, {
                "status": "skipped",
                "reason": "soft_time_limit_before_insert_finished",
                "output_path": montage_output,
                "requested_count": clips_count,
                "available_clips": len(insert_paths),
            }
        if inserted_path:
            if base_video_path != inserted_path and os.path.isfile(base_video_path):
                try:
                    os.remove(base_video_path)
                except OSError:
                    logging.warning("Failed to remove intermediate avatar file after inserts: %s", base_video_path)
            return inserted_path, insert_meta or {"status": "applied"}
        failed_meta = insert_meta or {"status": "failed", "reason": "unknown"}
        failed_meta.setdefault("output_path", montage_output)
        return base_video_path, failed_meta

    def _detect_avatar_video_type(video_path: str) -> tuple[str | None, dict]:
        meta: dict = {
            "path": video_path,
            "width": None,
            "height": None,
            "detected_orientation": None,
            "detected_task_type": None,
        }
        try:
            probe = processor._probe_media(video_path)
            video_stream = processor._get_first_stream(probe, "video")
            width = int(video_stream.get("width") or 0) if video_stream else 0
            height = int(video_stream.get("height") or 0) if video_stream else 0
        except Exception as probe_error:
            logging.warning("Task %s: failed to probe HeyGen video orientation: %s", task_id, probe_error)
            meta["error"] = str(probe_error)
            return None, meta

        meta["width"] = width or None
        meta["height"] = height or None
        if width <= 0 or height <= 0:
            meta["error"] = "missing_dimensions"
            return None, meta

        is_vertical = height > width
        detected_task_type = "avatar_vertical" if is_vertical else "avatar_horizontal"
        meta["detected_orientation"] = "vertical" if is_vertical else "horizontal"
        meta["detected_task_type"] = detected_task_type
        return detected_task_type, meta

    def _clamp_script_to_char_range(
        *,
        script: str,
        style_profile: str | None,
        min_chars: int,
        max_chars: int,
        max_attempts: int = 3,
    ) -> str:
        current = (script or "").strip()
        for _ in range(max_attempts):
            char_count = count_script_chars(current)
            if min_chars <= char_count <= max_chars:
                return current
            adjusted = llm.adjust_script_length_chars(
                script=current,
                style_profile=style_profile,
                min_chars=min_chars,
                max_chars=max_chars,
            )
            if not adjusted:
                return current
            adjusted = adjusted.strip()
            if adjusted == current:
                return current
            current = adjusted
        return current

    def _create_short_avatar_broll(base_video_path: str, script_text: str, source_video_path: str | None) -> tuple[str, dict]:
        coverage_percent = max(0, min(100, int(getattr(user, "reels_broll_coverage_percent", 50) or 0)))
        start_percent = 0
        end_percent = 100
        broll_dir = (
            getattr(user, "reels_broll_yandex_dir", None)
            or os.getenv("YANDEX_DISK_BROLL_DIR")
            or "disk:/Видео для REELS"
        ).strip()
        try:
            source_probe = processor._probe_media(base_video_path)
            source_duration = float(source_probe.get("format", {}).get("duration") or 0.0)
        except Exception:
            source_duration = 0.0
        target_broll_seconds = max(0.0, source_duration * (coverage_percent / 100.0))
        min_broll_seconds = float(os.getenv("REELS_BROLL_CLIP_MIN_SECONDS", "2.5"))
        max_broll_seconds = float(os.getenv("REELS_BROLL_CLIP_MAX_SECONDS", "4"))
        clips_count = int(math.ceil(target_broll_seconds / max_broll_seconds)) if target_broll_seconds > 0 else 0
        meta = {
            "status": "skipped",
            "reason": None,
            "input_video_path": base_video_path,
            "source_reel_path": source_video_path,
            "script_char_count": count_script_chars(script_text),
            "yandex_dir": broll_dir,
            "coverage_percent": coverage_percent,
            "source_duration_sec": round(source_duration, 3) if source_duration else None,
            "target_broll_seconds": round(target_broll_seconds, 3),
            "clip_duration_range_sec": [min_broll_seconds, max_broll_seconds],
            "requested_count": clips_count,
            "window_percent": [start_percent, end_percent],
            "selected_files": [],
        }
        if task.type not in SHORT_AVATAR_TASK_TYPES:
            meta["status"] = "skipped"
            meta["reason"] = "not_short_avatar"
            return base_video_path, meta
        if coverage_percent <= 0 or clips_count <= 0:
            meta["reason"] = "coverage_percent_is_zero"
            return base_video_path, meta
        if source_duration <= 0:
            meta["reason"] = "source_duration_unavailable"
            return base_video_path, meta
        if not yandex_disk.is_configured:
            meta["reason"] = "yandex_disk_not_configured"
            return base_video_path, meta

        update_task_status_message(
            db,
            task,
            stage="B-roll",
            detail="Выбираю случайные b-roll ролики с Яндекс.Диска.",
        )
        try:
            remote_files, yandex_debug = yandex_disk.list_video_files(broll_dir, include_debug=True)
        except Exception as list_error:
            logging.warning("Task %s: failed to list Yandex.Disk b-roll folder: %s", task_id, list_error)
            meta["status"] = "failed"
            meta["reason"] = "yandex_list_failed"
            meta["error"] = str(list_error)
            return base_video_path, meta
        meta["yandex_items_count"] = int((yandex_debug or {}).get("items_count") or 0)
        meta["yandex_seen_items"] = (yandex_debug or {}).get("items") or []
        logging.info(
            "Task %s: Yandex.Disk b-roll scan dir=%s items=%s video_files=%s names=%s",
            task_id,
            broll_dir,
            meta["yandex_items_count"],
            len(remote_files),
            [item.get("name") for item in remote_files[:20]],
        )

        if not remote_files:
            meta["reason"] = "no_video_files_in_yandex_dir"
            logging.warning(
                "Task %s: no b-roll video files found in %s. Seen items: %s",
                task_id,
                broll_dir,
                meta["yandex_seen_items"][:20],
            )
            return base_video_path, meta

        rnd = random.Random(task_id)
        rnd.shuffle(remote_files)
        selected_files = remote_files[: min(clips_count, len(remote_files))]
        meta["selected_files"] = selected_files

        local_dir = os.path.join(os.getenv("OUTPUT_DIR", "./output").strip(), f"reels_broll_{task_id}")
        os.makedirs(local_dir, exist_ok=True)
        local_paths: list[str] = []
        for index, item in enumerate(selected_files, start=1):
            remote_path = str(item.get("path") or "").strip()
            name = os.path.basename(str(item.get("name") or remote_path or f"broll_{index}.mp4"))
            _, ext = os.path.splitext(name)
            safe_ext = ext if ext.lower() in {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".mpeg"} else ".mp4"
            local_path = os.path.join(local_dir, f"broll_{index}{safe_ext}")
            try:
                yandex_disk.download_file(remote_path, local_path)
            except Exception as download_error:
                logging.warning(
                    "Task %s: failed to download b-roll file %s: %s",
                    task_id,
                    remote_path,
                    download_error,
                )
                continue
            local_paths.append(local_path)
            logging.info("Task %s: downloaded b-roll file %s to %s", task_id, remote_path, local_path)

        if not local_paths:
            meta["status"] = "failed"
            meta["reason"] = "all_downloads_failed"
            return base_video_path, meta

        update_task_status_message(
            db,
            task,
            stage="B-roll",
            detail=f"Встраиваю b-roll: {len(local_paths)} видео.",
        )
        broll_output = os.path.join(
            os.getenv("OUTPUT_DIR", "./output").strip(),
            f"reels_broll_inserted_{task_id}.mp4",
        )
        broll_path, broll_apply_meta = processor.apply_avatar_insert_clips(
            input_path=base_video_path,
            insert_paths=local_paths,
            start_percent=start_percent,
            end_percent=end_percent,
            clips_count=clips_count,
            output_path=broll_output,
            seed=task_id,
            min_insert_seconds=min_broll_seconds,
            max_insert_seconds=max_broll_seconds,
            target_total_insert_seconds=target_broll_seconds,
            preserve_source_audio=True,
        )
        meta = {**meta, **(broll_apply_meta or {})}
        meta["downloaded_paths"] = local_paths
        if broll_path:
            meta["status"] = "applied"
            return broll_path, meta
        meta["status"] = "failed" if (broll_apply_meta or {}).get("reason") else "skipped"
        meta["reason"] = (broll_apply_meta or {}).get("reason") or "broll_apply_failed"
        return base_video_path, meta

    def _generate_avatar_thumbnail(
        factual_outline: str,
        script_text: str,
        detail_text: str = "Генерирую обложку YouTube по сценарию и референсам.",
    ) -> tuple[str | None, dict]:
        is_short_avatar = task.type in SHORT_AVATAR_TASK_TYPES
        target_aspect_ratio = "9:16" if is_short_avatar else "16:9"
        active_face_path = user.vertical_thumbnail_face_path if is_short_avatar else user.thumbnail_face_path
        output_dir = os.getenv("OUTPUT_DIR", "./output").strip()
        thumbnail_output_path = os.path.join(output_dir, f"thumbnail_{task_id}.png")
        existing_meta = dict(task.script_meta or {})
        existing_thumbnail_meta = dict(existing_meta.get("thumbnail") or {})
        thumbnail_generation_meta = dict(existing_meta.get("thumbnail_generation") or {})
        existing_prompt = (
            existing_meta.get("thumbnail_prompt")
            or existing_thumbnail_meta.get("prompt")
            or ""
        )
        if existing_thumbnail_meta.get("telegram_sent") or existing_thumbnail_meta.get("telegram_sent_at"):
            logging.info("Task %s: thumbnail was already sent to Telegram; skipping duplicate generation.", task_id)
            return (str(existing_prompt or "").strip() or None), {
                **existing_thumbnail_meta,
                "status": existing_thumbnail_meta.get("status") or "generated",
                "reason": "telegram_already_sent",
                "telegram_sent": True,
                "aspect_ratio": target_aspect_ratio,
            }

        existing_output_path = str(existing_thumbnail_meta.get("output_path") or "").strip()
        reusable_thumbnail_path = existing_output_path if os.path.isfile(existing_output_path) else ""
        if not reusable_thumbnail_path and os.path.isfile(thumbnail_output_path):
            reusable_thumbnail_path = thumbnail_output_path
        if reusable_thumbnail_path:
            existing_face_path = str(existing_thumbnail_meta.get("face_path") or "").strip()
            existing_aspect_ratio = str(existing_thumbnail_meta.get("aspect_ratio") or "").strip()
            face_matches = (existing_face_path or None) == (active_face_path or None)
            aspect_matches = not existing_aspect_ratio or existing_aspect_ratio == target_aspect_ratio
            if not face_matches or not aspect_matches:
                logging.info(
                    "Task %s: ignoring reusable thumbnail because target changed "
                    "(existing_face=%s active_face=%s existing_aspect=%s target_aspect=%s)",
                    task_id,
                    bool(existing_face_path),
                    bool(active_face_path),
                    existing_aspect_ratio or "-",
                    target_aspect_ratio,
                )
            else:
                logging.info("Task %s: reusing existing thumbnail output: %s", task_id, reusable_thumbnail_path)
                thumbnail_meta = {
                    **existing_thumbnail_meta,
                    "status": existing_thumbnail_meta.get("status") or "generated",
                    "reason": "reused_existing_thumbnail",
                    "output_path": reusable_thumbnail_path,
                    "face_path": active_face_path,
                    "aspect_ratio": target_aspect_ratio,
                    "telegram_sent": bool(existing_thumbnail_meta.get("telegram_sent") or existing_thumbnail_meta.get("telegram_sent_at")),
                }
                return (str(existing_prompt or "").strip() or None), thumbnail_meta
        generation_status = str(thumbnail_generation_meta.get("status") or "").strip().lower()
        generation_started_ts = _parse_iso_timestamp(str(thumbnail_generation_meta.get("started_at") or ""))
        generation_age = (time.time() - generation_started_ts) if generation_started_ts else None
        if generation_status == "in_progress" and generation_age is not None and generation_age < THUMBNAIL_GENERATION_LOCK_TTL_SECONDS:
            logging.warning(
                "Task %s: thumbnail generation is already in progress (age=%.1fs); skipping duplicate KIE generation.",
                task_id,
                generation_age,
            )
            return (str(existing_prompt or "").strip() or None), {
                **existing_thumbnail_meta,
                "status": "skipped",
                "reason": "thumbnail_generation_already_in_progress",
                "lock_age_seconds": round(generation_age, 3),
                "lock_ttl_seconds": THUMBNAIL_GENERATION_LOCK_TTL_SECONDS,
                "output_path": existing_output_path or None,
                "aspect_ratio": target_aspect_ratio,
            }

        face_paths = [active_face_path] if active_face_path else []
        thumbnail_prompt = None
        thumbnail_meta: dict = {
            "status": "skipped",
            "reason": "thumbnail_prompt_empty",
            "output_path": None,
            "used_reference_count": 0,
            "face_path": active_face_path,
            "face_reference_count": len(face_paths),
            "aspect_ratio": target_aspect_ratio,
        }
        try:
            if is_short_avatar:
                thumbnail_prompt = llm.generate_vertical_thumbnail_prompt(
                    (task.source_title or "Главный момент").strip(),
                    context_text=(script_text or factual_outline or ""),
                )
            else:
                thumbnail_prompt = llm.generate_youtube_thumbnail_prompt(
                    factual_outline or "",
                    script_text or "",
                    video_title=(task.source_title or ""),
                )
        except Exception as e:
            logging.exception("Task %s: failed to generate thumbnail prompt: %s", task_id, e)
            thumbnail_meta = {
                **thumbnail_meta,
                "status": "failed",
                "reason": "thumbnail_prompt_generation_failed",
            }
            return None, thumbnail_meta

        if thumbnail_prompt:
            if THUMBNAIL_PROMPT_REVIEW_ENABLED and getattr(task, "telegram_chat_id", None):
                meta = dict(task.script_meta or {})
                review = dict(meta.get("thumbnail_prompt_review") or {})
                review_status = (review.get("status") or "").strip().lower()
                reviewed_prompt = (review.get("approved_prompt") or review.get("prompt") or "").strip()
                if review_status == "approved" and reviewed_prompt:
                    thumbnail_prompt = reviewed_prompt
                elif review_status == "rejected":
                    thumbnail_meta = {
                        **thumbnail_meta,
                        "status": "skipped",
                        "reason": "thumbnail_prompt_rejected",
                    }
                    return thumbnail_prompt, thumbnail_meta
                elif not review.get("prompt"):
                    review = {
                        "status": "pending",
                        "prompt": thumbnail_prompt,
                        "created_at": datetime.datetime.utcnow().isoformat(),
                    }
                    meta["thumbnail_prompt_review"] = review
                    task.script_meta = meta
                    db.commit()
                    send_thumbnail_prompt_review_to_telegram(task, thumbnail_prompt)

                if review_status != "approved":
                    update_task_status_message(
                        db,
                        task,
                        stage="Обложка",
                        detail="Жду подтверждение prompt обложки в Telegram.",
                    )
                    deadline = time.monotonic() + THUMBNAIL_PROMPT_REVIEW_TIMEOUT_SECONDS
                    while time.monotonic() < deadline:
                        db.refresh(task)
                        meta = dict(task.script_meta or {})
                        review = dict(meta.get("thumbnail_prompt_review") or {})
                        status = (review.get("status") or "").strip().lower()
                        if status == "approved":
                            thumbnail_prompt = (review.get("approved_prompt") or review.get("prompt") or thumbnail_prompt).strip()
                            break
                        if status == "rejected":
                            thumbnail_meta = {
                                **thumbnail_meta,
                                "status": "skipped",
                                "reason": "thumbnail_prompt_rejected",
                            }
                            return thumbnail_prompt, thumbnail_meta
                        time.sleep(THUMBNAIL_PROMPT_REVIEW_POLL_SECONDS)
                    else:
                        thumbnail_meta = {
                            **thumbnail_meta,
                            "status": "skipped",
                            "reason": "thumbnail_prompt_review_timeout",
                        }
                        return thumbnail_prompt, thumbnail_meta

            references = (
                db.query(models.ThumbnailReference)
                .filter(
                    models.ThumbnailReference.user_id == user.id,
                    models.ThumbnailReference.kind.in_(["vertical", "both"] if is_short_avatar else ["horizontal", "both"]),
                )
                .order_by(models.ThumbnailReference.created_at.desc(), models.ThumbnailReference.id.desc())
                .all()
            )
            reference_paths = [item.file_path for item in references if item and item.file_path]
            update_task_status_message(
                db,
                task,
                stage="Обложка",
                detail=detail_text,
            )
            current_meta = dict(task.script_meta or {})
            current_meta["thumbnail_prompt"] = thumbnail_prompt
            current_meta["thumbnail_generation"] = {
                "status": "in_progress",
                "started_at": datetime.datetime.utcnow().isoformat() + "Z",
                "output_path": thumbnail_output_path,
                "aspect_ratio": "9:16" if is_short_avatar else "16:9",
            }
            task.script_meta = current_meta
            db.commit()

            generated_thumbnail = thumbnail_generator.generate_thumbnail(
                prompt=thumbnail_prompt,
                face_path=active_face_path,
                face_paths=face_paths,
                reference_paths=reference_paths,
                output_path=thumbnail_output_path,
                aspect_ratio="9:16" if is_short_avatar else None,
                max_style_references=(
                    int(os.getenv("VERTICAL_THUMBNAIL_MAX_STYLE_REFERENCES", "4"))
                    if is_short_avatar
                    else None
                ),
            )
            if generated_thumbnail:
                thumbnail_meta = {
                    "status": "generated",
                    "reason": None,
                    "output_path": generated_thumbnail,
                    "used_reference_count": len(reference_paths[:5]),
                    "face_path": active_face_path,
                    "face_reference_count": len(face_paths),
                    "aspect_ratio": "9:16" if is_short_avatar else "16:9",
                    "prompt": thumbnail_prompt,
                    "telegram_sent": False,
                }
                current_meta = dict(task.script_meta or {})
                current_meta["thumbnail_prompt"] = thumbnail_prompt
                current_meta["thumbnail"] = thumbnail_meta
                current_meta["thumbnail_generation"] = {
                    **dict(current_meta.get("thumbnail_generation") or {}),
                    "status": "generated",
                    "completed_at": datetime.datetime.utcnow().isoformat() + "Z",
                    "output_path": generated_thumbnail,
                }
                task.script_meta = current_meta
                db.commit()
                update_task_status_message(
                    db,
                    task,
                    stage="Telegram",
                    detail="Отправляю готовую обложку в Telegram.",
                )
                db.refresh(task)
                latest_meta = dict(task.script_meta or {})
                latest_thumbnail_meta = dict(latest_meta.get("thumbnail") or {})
                if latest_thumbnail_meta.get("telegram_sent") or latest_thumbnail_meta.get("telegram_sent_at"):
                    thumbnail_meta = {
                        **thumbnail_meta,
                        "telegram_sent": True,
                        "telegram_sent_at": latest_thumbnail_meta.get("telegram_sent_at"),
                        "reason": "telegram_already_sent",
                    }
                elif not latest_thumbnail_meta.get("telegram_send_in_progress"):
                    latest_thumbnail_meta = {
                        **latest_thumbnail_meta,
                        "telegram_send_in_progress": True,
                        "telegram_send_started_at": datetime.datetime.utcnow().isoformat() + "Z",
                    }
                    latest_meta["thumbnail"] = latest_thumbnail_meta
                    task.script_meta = latest_meta
                    db.commit()
                    send_thumbnail_to_telegram(task, generated_thumbnail)
                    thumbnail_meta["telegram_sent"] = True
                    thumbnail_meta["telegram_sent_at"] = datetime.datetime.utcnow().isoformat() + "Z"
                    thumbnail_meta["telegram_send_in_progress"] = False
                    current_meta = dict(task.script_meta or {})
                    current_meta["thumbnail"] = thumbnail_meta
                    task.script_meta = current_meta
                    db.commit()
                else:
                    thumbnail_meta = {
                        **thumbnail_meta,
                        "telegram_sent": False,
                        "reason": "telegram_send_already_in_progress",
                    }
            else:
                kie_error_detail = thumbnail_generator.get_last_error_message_ru()
                thumbnail_meta = {
                    "status": "failed",
                    "reason": "generator_failed_or_unconfigured",
                    "reason_detail": kie_error_detail,
                    "output_path": None,
                    "used_reference_count": len(reference_paths[:5]),
                    "face_path": active_face_path,
                    "face_reference_count": len(face_paths),
                    "aspect_ratio": "9:16" if is_short_avatar else "16:9",
                }
                current_meta = dict(task.script_meta or {})
                current_meta["thumbnail_generation"] = {
                    **dict(current_meta.get("thumbnail_generation") or {}),
                    "status": "failed",
                    "completed_at": datetime.datetime.utcnow().isoformat() + "Z",
                    "reason": "generator_failed_or_unconfigured",
                    "reason_detail": kie_error_detail,
                }
                task.script_meta = current_meta
                db.commit()
                update_task_status_message(
                    db,
                    task,
                    stage="Обложка",
                    detail=f"Не удалось сгенерировать картинку через KIE. {kie_error_detail}",
                )
        return thumbnail_prompt, thumbnail_meta

    def _apply_vertical_thumbnail_intro(
        *,
        source_video_path: str,
        clip_title: str | None,
        context_text: str | None = None,
        clip_index: int,
    ) -> tuple[str, dict]:
        clean_title = (clip_title or "").strip()
        clean_context = re.sub(r"\s+", " ", (context_text or "")).strip()
        meta: dict = {
            "status": "skipped",
            "reason": None,
            "clip_title": clean_title,
            "context_char_count": len(clean_context),
            "prompt": None,
            "image_path": None,
            "intro_duration_seconds": VERTICAL_THUMBNAIL_INTRO_SECONDS,
            "used_reference_count": 0,
            "face_path": user.vertical_thumbnail_face_path,
        }
        if task.type in AVATAR_TASK_TYPES:
            meta["reason"] = "avatar_not_applicable"
            return source_video_path, meta
        if not clean_title and not clean_context:
            meta["reason"] = "clip_title_and_context_empty"
            return source_video_path, meta

        references = (
            db.query(models.ThumbnailReference)
            .filter(models.ThumbnailReference.user_id == user.id, models.ThumbnailReference.kind.in_(["vertical", "both"]))
            .order_by(models.ThumbnailReference.created_at.desc(), models.ThumbnailReference.id.desc())
            .all()
        )
        face_paths = [user.vertical_thumbnail_face_path] if user.vertical_thumbnail_face_path else []
        meta["face_reference_count"] = len(face_paths)
        reference_paths = []
        for item in references:
            resolved = _resolve_media_file_path(item.file_path, media_kind="thumbnails")
            if resolved:
                reference_paths.append(resolved)
            elif item.file_path:
                reference_paths.append(item.file_path)
        if not reference_paths:
            meta["reason"] = "no_vertical_references"
            return source_video_path, meta

        update_task_status_message(
            db,
            task,
            stage="Обложка 9:16",
            detail=f"Генерирую вертикальную обложку для клипа {clip_index}.",
        )
        try:
            prompt = llm.generate_vertical_thumbnail_prompt(clean_title, context_text=clean_context)
        except Exception as prompt_error:
            logging.exception("Task %s: vertical thumbnail prompt failed: %s", task_id, prompt_error)
            meta["status"] = "failed"
            meta["reason"] = "prompt_generation_failed"
            return source_video_path, meta

        if not prompt:
            meta["reason"] = "prompt_empty"
            return source_video_path, meta

        output_dir = os.getenv("OUTPUT_DIR", "./output").strip()
        os.makedirs(output_dir, exist_ok=True)
        image_output_path = os.path.join(output_dir, f"vertical_thumbnail_{task_id}_{clip_index}.png")
        generated_image = thumbnail_generator.generate_thumbnail(
            prompt=prompt,
            face_path=user.vertical_thumbnail_face_path,
            face_paths=face_paths,
            reference_paths=reference_paths,
            output_path=image_output_path,
            aspect_ratio="9:16",
            max_style_references=int(os.getenv("VERTICAL_THUMBNAIL_MAX_STYLE_REFERENCES", "4")),
        )
        meta["prompt"] = prompt
        meta["used_reference_count"] = len(reference_paths[: int(os.getenv("VERTICAL_THUMBNAIL_MAX_STYLE_REFERENCES", "4"))])
        if not generated_image:
            kie_error_detail = thumbnail_generator.get_last_error_message_ru()
            meta["status"] = "failed"
            meta["reason"] = "generator_failed_or_unconfigured"
            meta["reason_detail"] = kie_error_detail
            update_task_status_message(
                db,
                task,
                stage="Обложка 9:16",
                detail=f"Не удалось сгенерировать картинку через KIE. {kie_error_detail}",
            )
            return source_video_path, meta

        intro_output_path = os.path.join(output_dir, f"vertical_intro_{task_id}_{clip_index}.mp4")
        intro_video, intro_meta = processor.prepend_image_intro(
            input_path=source_video_path,
            image_path=generated_image,
            output_path=intro_output_path,
            duration_seconds=VERTICAL_THUMBNAIL_INTRO_SECONDS,
        )
        meta = {
            **meta,
            **(intro_meta or {}),
            "prompt": prompt,
            "image_path": generated_image,
            "used_reference_count": meta["used_reference_count"],
        }
        if intro_video:
            return intro_video, meta
        return source_video_path, meta

    def _apply_short_avatar_vertical_cover(
        source_video_path: str,
        script_text: str,
        cover_image_path: str | None = None,
        cover_prompt: str | None = None,
    ) -> tuple[str, dict]:
        existing_cover_path = (cover_image_path or "").strip()
        existing_prompt = (cover_prompt or "").strip()
        meta: dict = {
            "status": "skipped",
            "reason": None,
            "prompt": existing_prompt or None,
            "image_path": existing_cover_path or None,
            "intro_duration_seconds": REELS_VERTICAL_COVER_SECONDS,
            "used_reference_count": 0,
            "face_path": user.vertical_thumbnail_face_path,
            "source": "generated_thumbnail" if existing_cover_path else "generated_vertical_cover",
        }
        if task.type not in SHORT_AVATAR_TASK_TYPES:
            meta["reason"] = "not_short_avatar"
            return source_video_path, meta

        references = (
            db.query(models.ThumbnailReference)
            .filter(models.ThumbnailReference.user_id == user.id, models.ThumbnailReference.kind.in_(["vertical", "both"]))
            .order_by(models.ThumbnailReference.created_at.desc(), models.ThumbnailReference.id.desc())
            .all()
        )
        face_paths = [user.vertical_thumbnail_face_path] if user.vertical_thumbnail_face_path else []
        meta["face_reference_count"] = len(face_paths)
        reference_paths = []
        for item in references:
            resolved = _resolve_media_file_path(item.file_path, media_kind="thumbnails")
            if resolved:
                reference_paths.append(resolved)
            elif item.file_path:
                reference_paths.append(item.file_path)

        output_dir = os.getenv("OUTPUT_DIR", "./output").strip()
        os.makedirs(output_dir, exist_ok=True)
        max_refs = int(os.getenv("VERTICAL_THUMBNAIL_MAX_STYLE_REFERENCES", "4"))
        generated_image = existing_cover_path if existing_cover_path and os.path.isfile(existing_cover_path) else None
        meta["source"] = "generated_thumbnail" if generated_image else "generated_vertical_cover"
        prompt = existing_prompt or None
        if generated_image:
            update_task_status_message(
                db,
                task,
                stage="Обложка 9:16",
                detail="Использую уже сгенерированную обложку для короткого Avatar.",
            )
        else:
            update_task_status_message(
                db,
                task,
                stage="Обложка 9:16",
                detail="Генерирую вертикальную обложку для короткого Avatar.",
            )
            title = (task.source_title or "Short Avatar").strip()
            try:
                prompt = llm.generate_vertical_thumbnail_prompt(title, context_text=script_text)
            except Exception as prompt_error:
                logging.exception("Task %s: Reels vertical cover prompt failed: %s", task_id, prompt_error)
                meta["status"] = "failed"
                meta["reason"] = "prompt_generation_failed"
                return source_video_path, meta
            if not prompt:
                meta["reason"] = "prompt_empty"
                return source_video_path, meta

            image_output_path = os.path.join(output_dir, f"reels_vertical_cover_{task_id}.png")
            generated_image = thumbnail_generator.generate_thumbnail(
                prompt=prompt,
                face_path=user.vertical_thumbnail_face_path,
                face_paths=face_paths,
                reference_paths=reference_paths,
                output_path=image_output_path,
                aspect_ratio="9:16",
                max_style_references=max_refs,
            )
        meta["prompt"] = prompt
        meta["used_reference_count"] = len(reference_paths[:max_refs])
        if not generated_image:
            kie_error_detail = thumbnail_generator.get_last_error_message_ru()
            meta["status"] = "failed"
            meta["reason"] = "generator_failed_or_unconfigured"
            meta["reason_detail"] = kie_error_detail
            update_task_status_message(
                db,
                task,
                stage="Обложка 9:16",
                detail=f"Не удалось сгенерировать картинку через KIE. {kie_error_detail}",
            )
            return source_video_path, meta

        cover_output_path = os.path.join(output_dir, f"reels_vertical_cover_intro_{task_id}.mp4")
        cover_video, cover_meta = processor.prepend_image_intro(
            input_path=source_video_path,
            image_path=generated_image,
            output_path=cover_output_path,
            duration_seconds=REELS_VERTICAL_COVER_SECONDS,
        )
        meta = {
            **meta,
            **(cover_meta or {}),
            "prompt": prompt,
            "image_path": generated_image,
            "used_reference_count": meta["used_reference_count"],
        }
        if cover_video:
            return cover_video, meta
        return source_video_path, meta

    def _upload_to_yandex_disk_if_needed(rendered_items: List[dict]) -> List[dict]:
        if task.type not in AVATAR_TASK_TYPES:
            return []
        if not yandex_disk.is_configured:
            raise Exception("YANDEX_DISK_TOKEN is not configured for avatar upload")

        update_task_status_message(
            db,
            task,
            stage="Выгрузка",
            detail="Сохраняю видео и обложку в корень Яндекс.Диска (disk:/).",
        )
        target_root = (os.getenv("YANDEX_DISK_AVATAR_DIR") or "disk:/").strip()
        target_dir = target_root.rstrip("/") or "disk:/"
        ensured_dir = yandex_disk.ensure_directory(target_dir)

        thumbnail_path = ""
        description_txt_path = ""
        try:
            thumbnail_path = (
                ((task.script_meta or {}).get("thumbnail") or {}).get("output_path")
                or ""
            ).strip()
            description_txt_path = (
                ((task.script_meta or {}).get("youtube_description") or {}).get("txt_path")
                or ""
            ).strip()
        except Exception:
            thumbnail_path = ""
            description_txt_path = ""

        file_paths: List[str] = []
        for item in rendered_items:
            local_output = (item.get("output_path") or "").strip()
            if local_output and os.path.isfile(local_output):
                file_paths.append(local_output)
        if thumbnail_path and os.path.isfile(thumbnail_path):
            file_paths.append(thumbnail_path)
        if description_txt_path and os.path.isfile(description_txt_path):
            file_paths.append(description_txt_path)

        uploaded: List[dict] = []
        for local_path in file_paths:
            remote_path = f"{ensured_dir.rstrip('/')}/{os.path.basename(local_path)}"
            remote_saved_path = yandex_disk.upload_file(local_path=local_path, remote_path=remote_path, overwrite=True)
            public_url = yandex_disk.publish_and_get_public_url(remote_saved_path)
            uploaded.append(
                {
                    "local_output_path": local_path,
                    "remote_path": remote_saved_path,
                    "public_url": public_url,
                }
            )
        return uploaded

    def _clean_plate_title(value: str | None, *, fallback: str = "Главный тезис") -> str:
        title = re.sub(r"\s+", " ", (value or "")).strip().strip("\"'«»“”")
        title = re.sub(r"[#@]\S+", "", title).strip()
        if not re.search(r"[\wА-Яа-яЁё]", title, flags=re.UNICODE):
            title = ""
        if not title:
            title = fallback
        return title

    def _wrap_plate_title(value: str, *, max_chars: int = 22) -> list[str]:
        words = _clean_plate_title(value).split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if current and len(candidate) > max_chars:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        if len(lines) > 7:
            compact_lines: list[str] = []
            current = ""
            for word in words:
                candidate = f"{current} {word}".strip()
                if current and len(candidate) > 28:
                    compact_lines.append(current)
                    current = word
                else:
                    current = candidate
            if current:
                compact_lines.append(current)
            lines = compact_lines[:7]
        if not lines:
            lines = ["Главный тезис"]
        return lines

    def _render_five_second_post_video(
        *,
        image_path: str,
        title: str,
        output_path: str,
        audio_path: str | None = None,
        overlay_path: str | None = None,
        cta_text: str | None = None,
        duration_seconds: float = 5.0,
    ) -> tuple[str | None, dict]:
        output_dir = os.path.dirname(output_path) or "."
        os.makedirs(output_dir, exist_ok=True)
        plate_png_path = os.path.join(output_dir, f"instagram_post_5s_title_{task_id}.png")
        title_lines = _wrap_plate_title(title)
        try:
            from PIL import Image, ImageDraw, ImageFont

            plate = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
            draw = ImageDraw.Draw(plate)
            font_candidates = [
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                "/System/Library/Fonts/Helvetica.ttc",
            ]
            font_candidates.extend(glob.glob("/usr/share/fonts/truetype/**/*Sans*Bold*.ttf", recursive=True))
            selected_font_path = None
            for candidate_font_path in font_candidates:
                if os.path.isfile(candidate_font_path):
                    selected_font_path = candidate_font_path
                    break
            if not selected_font_path:
                raise RuntimeError("No TrueType font found for Instagram post 5s title plate")

            safe_x1 = 56
            safe_x2 = 900
            safe_center_x = int((safe_x1 + safe_x2) / 2)
            plate_x1 = safe_x1
            plate_x2 = safe_x2
            max_text_width = plate_x2 - plate_x1 - 72
            font = None
            font_size = 78
            line_gap = 84
            max_text_block_height = 610
            for candidate_size in range(78, 35, -2):
                candidate_font = ImageFont.truetype(selected_font_path, candidate_size)
                candidate_gap = max(int(candidate_size * 1.18), candidate_size + 8)
                too_wide = False
                for line in title_lines:
                    bbox = draw.textbbox((0, 0), line.upper(), font=candidate_font)
                    if (bbox[2] - bbox[0]) > max_text_width:
                        too_wide = True
                        break
                total_text_height = (len(title_lines) - 1) * candidate_gap + candidate_size
                if not too_wide and total_text_height <= max_text_block_height:
                    font = candidate_font
                    font_size = candidate_size
                    line_gap = candidate_gap
                    break
            if font is None:
                font_size = 34
                font = ImageFont.truetype(selected_font_path, font_size)
                line_gap = 42

            total_text_height = (len(title_lines) - 1) * line_gap + font_size
            plate_height = max(230, min(760, total_text_height + 118))
            plate_y2 = 1110 if plate_height <= 520 else 1160
            plate_y1 = int(plate_y2 - plate_height)
            draw.rounded_rectangle(
                (plate_x1, plate_y1, plate_x2, plate_y2),
                radius=46,
                fill=(255, 79, 87, 255),
            )
            center_y = (plate_y1 + plate_y2) / 2
            first_line_y = center_y - ((len(title_lines) - 1) * line_gap / 2)
            for index, line in enumerate(title_lines):
                text = line.upper()
                bbox = draw.textbbox((0, 0), text, font=font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
                x = int(safe_center_x - text_width / 2)
                y = int(first_line_y + index * line_gap - text_height / 2)
                draw.text((x, y), text, font=font, fill=(43, 47, 51, 255))

            clean_cta_text = "\n".join(
                line
                for line in (" ".join(raw_line.split()) for raw_line in (cta_text or "").replace("\r\n", "\n").split("\n"))
                if line
            ).strip()
            if clean_cta_text:
                raw_cta_lines = clean_cta_text[:220].split("\n")
                eyebrow_text = raw_cta_lines[0] if len(raw_cta_lines) > 1 else ""
                main_text = " ".join(raw_cta_lines[1:] if len(raw_cta_lines) > 1 else raw_cta_lines).strip()
                main_lines = _wrap_plate_title(main_text, max_chars=18)
                eyebrow_font = ImageFont.truetype(selected_font_path, 36)
                cta_font = None
                cta_font_size = 76
                cta_line_gap = 86
                cta_max_width = 760
                cta_max_height = 240
                for candidate_size in range(76, 35, -2):
                    candidate_font = ImageFont.truetype(selected_font_path, candidate_size)
                    candidate_gap = max(int(candidate_size * 1.16), candidate_size + 7)
                    too_wide = False
                    for line in main_lines:
                        bbox = draw.textbbox((0, 0), line.upper(), font=candidate_font)
                        if (bbox[2] - bbox[0]) > cta_max_width:
                            too_wide = True
                            break
                    eyebrow_height = 46 if eyebrow_text else 0
                    total_height = eyebrow_height + (len(main_lines) - 1) * candidate_gap + candidate_size
                    if not too_wide and total_height <= cta_max_height:
                        cta_font = candidate_font
                        cta_font_size = candidate_size
                        cta_line_gap = candidate_gap
                        break
                if cta_font is None:
                    cta_font_size = 28
                    cta_font = ImageFont.truetype(selected_font_path, cta_font_size)
                    cta_line_gap = 35

                eyebrow_height = 46 if eyebrow_text else 0
                cta_text_height = eyebrow_height + (len(main_lines) - 1) * cta_line_gap + cta_font_size
                cta_box_height = max(128, min(270, cta_text_height + 58))
                cta_y2 = min(1450, plate_y2 + 28 + cta_box_height)
                cta_y1 = int(cta_y2 - cta_box_height)
                draw.rounded_rectangle(
                    (safe_x1, cta_y1, safe_x2, cta_y2),
                    radius=34,
                    fill=(255, 255, 255, 242),
                )
                cta_center_y = (cta_y1 + cta_y2) / 2
                block_y = cta_center_y - cta_text_height / 2
                if eyebrow_text:
                    bbox = draw.textbbox((0, 0), eyebrow_text, font=eyebrow_font)
                    text_width = bbox[2] - bbox[0]
                    text_height = bbox[3] - bbox[1]
                    x = int(safe_center_x - text_width / 2)
                    y = int(block_y - text_height / 2 + 22)
                    draw.text((x, y), eyebrow_text, font=eyebrow_font, fill=(31, 41, 55, 255))
                    block_y += eyebrow_height
                for index, line in enumerate(main_lines):
                    text = line.upper()
                    bbox = draw.textbbox((0, 0), text, font=cta_font)
                    text_width = bbox[2] - bbox[0]
                    text_height = bbox[3] - bbox[1]
                    x = int(safe_center_x - text_width / 2)
                    y = int(block_y + index * cta_line_gap - text_height / 2 + cta_font_size / 2)
                    draw.text((x, y), text, font=cta_font, fill=(0, 0, 0, 255))
            plate.save(plate_png_path)
        except Exception as plate_error:
            logging.exception("Task %s: failed to render 5s title plate PNG: %s", task_id, plate_error)
            raise

        temp_path = f"{output_path}.tmp.mp4"
        use_audio_path = audio_path if audio_path and os.path.isfile(audio_path) else None
        use_overlay_path = overlay_path if overlay_path and os.path.isfile(overlay_path) else None
        cmd = [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-t",
            f"{duration_seconds:.3f}",
            "-i",
            image_path,
            "-loop",
            "1",
            "-t",
            f"{duration_seconds:.3f}",
            "-i",
            plate_png_path,
        ]
        if use_audio_path:
            cmd.extend(["-stream_loop", "-1", "-i", use_audio_path])
        else:
            cmd.extend([
                "-f",
                "lavfi",
                "-t",
                f"{duration_seconds:.3f}",
                "-i",
                "anullsrc=r=48000:cl=stereo",
            ])
        if use_overlay_path:
            cmd.extend([
                "-loop",
                "1",
                "-t",
                f"{duration_seconds:.3f}",
                "-i",
                use_overlay_path,
            ])
        filter_parts = [
            "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920[base]",
            "[1:v]format=rgba[plate]",
            "[base][plate]overlay=0:0[v_title]",
        ]
        video_label = "[v_title]"
        if use_overlay_path:
            filter_parts.extend(
                [
                    "[3:v]scale=1080:1920:force_original_aspect_ratio=decrease,setsar=1,format=rgba[extra_plate]",
                    "[v_title][extra_plate]overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/2:enable='gte(t,2)'[v]",
                ]
            )
            video_label = "[v]"
        cmd.extend([
            "-t",
            f"{duration_seconds:.3f}",
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            video_label,
            "-map",
            "2:a:0",
            "-r",
            "30",
            "-c:v",
            "libx264",
            "-preset",
            os.getenv("FFMPEG_X264_PRESET", "veryfast"),
            "-crf",
            os.getenv("FFMPEG_X264_CRF", "18"),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            "-movflags",
            "+faststart",
            temp_path,
        ])
        meta = {
            "status": "skipped",
            "image_path": image_path,
            "title": title,
            "cta_text": clean_cta_text or None,
            "audio_path": use_audio_path,
            "overlay_path": use_overlay_path,
            "overlay_start_seconds": 2.0 if use_overlay_path else None,
            "plate_png_path": plate_png_path,
            "output_path": output_path,
            "duration_seconds": duration_seconds,
            "reason": None,
        }
        logging.info("Task %s: rendering Instagram post 5s video: %s", task_id, " ".join(cmd))
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=min(900, max(120, PROCESS_TASK_SOFT_LIMIT_SECONDS - 600)),
            )
        except subprocess.TimeoutExpired as exc:
            meta["status"] = "failed"
            meta["reason"] = "timeout"
            meta["stderr"] = (exc.stderr or "")[-2000:]
            return None, meta
        if result.returncode != 0 or not os.path.isfile(temp_path):
            meta["status"] = "failed"
            meta["reason"] = f"ffmpeg_exit_{result.returncode}"
            meta["stderr"] = (result.stderr or "")[-3000:]
            return None, meta
        os.replace(temp_path, output_path)
        file_meta = _probe_video_file_meta(
            output_path,
            min_size_bytes=24 * 1024,
            min_duration_seconds=max(0.5, duration_seconds - 1.0),
        )
        if not file_meta.get("valid"):
            meta["status"] = "failed"
            meta["reason"] = "output_invalid"
            meta["file"] = file_meta
            logging.error("Task %s: Instagram post 5s output is invalid: %s", task_id, file_meta)
            return None, meta
        meta["status"] = "ready"
        meta["file"] = file_meta
        return output_path, meta

    def _extract_frame_at_second(video_path: str, output_path: str, *, second: float = 1.0) -> tuple[str | None, dict]:
        meta = {
            "status": "skipped",
            "video_path": video_path,
            "output_path": output_path,
            "second": second,
            "reason": None,
        }
        if not video_path or not os.path.isfile(video_path):
            meta["status"] = "failed"
            meta["reason"] = "video_missing"
            return None, meta
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            f"{max(0.0, second):.3f}",
            "-i",
            video_path,
            "-frames:v",
            "1",
            "-q:v",
            "2",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if result.returncode != 0 or not os.path.isfile(output_path):
            meta["status"] = "failed"
            meta["reason"] = f"ffmpeg_exit_{result.returncode}"
            meta["stderr"] = (result.stderr or "")[-2000:]
            return None, meta
        meta["status"] = "ready"
        return output_path, meta

    def _render_five_second_image_video(
        *,
        image_path: str,
        output_path: str,
        audio_path: str | None = None,
        duration_seconds: float = 5.0,
    ) -> tuple[str | None, dict]:
        meta = {
            "status": "skipped",
            "image_path": image_path,
            "audio_path": audio_path if audio_path and os.path.isfile(audio_path) else None,
            "output_path": output_path,
            "duration_seconds": duration_seconds,
            "reason": None,
        }
        if not image_path or not os.path.isfile(image_path):
            meta["status"] = "failed"
            meta["reason"] = "image_missing"
            return None, meta
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        temp_path = f"{output_path}.tmp.mp4"
        cmd = [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-t",
            f"{duration_seconds:.3f}",
            "-i",
            image_path,
        ]
        if meta["audio_path"]:
            cmd.extend(["-stream_loop", "-1", "-i", meta["audio_path"]])
        else:
            cmd.extend(["-f", "lavfi", "-t", f"{duration_seconds:.3f}", "-i", "anullsrc=r=48000:cl=stereo"])
        cmd.extend([
            "-t",
            f"{duration_seconds:.3f}",
            "-filter_complex",
            "[0:v:0]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[v]",
            "-map",
            "[v]",
            "-map",
            "1:a:0",
            "-r",
            "30",
            "-c:v",
            "libx264",
            "-preset",
            os.getenv("FFMPEG_X264_PRESET", "veryfast"),
            "-crf",
            os.getenv("FFMPEG_X264_CRF", "18"),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            "-movflags",
            "+faststart",
            temp_path,
        ])
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
        if result.returncode != 0 or not os.path.isfile(temp_path):
            meta["status"] = "failed"
            meta["reason"] = f"ffmpeg_exit_{result.returncode}"
            meta["stderr"] = (result.stderr or "")[-3000:]
            return None, meta
        os.replace(temp_path, output_path)
        file_meta = _probe_video_file_meta(
            output_path,
            min_size_bytes=24 * 1024,
            min_duration_seconds=max(0.5, duration_seconds - 1.0),
        )
        if not file_meta.get("valid"):
            meta["status"] = "failed"
            meta["reason"] = "output_invalid"
            meta["file"] = file_meta
            return None, meta
        meta["status"] = "ready"
        meta["file"] = file_meta
        return output_path, meta

    try:
        source_url_raw = (task.source_url or "").strip()
        if not source_url_raw:
            raise Exception("Source URL is empty")

        if task.type == "local_upload":
            local_input = _resolve_local_input_video_path(source_url_raw)
            if not local_input:
                raise Exception("Uploaded local video file was not found on disk")
            update_task_status_message(
                db,
                task,
                stage="Локальный файл",
                detail="Использую загруженное видео без внешних сервисов.",
            )
            input_videos.append(local_input)
            input_video_titles.append(task.source_title or os.path.basename(local_input))
            input_video_contexts.append(task.source_title or os.path.basename(local_input))
            source_url = source_url_raw
        else:
            source_url = _normalize_external_url(source_url_raw)
            if not source_url:
                raise Exception("Source URL is empty")

        if task.type == "vizard":
            update_task_status_message(db, task, stage="Vizard", detail="Отправляю видео в Vizard и жду клипы.")
            clips = _download_vizard_project_clips(db, task, source_url)
            input_videos.extend(path for path, _title in clips)
            input_video_titles.extend(title for _path, title in clips)
            input_video_contexts.extend(title for _path, title in clips)

        elif task.type in AVATAR_READY_HEYGEN_TASK_TYPES and _extract_heygen_video_id(source_url_raw):
            heygen_video_id = _extract_heygen_video_id(source_url_raw)
            if not heygen_video_id:
                raise Exception("Invalid HeyGen video_id for avatar task")

            update_task_status_message(
                db,
                task,
                stage="HeyGen",
                detail=f"Получаю уже готовое видео HeyGen по id={heygen_video_id}.",
            )
            logging.info("Task %s: avatar task using existing HeyGen video_id=%s", task_id, heygen_video_id)

            final_video_url = asyncio.run(heygen_client.poll_video_status(heygen_video_id))
            if not final_video_url:
                raise Exception(f"HeyGen video with id={heygen_video_id} is unavailable, failed, or timed out")

            update_task_status_message(db, task, stage="Монтаж", detail="Скачиваю готовое видео из HeyGen.")
            local_avatar_video = downloader.download_media(final_video_url, f"heygen_{task_id}")
            if not local_avatar_video:
                raise Exception("Failed to download existing HeyGen video")
            avatar_clean_audio_path = local_avatar_video
            existing_meta = dict(task.script_meta or {})
            existing_meta["ready_heygen_original_audio"] = {
                "status": "ready",
                "source_video_path": local_avatar_video,
                "mode": "stream_copy",
            }
            existing_meta.pop("ready_heygen_audio_cleanup", None)
            task.script_meta = existing_meta
            db.commit()

            detected_task_type, detection_meta = _detect_avatar_video_type(local_avatar_video)
            if detected_task_type and task.type != detected_task_type:
                previous_type = task.type
                task.type = detected_task_type
                existing_meta = dict(task.script_meta or {})
                existing_meta["heygen_ready_video"] = {
                    **detection_meta,
                    "previous_task_type": previous_type,
                    "source": "heygen_video_id",
                }
                task.script_meta = existing_meta
                db.commit()
                update_task_status_message(
                    db,
                    task,
                    stage="Формат",
                    detail=(
                        "Определил вертикальный HeyGen-ролик; продолжаю vertical pipeline."
                        if detected_task_type in SHORT_AVATAR_TASK_TYPES
                        else "Определил горизонтальный HeyGen-ролик; продолжаю horizontal pipeline."
                    ),
                )
            else:
                existing_meta = dict(task.script_meta or {})
                existing_meta["heygen_ready_video"] = {
                    **detection_meta,
                    "previous_task_type": task.type,
                    "source": "heygen_video_id",
                }
                task.script_meta = existing_meta
                db.commit()

            transcribed_text = ""
            inferred_outline = ""
            heygen_transcript_path = ""
            if not ENABLE_HEYGEN_READY_TRANSCRIBE:
                raise Exception("AVATAR_HEYGEN_READY_TRANSCRIBE must be enabled for HeyGen ID avatar tasks")
            if not deepgram_client.is_configured:
                raise Exception("DEEPGRAM_API_KEY is required for HeyGen ID avatar tasks")

            update_task_status_message(
                db,
                task,
                stage="Сценарий",
                detail="Транскрибирую готовое HeyGen-видео и беру тему перебивок из речи аватара.",
            )
            try:
                transcript_payload = deepgram_client.transcribe_media(local_avatar_video) or {}
                transcribed_text = (deepgram_client.extract_transcript_text(transcript_payload) or "").strip()
            except Exception as transcribe_error:
                logging.warning(
                    "Task %s: Deepgram transcription failed for existing HeyGen video: %s",
                    task_id,
                    transcribe_error,
                )
                transcript_payload = {}
                transcribed_text = ""
            if not transcribed_text:
                raise Exception("Failed to transcribe existing HeyGen video; refusing to use fallback avatar context")

            heygen_transcript_path = os.path.join(
                os.getenv("OUTPUT_DIR", "./output").strip(),
                f"heygen_transcript_{task_id}.json",
            )
            os.makedirs(os.path.dirname(heygen_transcript_path), exist_ok=True)
            try:
                import json

                with open(heygen_transcript_path, "w", encoding="utf-8") as fp:
                    json.dump(transcript_payload, fp, ensure_ascii=False, indent=2)
            except Exception as transcript_save_error:
                logging.warning(
                    "Task %s: failed to save HeyGen transcript JSON for reuse: %s",
                    task_id,
                    transcript_save_error,
                )
                heygen_transcript_path = ""

            try:
                inferred_outline = (llm.generate_factual_outline(transcribed_text) or "").strip()
            except Exception as outline_error:
                logging.warning(
                    "Task %s: factual outline generation from Deepgram transcript failed: %s",
                    task_id,
                    outline_error,
                )
                inferred_outline = ""
            task.script_text = transcribed_text
            if inferred_outline:
                task.factual_outline = inferred_outline
            existing_meta = dict(task.script_meta or {})
            existing_meta["heygen_ready_video"] = {
                **dict(existing_meta.get("heygen_ready_video") or {}),
                "transcript_source": "deepgram_avatar_video",
                "transcript_path": heygen_transcript_path or None,
                "transcript_char_count": len(transcribed_text),
            }
            task.script_meta = existing_meta
            db.commit()

            thumbnail_outline = (
                inferred_outline
                or transcribed_text
                or
                task.factual_outline
                or task.script_text
                or task.source_title
                or "Главная тема и конфликт видео."
            ).strip()
            thumbnail_script = (
                transcribed_text
                or
                task.script_text
                or task.factual_outline
                or task.source_title
                or thumbnail_outline
            ).strip()
            thumbnail_prompt, thumbnail_meta = _generate_avatar_thumbnail(
                factual_outline=thumbnail_outline,
                script_text=thumbnail_script,
                detail_text=(
                    "Генерирую вертикальную обложку 9:16 по теме готового HeyGen-видео."
                    if task.type in SHORT_AVATAR_TASK_TYPES
                    else "Генерирую обложку YouTube по теме готового HeyGen-видео."
                ),
            )

            youtube_description_meta = None
            if task.type not in SHORT_AVATAR_TASK_TYPES:
                hook_text, trigger_title, cta_text, final_description_text = _build_avatar_description_text(
                    script_text=thumbnail_script,
                    factual_outline=thumbnail_outline,
                    source_title=task.source_title,
                    description_template=user.youtube_description_template,
                )
                description_txt_path = _write_avatar_description_file(task_id, final_description_text)
                youtube_description_meta = {
                    "hook_text": hook_text,
                    "trigger_title": trigger_title,
                    "cta_text": cta_text,
                    "template": (user.youtube_description_template or "").strip(),
                    "final_text": final_description_text,
                    "txt_path": description_txt_path,
                }

            is_short_avatar = task.type in SHORT_AVATAR_TASK_TYPES
            update_task_status_message(
                db,
                task,
                stage="Монтаж",
                detail=(
                    "Рендерю стильную графику через Hyperframes (AI)."
                    if is_short_avatar
                    else "Рендерю YouTube-видео через Hyperframes: смысловые блоки, captions и KIE-визуалы."
                ),
            )
            render_output, renderer_name = _render_avatar_with_graphics(
                local_avatar_video,
                thumbnail_script,
                transcript_json_path=heygen_transcript_path or None,
            )
            if render_output:
                local_avatar_video = render_output
                if is_short_avatar:
                    local_avatar_video, remux_meta = _replace_video_audio_stream_copy(
                        local_avatar_video,
                        avatar_clean_audio_path,
                        stage="after_hyperframes",
                    )
                    current_meta = dict(task.script_meta or {})
                    current_meta["original_audio_remux"] = {
                        **dict(current_meta.get("original_audio_remux") or {}),
                        "after_hyperframes": remux_meta,
                    }
                    task.script_meta = current_meta
                    db.commit()
                _save_avatar_render_checkpoint(renderer_name, local_avatar_video)
                logging.info(
                    "Task %s: Successfully replaced raw video with %s output.",
                    task_id,
                    renderer_name,
                )
            else:
                raise Exception(
                    f"{renderer_name} rendering failed for ready HeyGen avatar task. "
                    "Raw HeyGen fallback is disabled by policy."
                )

            post_hyperframes_meta: dict = {}
            if is_short_avatar:
                thumbnail_image_path = str((thumbnail_meta or {}).get("output_path") or "").strip()
                local_avatar_video, vertical_cover_meta = _apply_short_avatar_vertical_cover(
                    local_avatar_video,
                    thumbnail_script,
                    cover_image_path=thumbnail_image_path,
                    cover_prompt=thumbnail_prompt,
                )
                post_hyperframes_meta["short_vertical_cover"] = vertical_cover_meta
                local_avatar_video, cover_audio_remux_meta = _replace_video_audio_stream_copy(
                    local_avatar_video,
                    avatar_clean_audio_path,
                    stage="after_vertical_cover",
                    audio_offset_seconds=REELS_VERTICAL_COVER_SECONDS,
                )
                post_hyperframes_meta["original_audio_remux"] = {
                    **dict(post_hyperframes_meta.get("original_audio_remux") or {}),
                    "after_vertical_cover": cover_audio_remux_meta,
                }
                if cover_audio_remux_meta.get("status") != "ready":
                    logging.warning(
                        "Task %s: failed to remux original ready-HeyGen audio after vertical cover; "
                        "keeping cover output audio. meta=%s",
                        task_id,
                        cover_audio_remux_meta,
                    )
            else:
                local_avatar_video, insert_meta = _apply_avatar_insert_montage(local_avatar_video)
                post_hyperframes_meta["avatar_insert_montage"] = insert_meta

            existing_meta = dict(task.script_meta or {})
            existing_meta["thumbnail_prompt"] = thumbnail_prompt
            existing_meta["thumbnail"] = thumbnail_meta
            for meta_key, meta_value in post_hyperframes_meta.items():
                if isinstance(meta_value, dict) and isinstance(existing_meta.get(meta_key), dict):
                    existing_meta[meta_key] = {
                        **dict(existing_meta.get(meta_key) or {}),
                        **meta_value,
                    }
                else:
                    existing_meta[meta_key] = meta_value
            if youtube_description_meta:
                existing_meta["youtube_description"] = youtube_description_meta
            else:
                existing_meta.pop("youtube_description", None)
            task.script_meta = existing_meta
            db.commit()

            input_videos.append(local_avatar_video)
            input_video_titles.append(task.source_title or f"Avatar Video {task_id}")
            input_video_contexts.append(thumbnail_script or task.source_title or f"Avatar Video {task_id}")

        elif task.type in INFOGRAPHIC_REELS_TASK_TYPES:
            update_task_status_message(db, task, stage="Инфографика", detail="Получаю исходный кадр и описание.")
            output_dir = os.getenv("OUTPUT_DIR", "./output").strip()
            os.makedirs(output_dir, exist_ok=True)
            caption = ""
            creator = ""
            source_title = (task.source_title or "").strip()
            source_frame_path = None
            source_media_path = None
            source_direct_image_url = None
            source_kind = "unknown"
            details = None

            if "instagram.com" in source_url:
                details = scraper.get_instagram_details(source_url)
                caption = ((details or {}).get("caption") or "").strip()
                creator = ((details or {}).get("creator") or "").strip()
                image_urls = [
                    url for url in ((details or {}).get("image_urls") or [])
                    if isinstance(url, str) and url.startswith(("http://", "https://"))
                ]
                if image_urls:
                    source_kind = "instagram_image"
                    source_direct_image_url = image_urls[0]
                    source_frame_path = downloader.download_media(image_urls[0], f"infographic_source_{task_id}")
                else:
                    download_url = _normalize_external_url(((details or {}).get("download_url") or "").strip())
                    if not download_url:
                        raise Exception("Failed to retrieve image or video URL for infographic format")
                    source_kind = "instagram_video"
                    source_media_path = downloader.download_video(download_url, f"infographic_source_video_{task_id}")
                    frame_output = os.path.join(output_dir, f"infographic_frame_{task_id}.jpg")
                    source_frame_path, frame_meta = _extract_frame_at_second(source_media_path, frame_output, second=1.0)
                    if not source_frame_path:
                        raise Exception(f"Failed to extract infographic source frame: {frame_meta.get('reason')}")
                if not source_title:
                    source_title = f"Instagram @{creator}" if creator else "Instagram"
            elif "youtube.com" in source_url or "youtu.be" in source_url:
                details = scraper.get_youtube_details(source_url)
                source_title = source_title or ((details or {}).get("title") or "").strip()
                transcript_value = (
                    ((details or {}).get("transcript_only_text") or "")
                    or ((details or {}).get("transcript") or "")
                    or source_title
                )
                caption = re.sub(r"\s+", " ", transcript_value if isinstance(transcript_value, str) else json.dumps(transcript_value, ensure_ascii=False)).strip()
                download_url = _normalize_external_url(((details or {}).get("download_url") or "").strip())
                if not download_url:
                    raise Exception("Failed to retrieve YouTube video URL for infographic format")
                source_kind = "youtube_video"
                source_media_path = downloader.download_video(download_url, f"infographic_source_video_{task_id}")
                frame_output = os.path.join(output_dir, f"infographic_frame_{task_id}.jpg")
                source_frame_path, frame_meta = _extract_frame_at_second(source_media_path, frame_output, second=1.0)
                if not source_frame_path:
                    raise Exception(f"Failed to extract infographic source frame: {frame_meta.get('reason')}")
            else:
                raise Exception("Infographic format supports Instagram posts/reels and YouTube Shorts")

            if not source_frame_path or not os.path.isfile(source_frame_path):
                raise Exception("Infographic source frame was not created")

            public_frame_url = None
            try:
                public_frame_url = thumbnail_generator._ensure_public_url(source_frame_path, prefix=f"infographic_frame_{task_id}")
            except Exception as public_url_error:
                logging.warning("Task %s: failed to make infographic frame public: %s", task_id, public_url_error)
            frame_data_url = image_file_to_data_url(source_frame_path)
            llm_frame_url = frame_data_url or public_frame_url or source_direct_image_url

            update_task_status_message(db, task, stage="Инфографика", detail="Читаю текст на кадре и собираю карточку.")
            card_payload = llm.generate_infographic_reels_card(
                image_url=llm_frame_url,
                caption=caption,
                source_title=source_title,
                style_profile=user.author_style_profile,
            )
            if not card_payload:
                raise Exception("Failed to generate infographic card payload")

            references = (
                db.query(models.ThumbnailReference)
                .filter(models.ThumbnailReference.user_id == user.id, models.ThumbnailReference.kind.in_(["vertical", "both"]))
                .order_by(models.ThumbnailReference.created_at.desc(), models.ThumbnailReference.id.desc())
                .all()
            )
            reference_paths = []
            for item in references:
                resolved = _resolve_media_file_path(item.file_path, media_kind="thumbnails")
                if resolved:
                    reference_paths.append(resolved)
                elif item.file_path:
                    reference_paths.append(item.file_path)
            active_infographic_face_path = user.vertical_thumbnail_face_path or user.thumbnail_face_path
            face_paths = [active_infographic_face_path] if active_infographic_face_path else []
            if not active_infographic_face_path:
                logging.warning("Task %s: infographic image generation has no active face reference", task_id)
            max_refs = int(os.getenv("VERTICAL_THUMBNAIL_MAX_STYLE_REFERENCES", "4"))

            update_task_status_message(db, task, stage="Инфографика", detail="Генерирую финальную карточку в нашем стиле.")
            infographic_image_path = os.path.join(output_dir, f"infographic_reels_{task_id}.png")
            infographic_image = thumbnail_generator.generate_thumbnail(
                prompt=card_payload["image_prompt"],
                face_path=active_infographic_face_path,
                face_paths=face_paths,
                reference_paths=reference_paths,
                output_path=infographic_image_path,
                aspect_ratio="9:16",
                resolution="1K",
                max_style_references=max_refs,
            )
            if not infographic_image:
                raise Exception(
                    "Не удалось сгенерировать картинку инфографики через KIE. "
                    f"{thumbnail_generator.get_last_error_message_ru()}"
                )

            audio_tracks = (
                db.query(models.InstagramPost5sAudioTrack)
                .filter(models.InstagramPost5sAudioTrack.user_id == user.id)
                .all()
            )
            usable_audio_tracks = [
                track for track in audio_tracks
                if track.file_path and os.path.isfile(track.file_path)
            ]
            selected_audio_track = random.choice(usable_audio_tracks) if usable_audio_tracks else None
            selected_audio_path = selected_audio_track.file_path if selected_audio_track else None

            update_task_status_message(db, task, stage="Монтаж", detail="Собираю 5-секундную инфографику с музыкой.")
            infographic_video_path = os.path.join(output_dir, f"infographic_reels_{task_id}.mp4")
            final_infographic_video, infographic_render_meta = _render_five_second_image_video(
                image_path=infographic_image,
                output_path=infographic_video_path,
                audio_path=selected_audio_path,
                duration_seconds=5.0,
            )
            if not final_infographic_video:
                raise Exception(
                    "Failed to render infographic video: "
                    f"{infographic_render_meta.get('reason')} file={infographic_render_meta.get('file')}"
                )

            description_txt_path = _write_publication_description_file(
                task_id,
                card_payload.get("description") or card_payload.get("title") or "",
                prefix="infographic_reels_description",
            )
            final_title = _clean_plate_title(card_payload.get("title"), fallback=source_title or "Инфографика")
            task.source_title = final_title
            task.script_text = card_payload.get("description") or final_title
            current_meta = dict(task.script_meta or {})
            current_meta["infographic_reels"] = {
                "status": "ready",
                "source_kind": source_kind,
                "source_media_path": source_media_path,
                "source_frame_path": source_frame_path,
                "source_direct_image_url": source_direct_image_url,
                "public_frame_url": public_frame_url,
                "llm_image_source": "data_url" if frame_data_url else ("public_url" if public_frame_url else "source_url"),
                "source_title": source_title,
                "caption": caption,
                "creator": creator,
                "card": card_payload,
                "description_txt_path": description_txt_path,
                "image_path": infographic_image,
                "selected_audio_track_id": selected_audio_track.id if selected_audio_track else None,
                "selected_audio_path": selected_audio_path,
                "render": infographic_render_meta,
                "used_reference_count": len(reference_paths[:max_refs]),
                "face_path": active_infographic_face_path,
            }
            task.script_meta = current_meta
            db.commit()

            input_videos.append(final_infographic_video)
            input_video_titles.append(final_title)
            input_video_contexts.append(card_payload.get("description") or final_title)

        elif task.type in INSTAGRAM_POST_FIVE_SECOND_TASK_TYPES:
            update_task_status_message(db, task, stage="Instagram Post", detail="Получаю картинку и подпись поста.")
            details = scraper.get_instagram_details(source_url)
            caption = ((details or {}).get("caption") or "").strip()
            creator = ((details or {}).get("creator") or "").strip()
            image_urls = [
                url for url in ((details or {}).get("image_urls") or [])
                if isinstance(url, str) and url.startswith(("http://", "https://"))
            ]
            if not image_urls:
                raise Exception("Failed to retrieve image URL for Instagram post 5s format")

            output_dir = os.getenv("OUTPUT_DIR", "./output").strip()
            os.makedirs(output_dir, exist_ok=True)
            source_image_url = image_urls[0]
            update_task_status_message(db, task, stage="Instagram Post", detail="Скачиваю изображение поста.")
            local_post_image = downloader.download_media(source_image_url, f"instagram_post_{task_id}")
            if not local_post_image:
                raise Exception("Failed to download Instagram post image")

            public_image_url = None
            try:
                public_image_url = thumbnail_generator._ensure_public_url(local_post_image, prefix=f"igpost{task_id}")
            except Exception as public_url_error:
                logging.warning("Task %s: failed to make Instagram post image public: %s", task_id, public_url_error)
            post_image_data_url = image_file_to_data_url(local_post_image)
            llm_post_image_url = post_image_data_url or public_image_url or source_image_url

            update_task_status_message(db, task, stage="Заголовок", detail="Анализирую текст на картинке и переписываю заголовок.")
            rewritten_title = llm.generate_instagram_post_5s_title(
                image_url=llm_post_image_url,
                caption=caption,
            )
            if not rewritten_title:
                rewritten_title = llm.generate_youtube_publication_title(caption) if caption else None
            final_title = _clean_plate_title(
                rewritten_title,
                fallback=(task.source_title or (f"Пост @{creator}" if creator else "Главный тезис")),
            )
            update_task_status_message(db, task, stage="Описание", detail="Переписываю описание поста под наш ролик.")
            rewritten_description = llm.generate_instagram_post_5s_description(
                caption=caption,
                title=final_title,
            )
            if not rewritten_description:
                rewritten_description = final_title
            description_txt_path = _write_publication_description_file(
                task_id,
                rewritten_description,
                prefix="instagram_post_5s_description",
            )
            task.source_title = final_title
            task.script_text = rewritten_description or final_title
            db.commit()

            update_task_status_message(db, task, stage="Изображение", detail="Очищаю картинку от текста через image-to-image.")
            clean_image_prompt = (
                "Use the provided Instagram post image as the main reference. "
                "Create a clean 9:16 vertical background image from it while keeping the original visual composition "
                "and camera distance as close as possible. Do not zoom out, shrink the person, or turn the source "
                "into a small centered poster. The main subject should stay large and prominent, close to the "
                "reference crop, with natural outpainting only where 9:16 needs extra space. Preserve the scene, "
                "colors, lighting and mood, but remove all readable text, captions, headlines, numbers, logos, "
                "UI elements, stickers, watermarks and overlay graphics. Do not add any new text, borders, sidebars "
                "or poster frame. The output must be only the visual first layer/background, ready for a separate "
                "title plate."
            )
            five_second_image_prompt = " ".join(
                str(getattr(user, "instagram_post_5s_image_prompt", None) or "").split()
            ).strip()
            if five_second_image_prompt:
                clean_image_prompt = (
                    f"{clean_image_prompt} Additional creative direction from the user: "
                    f"{five_second_image_prompt}"
                )
            clean_image_path = os.path.join(output_dir, f"instagram_post_clean_{task_id}.png")
            generated_clean_image = thumbnail_generator.generate_image_from_references(
                prompt=clean_image_prompt,
                reference_paths=[local_post_image],
                output_path=clean_image_path,
                aspect_ratio="9:16",
                resolution="1K",
            )
            if not generated_clean_image:
                kie_error_detail = thumbnail_generator.get_last_error_message_ru()
                current_meta = dict(task.script_meta or {})
                current_meta["instagram_post_5s"] = {
                    **dict(current_meta.get("instagram_post_5s") or {}),
                    "status": "failed",
                    "reason": "image_cleanup_failed",
                    "reason_detail": kie_error_detail,
                    "source_image_url": source_image_url,
                    "public_image_url": public_image_url,
                    "llm_image_source": "data_url" if post_image_data_url else ("public_url" if public_image_url else "source_url"),
                    "source_image_path": local_post_image,
                    "clean_image_path": clean_image_path,
                    "title": final_title,
                    "caption": caption,
                    "rewritten_description": rewritten_description,
                    "description_txt_path": description_txt_path,
                    "creator": creator,
                    "image_prompt": five_second_image_prompt or None,
                }
                task.script_meta = current_meta
                db.commit()
                if (os.getenv("INSTAGRAM_POST_5S_ALLOW_ORIGINAL_IMAGE_FALLBACK") or "0").strip() in {"1", "true", "True"}:
                    logging.warning("Task %s: image cleanup failed; using original post image as fallback.", task_id)
                    generated_clean_image = local_post_image
                else:
                    raise Exception(
                        "Не удалось очистить картинку для формата 5 секунд через KIE. "
                        f"{kie_error_detail}"
                    )

            audio_tracks = (
                db.query(models.InstagramPost5sAudioTrack)
                .filter(models.InstagramPost5sAudioTrack.user_id == user.id)
                .all()
            )
            usable_audio_tracks = [
                track for track in audio_tracks
                if track.file_path and os.path.isfile(track.file_path)
            ]
            selected_audio_track = random.choice(usable_audio_tracks) if usable_audio_tracks else None
            selected_audio_path = selected_audio_track.file_path if selected_audio_track else None
            overlay_path = (
                user.instagram_post_5s_overlay_path
                if user.instagram_post_5s_overlay_path and os.path.isfile(user.instagram_post_5s_overlay_path)
                else None
            )
            five_second_cta_text = "\n".join(
                line
                for line in (
                    " ".join(raw_line.split())
                    for raw_line in (getattr(user, "instagram_post_5s_cta_text", None) or "").replace("\r\n", "\n").split("\n")
                )
                if line
            ).strip() or None

            update_task_status_message(db, task, stage="Монтаж", detail="Собираю 5-секундное видео с плашкой.")
            five_second_output = os.path.join(output_dir, f"instagram_post_5s_{task_id}.mp4")
            final_post_video, five_second_meta = _render_five_second_post_video(
                image_path=generated_clean_image,
                title=final_title,
                output_path=five_second_output,
                audio_path=selected_audio_path,
                overlay_path=overlay_path,
                cta_text=five_second_cta_text,
                duration_seconds=5.0,
            )
            if not final_post_video:
                raise Exception(
                    "Failed to render Instagram post 5s video: "
                    f"{five_second_meta.get('reason')} file={five_second_meta.get('file')}"
                )

            current_meta = dict(task.script_meta or {})
            current_meta["instagram_post_5s"] = {
                "status": "ready",
                "source_image_url": source_image_url,
                "public_image_url": public_image_url,
                "llm_image_source": "data_url" if post_image_data_url else ("public_url" if public_image_url else "source_url"),
                "source_image_path": local_post_image,
                "clean_image_path": generated_clean_image,
                "title": final_title,
                "caption": caption,
                "rewritten_description": rewritten_description,
                "description_txt_path": description_txt_path,
                "selected_audio_track_id": selected_audio_track.id if selected_audio_track else None,
                "selected_audio_path": selected_audio_path,
                "overlay_path": overlay_path,
                "cta_text": five_second_cta_text,
                "image_prompt": five_second_image_prompt or None,
                "creator": creator,
                "render": five_second_meta,
            }
            task.script_meta = current_meta
            db.commit()

            input_videos.append(final_post_video)
            input_video_titles.append(final_title)
            input_video_contexts.append(rewritten_description or final_title)

        elif task.type in AVATAR_TASK_TYPES:
            cleaned_reels_transcript = ""
            local_reel_source = None
            if task.type in {"avatar_instagram", *INSTAGRAM_POST_FIVE_SECOND_TASK_TYPES}:
                is_instagram_post_5s = task.type in INSTAGRAM_POST_FIVE_SECOND_TASK_TYPES
                instagram_content_label = "Instagram Post" if is_instagram_post_5s else "Instagram Reels"
                update_task_status_message(db, task, stage="Сценарий", detail=f"Получаю данные {instagram_content_label}.")
                t_data = scraper.get_instagram_details(source_url)
                caption = ((t_data or {}).get("caption") or "").strip()
                creator = ((t_data or {}).get("creator") or "").strip()
                view_count = (t_data or {}).get("view_count")
                download_url = "" if is_instagram_post_5s else _normalize_external_url(((t_data or {}).get("download_url") or "").strip())
                source_title = (task.source_title or "").strip()
                if not source_title:
                    if is_instagram_post_5s:
                        source_title = f"Instagram Post 5 секунд @{creator}" if creator else "Instagram Post 5 секунд"
                    else:
                        source_title = f"Instagram Reel @{creator}" if creator else "Instagram Reel"
                    task.source_title = source_title
                    db.commit()

                reel_transcript = ""
                if download_url and deepgram_client.is_configured:
                    update_task_status_message(
                        db,
                        task,
                        stage="Сценарий",
                        detail="Транскрибирую аудио Instagram Reels.",
                    )
                    local_reel_source = downloader.download_video(download_url, f"reels_avatar_source_{task_id}")
                    if local_reel_source:
                        try:
                            reel_transcript = (deepgram_client.transcribe_media_text(local_reel_source) or "").strip()
                        except Exception as transcribe_error:
                            logging.warning(
                                "Task %s: Deepgram transcription failed for Instagram Reel: %s",
                                task_id,
                                transcribe_error,
                            )

                if not reel_transcript and not caption:
                    raise Exception(f"Failed to retrieve usable text for {instagram_content_label}")
                raw_reels_transcript = "\n".join(
                    part for part in [
                        f"Transcript: {reel_transcript}" if reel_transcript else "",
                        f"Caption: {caption}" if caption else "",
                        f"Creator: @{creator}" if creator else "",
                        f"Views: {view_count}" if view_count else "",
                    ]
                    if part
                )
                update_task_status_message(db, task, stage="Сценарий", detail=f"Удаляю CTA и промо из {instagram_content_label}.")
                cleaned_reels_transcript = (
                    llm.remove_cta_from_transcript(raw_reels_transcript)
                    or _strip_cta_fallback(raw_reels_transcript)
                ).strip()
                if not cleaned_reels_transcript:
                    raise Exception(f"Failed to clean {instagram_content_label} text")
                transcript = cleaned_reels_transcript
            elif task.type == "avatar_shorts":
                update_task_status_message(db, task, stage="Сценарий", detail="Получаю транскрипт YouTube Shorts.")
                t_data = scraper.get_youtube_transcript(source_url)
                shorts_transcript = (t_data.get("transcript_only_text") if t_data else None) or ""
                source_title = (t_data.get("title") if t_data else None) or task.source_title
                if source_title and not task.source_title:
                    task.source_title = str(source_title).strip()
                    db.commit()
                if not shorts_transcript.strip():
                    raise Exception("Failed to retrieve transcript for YouTube Shorts Avatar task")

                raw_shorts_transcript = "\n".join(
                    part for part in [
                        f"Transcript: {shorts_transcript.strip()}",
                        f"Title: {str(source_title).strip()}" if source_title else "",
                    ]
                    if part
                )
                update_task_status_message(db, task, stage="Сценарий", detail="Удаляю CTA и промо из Shorts.")
                cleaned_reels_transcript = (
                    llm.remove_cta_from_transcript(raw_shorts_transcript)
                    or _strip_cta_fallback(raw_shorts_transcript)
                ).strip()
                if not cleaned_reels_transcript:
                    raise Exception("Failed to clean YouTube Shorts transcript")
                transcript = cleaned_reels_transcript
            else:
                update_task_status_message(db, task, stage="Сценарий", detail="Получаю транскрипт видео.")
                t_data = scraper.get_youtube_transcript(source_url)
                transcript = t_data.get("transcript_only_text") if t_data else None
                source_title = (t_data.get("title") if t_data else None) or task.source_title
                if source_title and not task.source_title:
                    task.source_title = str(source_title).strip()
                    db.commit()
                
                if not transcript:
                    raise Exception("Failed to retrieve transcript for Avatar task")
            
            # factual outline
            update_task_status_message(db, task, stage="Сценарий", detail="Выделяю ключевые факты (Gemini 2.5 Pro).")
            outline = llm.generate_factual_outline(transcript)
            if not outline:
                logging.warning(
                    "Task %s: factual outline generation returned empty; retrying once. transcript_chars=%s",
                    task_id,
                    count_script_chars(transcript),
                )
                outline = llm.generate_factual_outline(transcript)
            if not outline:
                logging.warning(
                    "Task %s: factual outline generation failed twice; using transcript fallback outline.",
                    task_id,
                )
                outline = (
                    "FACTUAL OUTLINE FALLBACK\n"
                    "OpenRouter/Gemini did not return an outline. Use this cleaned transcript as the factual source:\n"
                    f"{transcript}"
                )
            task.factual_outline = outline
            db.commit()
            
            voice_id = (user.elevenlabs_voice_id or os.getenv("ELEVENLABS_VOICE_ID", "nPczCjzB2oQXqZ4mU67e")).strip()
            voice_speed = get_cached_voice_speed(user, voice_id)
            if not voice_speed:
                voice_speed = get_or_calibrate_voice_speed(
                    db=db,
                    user=user,
                    voice_id=voice_id,
                    elevenlabs_client=elevenlabs_client,
                )
            chars_per_second = float((voice_speed or {}).get("chars_per_second") or 0)
            style_profile = user.author_style_profile
            min_words = AVATAR_SCRIPT_MIN_MINUTES * AVATAR_SCRIPT_WPM
            max_words = AVATAR_SCRIPT_MAX_MINUTES * AVATAR_SCRIPT_WPM
            target_duration_minutes = int(getattr(user, "avatar_script_duration_minutes", 5) or 5)
            target_duration_minutes = max(1, min(30, target_duration_minutes))
            avatar_vertical_duration_seconds = int(getattr(user, "avatar_vertical_duration_seconds", 0) or 0)
            if avatar_vertical_duration_seconds < 5 or avatar_vertical_duration_seconds > 300:
                avatar_vertical_duration_seconds = 0

            if task.type in SHORT_AVATAR_TASK_TYPES:
                if task.type in INSTAGRAM_POST_FIVE_SECOND_TASK_TYPES:
                    target_duration_seconds = 5.0
                    target_chars = int(round(chars_per_second * target_duration_seconds)) if chars_per_second > 0 else 70
                    target_chars = max(45, min(120, target_chars))
                    min_chars = max(35, int(round(target_chars * 0.9)))
                    max_chars = max(min_chars + 10, int(round(target_chars * 1.1)))
                elif avatar_vertical_duration_seconds > 0:
                    target_duration_seconds = float(avatar_vertical_duration_seconds)
                    fallback_chars_per_second = max(6.0, (AVATAR_SCRIPT_WPM * 6.0) / 60.0)
                    effective_chars_per_second = chars_per_second if chars_per_second > 0 else fallback_chars_per_second
                    target_chars = max(80, int(round(effective_chars_per_second * target_duration_seconds)))
                    min_chars = max(60, int(round(target_chars * 0.9)))
                    max_chars = max(min_chars + 10, int(round(target_chars * 1.1)))
                else:
                    original_char_count = count_script_chars(cleaned_reels_transcript)
                    target_chars = max(80, original_char_count)
                    min_chars = max(40, int(round(target_chars * 0.97)))
                    max_chars = max(min_chars + 10, int(round(target_chars * 1.03)))
                    target_duration_seconds = (
                        round(target_chars / chars_per_second, 2)
                        if chars_per_second > 0
                        else None
                    )
                update_task_status_message(
                    db,
                    task,
                    stage="Сценарий",
                    detail=(
                        "Сжимаю пост в сценарий на 5 секунд и усиливаю хук."
                        if task.type in INSTAGRAM_POST_FIVE_SECOND_TASK_TYPES
                        else (
                            f"Сжимаю сценарий под {avatar_vertical_duration_seconds} сек. и усиливаю хук."
                            if avatar_vertical_duration_seconds > 0
                            else "Подгоняю сценарий под длительность озвучки и усиливаю хук."
                        )
                    ),
                )
                script = llm.rewrite_reels_avatar_script(
                    cleaned_transcript=cleaned_reels_transcript,
                    style_profile=style_profile,
                    target_chars=target_chars,
                    min_chars=min_chars,
                    max_chars=max_chars,
                    voice_chars_per_second=chars_per_second or None,
                    target_duration_seconds=target_duration_seconds,
                )
                if not script:
                    logging.warning(
                        "Task %s: short Avatar script rewrite returned empty; retrying once. "
                        "cleaned_chars=%s target=%s range=%s-%s",
                        task_id,
                        count_script_chars(cleaned_reels_transcript),
                        target_chars,
                        min_chars,
                        max_chars,
                    )
                    script = llm.rewrite_reels_avatar_script(
                        cleaned_transcript=cleaned_reels_transcript,
                        style_profile=style_profile,
                        target_chars=target_chars,
                        min_chars=min_chars,
                        max_chars=max_chars,
                        voice_chars_per_second=chars_per_second or None,
                        target_duration_seconds=target_duration_seconds,
                    )
                if not script:
                    logging.warning(
                        "Task %s: short Avatar script rewrite failed twice; using cleaned transcript fallback.",
                        task_id,
                    )
                    script = cleaned_reels_transcript
                word_count = llm.estimate_word_count(script)
                char_count = count_script_chars(script)
                if char_count < min_chars or char_count > max_chars:
                    adjusted_script = _clamp_script_to_char_range(
                        script=script,
                        style_profile=style_profile,
                        min_chars=min_chars,
                        max_chars=max_chars,
                    )
                    if adjusted_script:
                        script = adjusted_script
                        word_count = llm.estimate_word_count(script)
                        char_count = count_script_chars(script)
            else:
                target_chars = int(round(chars_per_second * target_duration_minutes * 60)) if chars_per_second > 0 else None
                min_chars = int(round(target_chars * 0.92)) if target_chars else None
                max_chars = int(round(target_chars * 1.08)) if target_chars else None

                update_task_status_message(
                    db,
                    task,
                    stage="Сценарий",
                    detail=(
                        f"Пишу сценарий в вашем стиле на {target_duration_minutes} мин."
                        if target_chars
                        else "Пишу сценарий в вашем стиле на 4-6 минут."
                    ),
                )
                structured_source = (
                    "FACTUAL OUTLINE (ключевые смыслы):\n"
                    f"{outline}\n\n"
                    "RAW TRANSCRIPT (оригинальный поток речи, может быть не по порядку):\n"
                    f"{transcript}"
                )
                script = llm.rewrite_to_script(
                    structured_source,
                    style_profile,
                    min_minutes=target_duration_minutes if target_chars else AVATAR_SCRIPT_MIN_MINUTES,
                    max_minutes=target_duration_minutes if target_chars else AVATAR_SCRIPT_MAX_MINUTES,
                    words_per_minute=AVATAR_SCRIPT_WPM,
                    target_chars=target_chars,
                    min_chars=min_chars,
                    max_chars=max_chars,
                )
                if not script:
                    logging.warning(
                        "Task %s: styled Avatar script generation returned empty; retrying once.",
                        task_id,
                    )
                    script = llm.rewrite_to_script(
                        structured_source,
                        style_profile,
                        min_minutes=target_duration_minutes if target_chars else AVATAR_SCRIPT_MIN_MINUTES,
                        max_minutes=target_duration_minutes if target_chars else AVATAR_SCRIPT_MAX_MINUTES,
                        words_per_minute=AVATAR_SCRIPT_WPM,
                        target_chars=target_chars,
                        min_chars=min_chars,
                        max_chars=max_chars,
                    )
                if not script:
                    logging.warning(
                        "Task %s: styled Avatar script generation failed twice; using structured source fallback.",
                        task_id,
                    )
                    script = structured_source

                word_count = llm.estimate_word_count(script)
                char_count = count_script_chars(script)
                if target_chars and min_chars and max_chars and (char_count < min_chars or char_count > max_chars):
                    update_task_status_message(
                        db,
                        task,
                        stage="Сценарий",
                        detail=f"Подгоняю длину сценария под {target_duration_minutes} мин.",
                    )
                    adjusted_script = _clamp_script_to_char_range(
                        script=script,
                        style_profile=style_profile,
                        min_chars=min_chars,
                        max_chars=max_chars,
                    )
                    if adjusted_script:
                        script = adjusted_script
                        word_count = llm.estimate_word_count(script)
                        char_count = count_script_chars(script)
                elif not target_chars and (word_count < min_words or word_count > max_words):
                    update_task_status_message(
                        db,
                        task,
                        stage="Сценарий",
                        detail="Подгоняю длину сценария под 4-6 минут.",
                    )
                    adjusted_script = llm.adjust_script_length(
                        script=script,
                        style_profile=style_profile,
                        min_words=min_words,
                        max_words=max_words,
                    )
                    if adjusted_script:
                        script = adjusted_script
                        word_count = llm.estimate_word_count(script)
                        char_count = count_script_chars(script)

                # humanize pass (remove AI-like patterns and strengthen opening)
                update_task_status_message(
                    db,
                    task,
                    stage="Сценарий",
                    detail="Очеловечиваю текст и усиливаю начало.",
                )
                if target_chars and min_chars and max_chars:
                    humanized_script = llm.humanize_russian_text_by_chars(
                        script=script,
                        style_profile=style_profile,
                        min_chars=min_chars,
                        max_chars=max_chars,
                    )
                else:
                    humanized_script = llm.humanize_russian_text(
                        script=script,
                        style_profile=style_profile,
                        min_words=min_words,
                        max_words=max_words,
                    )
                if humanized_script:
                    script = humanized_script
                    word_count = llm.estimate_word_count(script)
                    char_count = count_script_chars(script)

                # final length guard after humanization
                if target_chars and min_chars and max_chars and (char_count < min_chars or char_count > max_chars):
                    update_task_status_message(
                        db,
                        task,
                        stage="Сценарий",
                        detail="Финально подгоняю объем после очеловечивания.",
                    )
                    adjusted_script = _clamp_script_to_char_range(
                        script=script,
                        style_profile=style_profile,
                        min_chars=min_chars,
                        max_chars=max_chars,
                    )
                    if adjusted_script:
                        script = adjusted_script
                        word_count = llm.estimate_word_count(script)
                        char_count = count_script_chars(script)
                elif not target_chars and (word_count < min_words or word_count > max_words):
                    update_task_status_message(
                        db,
                        task,
                        stage="Сценарий",
                        detail="Финально подгоняю объем после очеловечивания.",
                    )
                    adjusted_script = llm.adjust_script_length(
                        script=script,
                        style_profile=style_profile,
                        min_words=min_words,
                        max_words=max_words,
                    )
                    if adjusted_script:
                        script = adjusted_script
                        word_count = llm.estimate_word_count(script)
                        char_count = count_script_chars(script)

            # faithfulness check
            update_task_status_message(db, task, stage="Сценарий", detail="Проверяю сценарий на соответствие фактам.")
            validation = llm.verify_faithfulness(outline, script)
            estimated_minutes = (
                round(count_script_chars(script) / chars_per_second / 60, 2)
                if chars_per_second > 0
                else _estimate_script_minutes(script, AVATAR_SCRIPT_WPM)
            )
            thumbnail_prompt, thumbnail_meta = _generate_avatar_thumbnail(
                factual_outline=outline,
                script_text=script,
            )
            hook_text, trigger_title, cta_text, final_description_text = _build_avatar_description_text(
                script_text=script,
                factual_outline=outline,
                source_title=task.source_title,
                description_template=user.youtube_description_template,
            )
            description_txt_path = _write_avatar_description_file(task_id, final_description_text)
            existing_script_meta = dict(task.script_meta or {})
            short_avatar_meta = {}
            if task.type in SHORT_AVATAR_TASK_TYPES:
                short_avatar_meta = {
                    "short_avatar": {
                        "cleaned_transcript": cleaned_reels_transcript,
                        "cleaned_transcript_char_count": count_script_chars(cleaned_reels_transcript),
                        "target_duration_seconds_by_voice_speed": target_duration_seconds,
                        "configured_target_duration_seconds": avatar_vertical_duration_seconds or None,
                    }
                }
            task.script_text = script
            task.script_meta = {
                **(validation or {}),
                **short_avatar_meta,
                "target_minutes": target_duration_minutes,
                "target_chars": target_chars,
                "target_chars_range": [min_chars, max_chars] if min_chars and max_chars else None,
                "voice_id": voice_id,
                "voice_chars_per_second": chars_per_second or None,
                "words_per_minute_assumption": AVATAR_SCRIPT_WPM,
                "word_count": word_count,
                "char_count": count_script_chars(script),
                "estimated_minutes": estimated_minutes,
                "thumbnail_prompt": thumbnail_prompt,
                "thumbnail_prompt_review": existing_script_meta.get("thumbnail_prompt_review"),
                "thumbnail": thumbnail_meta,
                "youtube_description": {
                    "hook_text": hook_text,
                    "trigger_title": trigger_title,
                    "cta_text": cta_text,
                    "template": (user.youtube_description_template or "").strip(),
                    "final_text": final_description_text,
                    "txt_path": description_txt_path,
                },
            }
            db.commit()

            # ElevenLabs audio generation
            update_task_status_message(
                db,
                task,
                stage="Озвучка",
                detail="Генерирую аудио через ElevenLabs (v2).",
            )
            
            audio_output_path = os.path.join(
                os.getenv("OUTPUT_DIR", "./output").strip(),
                f"avatar_audio_{task_id}.mp3"
            )
            
            os.makedirs(os.path.dirname(audio_output_path), exist_ok=True)
            
            logging.info(f"Generating audio for task {task_id} using voice_id: {voice_id}")

            generated_audio = elevenlabs_client.generate_audio(
                text=script,
                voice_id=voice_id,
                output_path=audio_output_path
            )

            if not generated_audio:
                raise Exception("Failed to generate audio with ElevenLabs")
            avatar_clean_audio_path = audio_output_path

            actual_audio_seconds = get_audio_duration_seconds(audio_output_path)
            if actual_audio_seconds and actual_audio_seconds > 0:
                estimated_minutes = round(actual_audio_seconds / 60, 2)
                current_meta = dict(task.script_meta or {})
                current_meta["actual_audio_duration_seconds"] = round(actual_audio_seconds, 3)
                current_meta["estimated_minutes"] = estimated_minutes
                current_meta["actual_voice_chars_per_second"] = round(
                    count_script_chars(script) / actual_audio_seconds,
                    3,
                )
                task.script_meta = current_meta
                db.commit()

            # --- HeyGen Video Generation ---
            avatar_id = (
                (
                    user.heygen_vertical_avatar_id
                    if task.type in SHORT_AVATAR_TASK_TYPES
                    else user.heygen_avatar_id
                )
                or user.heygen_avatar_id
                or os.getenv("HEYGEN_AVATAR_ID", "788070966a344933a30c6a8581005a30")
            ).strip()
            avatar_engine = (getattr(user, "heygen_avatar_engine", None) or "avatar_iv").strip().lower()
            if avatar_engine not in {"avatar_iv", "avatar_v"}:
                avatar_engine = "avatar_iv"
            heygen_api_version = (getattr(user, "heygen_video_api_version", None) or "v2").strip().lower()
            if heygen_api_version not in {"v2", "v3"}:
                heygen_api_version = "v2"
            avatar_look = asyncio.run(heygen_client.get_avatar_look(avatar_id))
            avatar_type = ((avatar_look or {}).get("avatar_type") or "").strip().lower()
            supported_engines = [
                str(engine).strip().lower()
                for engine in ((avatar_look or {}).get("supported_api_engines") or [])
                if str(engine).strip()
            ]
            logging.info(
                "Task %s: using selected HeyGen generation model api_version=%s engine=%s avatar=%s avatar_type=%s supported_engines=%s",
                task_id,
                heygen_api_version,
                avatar_engine if heygen_api_version == "v3" else None,
                avatar_id,
                avatar_type or None,
                supported_engines,
            )
            motion_prompt = None
            expressiveness = None
            if avatar_type == "photo_avatar" and heygen_api_version == "v3" and avatar_engine == "avatar_iv":
                motion_prompt = (
                    os.getenv("HEYGEN_PHOTO_AVATAR_MOTION_PROMPT")
                    or (
                        "The subject appears as a natural, expressive presenter speaking directly to the camera. "
                        "The camera stays stable and professional, while the performance feels alive, focused, and confident. "
                        "Facial expression remains neutral and attentive, without a smile, with subtle changes that match "
                        "the rhythm and emphasis of speech.\n\n"
                        "Use natural presenter movement: small shifts in posture, controlled head movement, steady eye contact, "
                        "and restrained hand movement when it supports emphasis. The gestures should feel conversational and "
                        "intentional, not theatrical or exaggerated.\n\n"
                        "The overall delivery should feel like a clear, expressive narrator or news-style speaker: composed, "
                        "engaged, professional, and dynamic enough to avoid looking frozen. Avoid forced smiling, waving, "
                        "large gestures, dancing, or dramatic body movement."
                    )
                ).strip()
                expressiveness = (os.getenv("HEYGEN_PHOTO_AVATAR_EXPRESSIVENESS") or "high").strip().lower()
            update_task_status_message(
                db,
                task,
                stage="HeyGen",
                detail=(
                    f"Отправляю аудио в HeyGen {heygen_api_version}"
                    f"{f' ({avatar_engine})' if heygen_api_version == 'v3' else ''}"
                    f", Avatar: {avatar_id}."
                ),
            )
            
            # 1. Upload audio to HeyGen assets
            audio_asset_id = asyncio.run(heygen_client.upload_asset(audio_output_path))
            if not audio_asset_id:
                raise Exception("Failed to upload audio to HeyGen assets")
                
            # 2. Generate video
            update_task_status_message(db, task, stage="HeyGen", detail="Генерирую видео с аватаром...")
            heygen_video_id = asyncio.run(
                heygen_client.generate_avatar_video(
                    avatar_id,
                    audio_asset_id,
                    orientation="vertical" if task.type in SHORT_AVATAR_TASK_TYPES else "horizontal",
                    api_version=heygen_api_version,
                    engine=avatar_engine,
                    title=task.source_title or f"Turan Avatar {task_id}",
                    motion_prompt=motion_prompt,
                    expressiveness=expressiveness,
                )
            )
            if not heygen_video_id:
                raise Exception("Failed to submit video generation to HeyGen")
            current_meta = dict(task.script_meta or {})
            current_meta["heygen_generation"] = {
                "api_version": heygen_api_version,
                "engine": avatar_engine if heygen_api_version == "v3" else None,
                "avatar_id": avatar_id,
                "avatar_type": avatar_type or None,
                "forced_photo_avatar_v3": False,
                "motion_prompt": bool(motion_prompt),
                "expressiveness": expressiveness,
                "video_id": heygen_video_id,
            }
            task.script_meta = current_meta
            db.commit()
                
            # 3. Poll for completion
            update_task_status_message(db, task, stage="HeyGen", detail="Ожидаю рендеринг аватара (это может занять 10-20 мин)...")
            final_video_url = asyncio.run(heygen_client.poll_video_status(heygen_video_id))
            if not final_video_url:
                raise Exception("HeyGen video generation timed out or failed")
                
            # 4. Download result
            update_task_status_message(db, task, stage="Монтаж", detail="Скачиваю готовое видео из HeyGen.")
            final_video_path = os.path.join(
                os.getenv("OUTPUT_DIR", "./output").strip(),
                f"avatar_video_{task_id}.mp4"
            )
            local_avatar_video = downloader.download_media(final_video_url, f"heygen_{task_id}")
            if not local_avatar_video:
                raise Exception("Failed to download final video from HeyGen")

            if task.type in SHORT_AVATAR_TASK_TYPES:
                current_meta = dict(task.script_meta or {})
                current_meta["broll"] = {
                    "status": "skipped",
                    "reason": "hyperframes_replaces_broll_for_short_avatar",
                }
                task.script_meta = current_meta
                db.commit()
                
            # --- Hyperframes Rendering ---
            is_short_avatar = task.type in SHORT_AVATAR_TASK_TYPES
            update_task_status_message(
                db,
                task,
                stage="Монтаж",
                detail=(
                    "Рендерю стильную графику через Hyperframes (AI)."
                    if is_short_avatar
                    else "Рендерю YouTube-видео через Hyperframes: смысловые блоки, captions и KIE-визуалы."
                ),
            )
            render_output, renderer_name = _render_avatar_with_graphics(
                local_avatar_video,
                script,
            )
            if render_output:
                local_avatar_video = render_output
                _save_avatar_render_checkpoint(renderer_name, local_avatar_video)
                logging.info(
                    "Task %s: Successfully replaced raw video with %s output.",
                    task_id,
                    renderer_name,
                )
            else:
                raise Exception(
                    f"{renderer_name} rendering failed for avatar task. "
                    "Raw HeyGen fallback is disabled by policy."
                )

            if not is_short_avatar:
                local_avatar_video, insert_meta = _apply_avatar_insert_montage(local_avatar_video)
                current_meta = dict(task.script_meta or {})
                current_meta["avatar_insert_montage"] = insert_meta
                task.script_meta = current_meta
                db.commit()

            if task.type in SHORT_AVATAR_TASK_TYPES:
                thumbnail_image_path = str((thumbnail_meta or {}).get("output_path") or "").strip()
                local_avatar_video, vertical_cover_meta = _apply_short_avatar_vertical_cover(
                    local_avatar_video,
                    script,
                    cover_image_path=thumbnail_image_path,
                    cover_prompt=thumbnail_prompt,
                )
                local_avatar_video, cover_remux_meta = _replace_video_audio_with_elevenlabs(
                    local_avatar_video,
                    avatar_clean_audio_path,
                    stage="after_vertical_cover",
                )
                current_meta = dict(task.script_meta or {})
                current_meta["short_vertical_cover"] = vertical_cover_meta
                current_meta["elevenlabs_audio_remux"] = {
                    **dict(current_meta.get("elevenlabs_audio_remux") or {}),
                    "after_vertical_cover": cover_remux_meta,
                }
                task.script_meta = current_meta
                db.commit()
                
            # --- Final Post-Processing (Plates/Endings) ---
            # We treat this video as the 'source' for the final step
            input_videos.append(local_avatar_video)
            input_video_titles.append(task.source_title or f"Avatar Video {task_id}")
            input_video_contexts.append(task.script_text or task.factual_outline or task.source_title or f"Avatar Video {task_id}")
            # Continue to standard processing loop below


        elif task.type == "instagram":
            update_task_status_message(db, task, stage="Скачивание", detail="Скачиваю видео из Instagram.")
            details = scraper.get_instagram_details(source_url)
            caption = ((details or {}).get("caption") or "").strip()
            creator = ((details or {}).get("creator") or "").strip()
            source_title = (task.source_title or "").strip()
            if not source_title:
                first_caption_line = re.sub(r"\s+", " ", caption).strip()
                source_title = first_caption_line[:140].strip() or (
                    f"Instagram Reel @{creator}" if creator else "Instagram Reel"
                )
                task.source_title = source_title
                current_meta = dict(task.script_meta or {})
                current_meta["instagram_source"] = {
                    "creator": creator or None,
                    "caption": caption or None,
                }
                task.script_meta = current_meta
                db.commit()
            download_url = _normalize_external_url((details or {}).get("download_url") or "")
            if not download_url:
                error_text = (details or {}).get("error") or "Failed to get Instagram download link"
                raise Exception(error_text)

            local_file = downloader.download_video(download_url, f"insta_{task_id}")
            if not local_file:
                raise Exception("Failed to download Instagram video from ScrapeCreators URL")
            input_videos.append(local_file)
            input_video_titles.append(source_title)
            input_video_contexts.append(caption or source_title)

        elif task.type == "youtube":
            _validate_youtube_url_or_raise(source_url)
            youtube_video_id = _extract_youtube_video_id(source_url)
            if not youtube_video_id:
                raise Exception("Failed to normalize YouTube video id")
            if _is_youtube_shorts_url(source_url):
                update_task_status_message(db, task, stage="Скачивание", detail="Скачиваю YouTube Shorts через RapidAPI.")
                provider_source_url = f"https://www.youtube.com/shorts/{youtube_video_id}"
                local_file = None
                rapid_details = {}
                rapid_error = ""
                for rapid_attempt in range(1, 4):
                    rapid_details = youtube_downloader.get_youtube_details(provider_source_url)
                    rapid_download_url = _normalize_external_url((rapid_details or {}).get("download_url") or "")
                    if not rapid_download_url:
                        rapid_error = (rapid_details or {}).get("error") or "нет ссылки на скачивание"
                        break

                    local_file = downloader.download_video(
                        rapid_download_url,
                        f"yt_{task_id}_rapidapi_{rapid_attempt}",
                    )
                    if local_file:
                        break

                    rapid_error = "ссылка RapidAPI недоступна"
                    logging.warning(
                        "Task %s: RapidAPI YouTube direct download failed on attempt %s/3 host=%s status=%s",
                        task_id,
                        rapid_attempt,
                        urlparse(rapid_download_url).netloc,
                        (rapid_details or {}).get("status"),
                    )
                    if rapid_attempt < 3:
                        update_task_status_message(
                            db,
                            task,
                            stage="Скачивание",
                            detail=f"RapidAPI дал битую ссылку, пробую заново ({rapid_attempt + 1}/3).",
                        )
                        time.sleep(2)

                if not local_file:
                    raise Exception(
                        "Не удалось скачать YouTube Shorts через RapidAPI: "
                        f"{rapid_error or 'ссылка на файл недоступна'}"
                    )

                details = scraper.get_youtube_details(provider_source_url) or {}
                if details.get("error"):
                    logging.warning(
                        "Task %s: ScrapeCreators metadata unavailable after RapidAPI download: %s",
                        task_id,
                        details.get("error"),
                    )
                source_title = (
                    (task.source_title or "").strip()
                    or str((details or {}).get("title") or "").strip()
                    or "YouTube Shorts"
                )
                if source_title and source_title != (task.source_title or "").strip():
                    task.source_title = source_title
                    db.commit()

                logging.info(
                    "Task %s: downloaded YouTube Shorts via RapidAPI status=%s",
                    task_id,
                    (rapid_details or {}).get("status"),
                )
                transcript_context = ((details or {}).get("transcript_only_text") or "").strip()
                if not transcript_context:
                    transcript_data = scraper.get_youtube_transcript(provider_source_url) or {}
                    transcript_context = (transcript_data.get("transcript_only_text") or "").strip()
                input_videos.append(local_file)
                input_video_titles.append(source_title)
                input_video_contexts.append(transcript_context or source_title)
            else:
                logging.info("Task %s: routed full YouTube video to Vizard", task_id)
                update_task_status_message(db, task, stage="Vizard", detail="Полное YouTube-видео отправлено в Vizard.")
                clips = _download_vizard_project_clips(
                    db,
                    task,
                    source_url,
                    video_type=2,
                    prefer_length=[2],
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
                input_video_contexts.extend(title for _path, title in clips)

        if not input_videos:
            raise Exception("No input videos were downloaded")
        while len(input_video_contexts) < len(input_videos):
            index = len(input_video_contexts)
            input_video_contexts.append(input_video_titles[index] if len(input_video_titles) > index else None)
        update_task_status_message(db, task, stage="Монтаж", detail="Собираю финальные ролики.")
        process_all_clips = bool(task.vizard_project_id)
        if task.type in AVATAR_TASK_TYPES:
            # Avatar flow always has a single HeyGen source clip and must not fan out by clip.
            process_all_clips = False
        if process_all_clips:
            source_items = [
                (
                    index,
                    input_videos[index - 1],
                    input_video_titles[index - 1] if len(input_video_titles) >= index else None,
                    input_video_contexts[index - 1] if len(input_video_contexts) >= index else None,
                )
                for index in range(1, len(input_videos) + 1)
            ]
        else:
            source_items = [(
                1,
                input_videos[0],
                input_video_titles[0] if input_video_titles else None,
                input_video_contexts[0] if input_video_contexts else None,
            )]
        if not process_all_clips and len(input_videos) > 1:
            logging.info(f"Task {task_id}: got {len(input_videos)} source clips, processing first clip only")

        subtitles_enabled = False
        ass_path = None
        target_account_ids = [] if task.type == "local_upload" else _get_target_account_ids(db, user.id)
        if task.type in READY_TO_PUBLISH_VIDEO_TASK_TYPES:
            if not target_account_ids:
                raise Exception(
                    "No PostMyPost accounts configured/enabled for this user. "
                    "Enable channels in UI or set POSTMYPOST_CHANNEL_IDS."
                )
        elif task.type in AVATAR_TASK_TYPES:
            target_account_ids = []
        if task.type in {"instagram", "youtube"} and not target_account_ids and not process_all_clips:
            raise Exception(
                "No PostMyPost accounts configured/enabled for this user. "
                "Enable channels in UI or set POSTMYPOST_CHANNEL_IDS."
            )

        if task.type not in AVATAR_TASK_TYPES:
            if not target_account_ids and task.target_account_id:
                target_account_ids = [int(task.target_account_id)]
            elif task.target_account_id and int(task.target_account_id) not in target_account_ids:
                target_account_ids = [int(task.target_account_id)] + target_account_ids
        target_account_ids = list(dict.fromkeys(target_account_ids))
        if target_account_ids and task.type != "local_upload":
            original_target_account_ids = target_account_ids
            connected_target_account_ids = _get_connected_postmypost_account_ids(target_account_ids)
            if connected_target_account_ids != target_account_ids:
                logging.warning(
                    "Task %s: filtered PostMyPost target accounts from %s to %s",
                    task_id,
                    target_account_ids,
                    connected_target_account_ids,
                )
            target_account_ids = connected_target_account_ids
            if original_target_account_ids and not target_account_ids:
                raise Exception(
                    "No connected PostMyPost accounts found. "
                    "Reconnect channels in PostMyPost or enable connected channels in Turan."
                )

        account_platform_map = _get_account_platform_map(target_account_ids)
        if task.type in AVATAR_TASK_TYPES and task.type not in INSTAGRAM_POST_FIVE_SECOND_TASK_TYPES:
            logging.info("Task %s: avatar skips PostMyPost publication and account fan-out", task_id)

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
        output_group_keys: list[str | int | None] = []
        output_account_ids: list[int | None] = []
        if target_account_ids:
            for _clip_index, _video_path, _clip_title, _clip_context in source_items:
                for account_id in target_account_ids:
                    output_platforms.append(_normalize_platform_code(account_platform_map.get(account_id, "universal")))
                    output_group_keys.append(_clip_index)
                    output_account_ids.append(account_id)
        else:
            for _clip_index, _video_path, _clip_title, _clip_context in source_items:
                output_platforms.append(_normalize_platform_code(task.type))
                output_group_keys.append(_clip_index)
                output_account_ids.append(None)
        publication_lane = "vizard" if task.vizard_project_id else "instant"
        publish_immediately_when_available = _should_publish_immediately(task)
        publish_times = _plan_publish_times_for_outputs(
            db=db,
            user=user,
            output_platforms=output_platforms,
            manual_publish_at=None if process_all_clips or publish_immediately_when_available else task.publish_at,
            output_group_keys=output_group_keys,
            output_account_ids=output_account_ids,
            publication_lane=publication_lane,
            publish_immediately_when_slot_available=publish_immediately_when_available,
        )
        should_sync_outputs = bool(target_account_ids) or task.type in READY_TO_PUBLISH_VIDEO_TASK_TYPES
        base_source = _get_base_source_label(task.source_url)
        if should_sync_outputs and output_platforms:
            current_meta = dict(task.script_meta or {})
            batch_meta = dict(current_meta.get("publication_batch_report") or {})
            batch_meta.update(
                {
                    "batch_id": batch_meta.get("batch_id") or f"task-{task.id}-{uuid.uuid4().hex[:8]}",
                    "expected_clips": len(source_items),
                    "expected_publications": len(output_platforms),
                    "expected_accounts": len(target_account_ids),
                    "source_label": base_source,
                    "started_at": batch_meta.get("started_at") or datetime.datetime.utcnow().isoformat(),
                }
            )
            current_meta["publication_batch_report"] = batch_meta
            task.script_meta = current_meta
            db.commit()
        rendered_outputs: List[dict] = []
        vertical_thumbnail_intro_meta: List[dict] = []
        publish_index = 0
        per_output_publication_enabled = bool(process_all_clips and should_sync_outputs)
        synced_output_task_ids: set[int] = set()

        def _sync_rendered_output_now(rendered_output: dict) -> None:
            if not per_output_publication_enabled:
                return
            output_task = _upsert_processed_task(
                db=db,
                base_task=task,
                output_path=rendered_output["output_path"],
                source_label=rendered_output["source_label"],
                source_title=rendered_output["source_title"],
                publish_at=rendered_output["publish_at"],
                target_account_id=rendered_output["target_account_id"],
                target_platform=rendered_output["target_platform"],
                should_sync=True,
            )
            if output_task.id in synced_output_task_ids:
                return
            if (
                output_task.postmypost_id
                or output_task.postmypost_file_id
                or output_task.publishing_status in {"published", "in_progress"}
            ):
                logging.info(
                    "Task %s: rendered output task %s already has PostMyPost state, skipping duplicate enqueue",
                    task_id,
                    output_task.id,
                )
                return
            synced_output_task_ids.add(output_task.id)
            logging.info(
                "Task %s: enqueue immediate sync for rendered output task=%s account=%s publish_at=%s",
                task_id,
                output_task.id,
                rendered_output["target_account_id"],
                rendered_output["publish_at"],
            )
            update_task_status_message(
                db,
                task,
                stage="Публикация",
                detail=(
                    f"Клип {rendered_output.get('clip_index') or '-'} готов для "
                    f"{rendered_output.get('target_platform') or 'платформы'}. Передаю в PostMyPost."
                ),
            )
            celery_app.send_task("sync_publication_task", args=[output_task.id])

        for clip_index, video_path, clip_title, clip_context in source_items:
            if not video_path:
                raise Exception("Downloaded video path is empty")
            needs_youtube_title = (
                task.type == "youtube"
                or any(
                    _normalize_platform_code(account_platform_map.get(account_id, "universal")) == "youtube"
                    for account_id in target_account_ids
                )
            )
            youtube_publication_title = (
                _generate_youtube_title_from_context(task_id, clip_context, clip_title)
                if needs_youtube_title
                else None
            )
            should_apply_vertical_cover = bool(task.vizard_project_id) or task.type in {"instagram", "youtube"}
            if should_apply_vertical_cover:
                vertical_context = (
                    task.script_text
                    or task.factual_outline
                    or clip_context
                    or task.source_title
                    or clip_title
                    or ""
                )
                video_path, vertical_meta = _apply_vertical_thumbnail_intro(
                    source_video_path=video_path,
                    clip_title=clip_title,
                    context_text=vertical_context,
                    clip_index=clip_index,
                )
                vertical_thumbnail_intro_meta.append({"clip_index": clip_index, **vertical_meta})

            video_root, _ = os.path.splitext(video_path)
            clip_used_ending_ids_by_platform: dict[str, set[int]] = {}

            if target_account_ids:
                for account_id in target_account_ids:
                    slot_idx = account_variant_index.get(account_id, 1)
                    platform_code = account_platform_map.get(account_id, "universal")
                    output_source_title = (
                        youtube_publication_title
                        if _normalize_platform_code(platform_code) == "youtube" or task.type == "youtube"
                        else clip_title
                    )
                    account_output = f"{video_root}_final_s{slot_idx}_a{account_id}.mp4"

                    if task.type in READY_TO_PUBLISH_VIDEO_TASK_TYPES:
                        logging.info(
                            "Task %s: clip=%s account=%s platform=%s slot=%s using ready-to-publish output (no extra plate/CTA overlay)",
                            task_id,
                            clip_index,
                            account_id,
                            platform_code,
                            slot_idx,
                        )
                        shutil.copy2(video_path, account_output)
                        publish_at = publish_times[publish_index] if len(publish_times) > publish_index else None
                        publish_index += 1
                        rendered_output = {
                            "output_path": account_output,
                            "publish_at": publish_at,
                            "target_account_id": account_id,
                            "target_platform": platform_code,
                            "source_title": output_source_title,
                            "source_label": _build_source_label(
                                base_source,
                                clip_index=clip_index if process_all_clips else None,
                                slot_index=slot_idx,
                                account_id=account_id,
                            ),
                            "clip_index": clip_index,
                        }
                        rendered_outputs.append(rendered_output)
                        _sync_rendered_output_now(rendered_output)
                        continue

                    if task.type in AVATAR_TASK_TYPES:
                        logging.info(
                            "Task %s: clip=%s account=%s platform=%s slot=%s using avatar-only output (no plate/CTA overlay)",
                            task_id,
                            clip_index,
                            account_id,
                            platform_code,
                            slot_idx,
                        )
                        shutil.copy2(video_path, account_output)
                        publish_at = publish_times[publish_index] if len(publish_times) > publish_index else None
                        publish_index += 1
                        rendered_output = {
                            "output_path": account_output,
                            "publish_at": publish_at,
                            "target_account_id": account_id,
                            "target_platform": platform_code,
                            "source_title": output_source_title,
                            "source_label": _build_source_label(
                                base_source,
                                clip_index=clip_index if process_all_clips else None,
                                slot_index=slot_idx,
                                account_id=account_id,
                            ),
                            "clip_index": clip_index,
                        }
                        rendered_outputs.append(rendered_output)
                        _sync_rendered_output_now(rendered_output)
                        continue

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
                        (
                            "Task %s: clip=%s account=%s platform=%s slot=%s "
                            "plate_path=%s plate_start_percent=%s ending_id=%s ending_path=%s"
                        ),
                        task_id,
                        clip_index,
                        account_id,
                        platform_code,
                        slot_idx,
                        plate_path,
                        plate_start_percent,
                        getattr(ending, "id", None),
                        ending_path,
                    )
                    if not plate_path:
                        logging.warning(
                            "Task %s: plate is not configured/resolved for account=%s platform=%s. "
                            "Final output will not contain UI plate overlay.",
                            task_id,
                            account_id,
                            platform_code,
                        )
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
                    rendered_output = {
                        "output_path": account_output,
                        "publish_at": publish_at,
                        "target_account_id": account_id,
                        "target_platform": platform_code,
                        "source_title": output_source_title,
                        "source_label": _build_source_label(
                            base_source,
                            clip_index=clip_index if process_all_clips else None,
                            slot_index=slot_idx,
                            account_id=account_id,
                        ),
                        "clip_index": clip_index,
                    }
                    rendered_outputs.append(rendered_output)
                    _sync_rendered_output_now(rendered_output)
            else:
                base_output = f"{video_root}_final.mp4"
                if task.type in READY_TO_PUBLISH_VIDEO_TASK_TYPES:
                    shutil.copy2(video_path, base_output)
                    publish_at = publish_times[publish_index] if len(publish_times) > publish_index else None
                    publish_index += 1
                    rendered_outputs.append(
                        {
                            "output_path": base_output,
                            "publish_at": publish_at,
                            "target_account_id": None,
                            "target_platform": "instagram",
                            "source_title": clip_title,
                            "source_label": _build_source_label(
                                base_source,
                                clip_index=clip_index if process_all_clips else None,
                            ),
                        }
                    )
                    continue
                if task.type in AVATAR_TASK_TYPES:
                    shutil.copy2(video_path, base_output)
                    rendered_outputs.append(
                        {
                            "output_path": base_output,
                            "publish_at": None,
                            "target_account_id": None,
                            "target_platform": "instagram" if task.type in {"avatar_instagram", *INSTAGRAM_POST_FIVE_SECOND_TASK_TYPES} else "youtube",
                            "source_title": clip_title,
                            "source_label": _build_source_label(
                                base_source,
                                clip_index=clip_index if process_all_clips else None,
                            ),
                        }
                    )
                    continue
                plate_path, plate_start_percent = _get_channel_plate_config(db, user, None)
                logging.info(
                    "Task %s: clip=%s account=%s platform=%s plate_path=%s plate_start_percent=%s",
                    task_id,
                    clip_index,
                    None,
                    _normalize_platform_code(task.type),
                    plate_path,
                    plate_start_percent,
                )
                if not plate_path:
                    logging.warning(
                        "Task %s: plate is not configured/resolved for non-account output. "
                        "Final output will not contain UI plate overlay.",
                        task_id,
                    )
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
                        "source_title": youtube_publication_title if task.type == "youtube" else clip_title,
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
        if vertical_thumbnail_intro_meta:
            current_meta = dict(task.script_meta or {})
            current_meta["vertical_thumbnail_intro"] = vertical_thumbnail_intro_meta
            task.script_meta = current_meta
        if task.type in AVATAR_TASK_TYPES and task.type not in INSTAGRAM_POST_FIVE_SECOND_TASK_TYPES:
            current_meta = dict(task.script_meta or {})
            upload_paths = _collect_yandex_disk_upload_paths(task, rendered_outputs)
            current_meta["yandex_disk_uploads"] = []
            if yandex_disk.is_configured and upload_paths:
                current_meta["yandex_disk_upload_status"] = "pending"
                current_meta["yandex_disk_upload_paths"] = upload_paths
                current_meta.pop("yandex_disk_upload_error", None)
            elif not yandex_disk.is_configured:
                current_meta["yandex_disk_upload_status"] = "skipped"
                current_meta["yandex_disk_upload_error"] = "YANDEX_DISK_TOKEN is not configured for avatar upload"
            else:
                current_meta["yandex_disk_upload_status"] = "skipped"
                current_meta["yandex_disk_upload_error"] = "No local files available for Yandex.Disk upload"
            task.script_meta = current_meta
        db.commit()
        db.refresh(task)
        if task.type in AVATAR_TASK_TYPES and task.type not in INSTAGRAM_POST_FIVE_SECOND_TASK_TYPES:
            current_meta = dict(task.script_meta or {})
            upload_paths = list(current_meta.get("yandex_disk_upload_paths") or [])
            if current_meta.get("yandex_disk_upload_status") == "pending" and upload_paths:
                logging.info("Task %s: enqueue upload_yandex_disk_task for %s file(s)", task.id, len(upload_paths))
                celery_app.send_task("upload_yandex_disk_task", args=[task.id, upload_paths])
                current_meta["yandex_disk_upload_status"] = "queued"
                current_meta["yandex_disk_upload_queued_at"] = datetime.datetime.utcnow().isoformat()
                task.script_meta = current_meta
                db.commit()
        if task.type in SHORT_AVATAR_TASK_TYPES and task.output_path:
            if task.type == "avatar_instagram":
                label = "Reels Avatar"
            elif task.type in INSTAGRAM_POST_FIVE_SECOND_TASK_TYPES:
                label = "Instagram Post 5 секунд"
            elif task.type == "avatar_shorts":
                label = "Shorts Avatar"
            else:
                label = "Vertical Avatar"
            update_task_status_message(
                db,
                task,
                stage="Telegram",
                detail=f"Отправляю финальный {label} в Telegram.",
            )
            telegram_caption = f"✅ Финальный {label} готов.\n{build_task_context_text(task)}"
            if task.type in INSTAGRAM_POST_FIVE_SECOND_TASK_TYPES:
                try:
                    post_description = (
                        ((task.script_meta or {}).get("instagram_post_5s") or {}).get("rewritten_description")
                        or ""
                    ).strip()
                except Exception:
                    post_description = ""
                if post_description:
                    telegram_caption = f"{telegram_caption}\n\nОписание:\n{post_description[:700].strip()}"
            send_avatar_video_to_telegram(
                task,
                task.output_path,
                caption=telegram_caption,
            )
        if task.vizard_project_id and not should_sync_outputs:
            update_task_status_message(
                db,
                task,
                stage="Telegram",
                detail=f"Отправляю готовые Vizard-клипы в Telegram: {len(rendered_outputs)}.",
            )
            for output_index, rendered_output in enumerate(rendered_outputs, start=1):
                output_path = (rendered_output.get("output_path") or "").strip()
                if not output_path:
                    continue
                send_avatar_video_to_telegram(
                    task,
                    output_path,
                    caption=(
                        f"✅ Vizard-клип {output_index}/{len(rendered_outputs)} готов.\n"
                        f"{build_task_context_text(task)}"
                    ),
                )
        if should_sync_outputs and not per_output_publication_enabled:
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

        if should_sync_outputs and per_output_publication_enabled:
            update_task_status_message(
                db,
                task,
                stage="Готово",
                detail=f"Подготовлено роликов: {len(rendered_outputs)}. Каждый готовый ролик уже передан в очередь публикации.",
                ok=True,
            )

        if should_sync_outputs and not per_output_publication_enabled:
            logging.info(
                "Task %s: enqueue sync_publication_task for primary output account=%s publish_at=%s",
                task.id,
                primary_output["target_account_id"],
                primary_output["publish_at"],
            )
            force_now = bool(publish_immediately_when_available and primary_output["publish_at"] is None)
            celery_app.send_task("sync_publication_task", args=[task.id], kwargs={"force_now": force_now})

        # Avatar tasks are not published through PostMyPost; files are saved to Yandex.Disk.

        if not per_output_publication_enabled:
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
                    force_now = bool(publish_immediately_when_available and derived_output["publish_at"] is None)
                    celery_app.send_task("sync_publication_task", args=[derived_task.id], kwargs={"force_now": force_now})

    except Exception as e:
        logging.exception(f"Task {task_id} failed: {e}")
        try:
            db.rollback()
        except Exception as rollback_error:
            logging.warning("Task %s: failed to rollback aborted transaction: %s", task_id, rollback_error)
        if _is_deadlock_error(e):
            logging.warning("Task %s: database deadlock detected; retrying after a short delay", task_id)
            raise self.retry(exc=e, countdown=30)
        try:
            task = db.query(models.VideoTask).get(task_id)
            if task:
                task.status = "failed"
                db.commit()
                update_task_status_message(
                    db,
                    task,
                    stage="Ошибка",
                    detail=f"Обработка остановилась: {str(e)[:300]}",
                    failed=True,
                )
        except Exception as mark_error:
            logging.exception("Task %s: failed to mark task as failed after rollback: %s", task_id, mark_error)
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
