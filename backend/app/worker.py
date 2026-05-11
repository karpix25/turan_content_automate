import os
import asyncio
import random
import logging
import re
import shutil
import datetime
import time
import math
from typing import List
from urllib.parse import urlparse, parse_qs
from celery import Celery
from .integrations.vizard import VizardClient
from .integrations.scrape_creators import ScrapeCreatorsClient
from .integrations.llm import LLMClient
from .integrations.rapidapi_youtube import RapidAPIYoutubeClient
from .integrations.downloader import Downloader
from .integrations.postmypost import PostMyPostClient
from .processor import VideoProcessor
from .database import SessionLocal, init_database
from .publish_planner import plan_next_publish_times
from .telegram_progress import (
    update_task_status_message,
    send_avatar_audio_to_telegram,
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
)
from .utils.media_utils import (
    _estimate_script_minutes,
    _resolve_local_input_video_path,
    _resolve_media_file_path,
)
from .utils.voice_calibration import (
    count_script_chars,
    get_cached_voice_speed,
    get_or_calibrate_voice_speed,
)
from . import models
from dotenv import load_dotenv

load_dotenv()
init_database()

celery_app = Celery('tasks', broker=(os.getenv("REDIS_URL") or "redis://localhost:6379/0").strip())

# Initialize clients
vizard = VizardClient(api_key=(os.getenv("VIZARD_API_KEY") or "").strip())
pmp_client = PostMyPostClient(api_key=(os.getenv("POSTMYPOST_API_KEY") or "").strip())
scraper = ScrapeCreatorsClient(api_key=(os.getenv("SCRAPE_CREATORS_API_KEY") or "").strip())
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
rapidapi_yt = RapidAPIYoutubeClient(
    api_key=os.getenv("RAPIDAPI_KEY", ""),
    host=os.getenv("YOUTUBE_DOWNLOAD_RAPIDAPI_HOST", "youtube-mp4-mp3-downloader.p.rapidapi.com"),
    video_format=os.getenv("YOUTUBE_DOWNLOAD_FORMAT", "720"),
    audio_quality=os.getenv("YOUTUBE_DOWNLOAD_AUDIO_QUALITY", "128"),
    poll_interval_seconds=float(os.getenv("YOUTUBE_DOWNLOAD_POLL_INTERVAL_SECONDS", "2")),
    timeout_seconds=float(os.getenv("YOUTUBE_DOWNLOAD_TIMEOUT_SECONDS", "90")),
)
downloader = Downloader(output_dir=(os.getenv("OUTPUT_DIR") or "./output").strip())
processor = VideoProcessor()
SHORT_AVATAR_TASK_TYPES = {"avatar_instagram", "avatar_shorts"}
AVATAR_TASK_TYPES = {"avatar_youtube", *SHORT_AVATAR_TASK_TYPES}
AVATAR_SCRIPT_MIN_MINUTES = int(os.getenv("AVATAR_SCRIPT_MIN_MINUTES", "4"))
AVATAR_SCRIPT_MAX_MINUTES = int(os.getenv("AVATAR_SCRIPT_MAX_MINUTES", "6"))
AVATAR_SCRIPT_WPM = int(os.getenv("AVATAR_SCRIPT_WORDS_PER_MINUTE", "110"))
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
    0.1,
    float(os.getenv("VERTICAL_THUMBNAIL_INTRO_SECONDS", "10")),
)
REELS_VERTICAL_COVER_SECONDS = max(
    0.01,
    min(0.10, float(os.getenv("REELS_VERTICAL_COVER_SECONDS", "0.10"))),
)


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


def _run_remotion_pipeline(task_id: int, input_video: str, script: str) -> str | None:
    import subprocess
    import json
    logging.info(f"Task {task_id}: Starting Remotion pipeline on {input_video}")
    montage_script = "/app/hf-montage-test/tools/smart_montage_pipeline.py"
    remotion_dir = "/app/remotion-auto"
    scene_plan_index = "/app/hf-montage-test/index.html"
    
    out_dir = os.getenv("OUTPUT_DIR", "./output").strip()
    out_plan = os.path.join(out_dir, f"scene-plan_{task_id}.json")
    out_words = os.path.join(out_dir, f"scene-word-cues_{task_id}.json")
    
    # 1. Run AI Scene Planner
    cmd_plan = [
        "python3", montage_script,
        "--video", input_video,
        "--index", scene_plan_index,
        "--out-plan", out_plan,
        "--deepgram-intelligence"
    ]
    logging.info(f"Task {task_id}: Running scene planner: {' '.join(cmd_plan)}")
    res = subprocess.run(cmd_plan, capture_output=True, text=True)
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
            
    # 2. Run Remotion Render
    final_output = os.path.join(out_dir, f"remotion_{task_id}.mp4")
    cmd_render = [
        "npm", "run", "render:auto", "--",
        "--video", input_video,
        "--scene-plan", out_plan,
        "--word-cues", out_words,
        "--out", final_output
    ]
    logging.info(f"Task {task_id}: Running Remotion: {' '.join(cmd_render)}")
    res_render = subprocess.run(cmd_render, cwd=remotion_dir, capture_output=True, text=True)
    if res_render.returncode != 0:
        logging.error(f"Task {task_id}: Remotion failed. STDOUT: {res_render.stdout}\nSTDERR: {res_render.stderr}")
        return None
        
    if os.path.exists(final_output):
        return final_output
    return None


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
        max_insert_seconds = float(os.getenv("AVATAR_INSERT_CLIP_MAX_SECONDS", "0"))
        inserted_path, insert_meta = processor.apply_avatar_insert_clips(
            input_path=base_video_path,
            insert_paths=insert_paths,
            start_percent=start_percent,
            end_percent=end_percent,
            clips_count=clips_count,
            output_path=montage_output,
            seed=task_id,
            max_insert_seconds=max_insert_seconds,
        )
        if inserted_path:
            if base_video_path != inserted_path and os.path.isfile(base_video_path):
                try:
                    os.remove(base_video_path)
                except OSError:
                    logging.warning("Failed to remove intermediate avatar file after inserts: %s", base_video_path)
            return inserted_path, insert_meta or {"status": "applied"}
        return base_video_path, insert_meta or {"status": "failed", "reason": "unknown"}

    def _create_short_avatar_broll(base_video_path: str, script_text: str, source_video_path: str | None) -> tuple[str, dict]:
        coverage_percent = max(0, min(100, int(getattr(user, "reels_broll_coverage_percent", 50) or 0)))
        start_percent = 0
        end_percent = 100
        broll_dir = (
            getattr(user, "reels_broll_yandex_dir", None)
            or os.getenv("YANDEX_DISK_BROLL_DIR")
            or "disk:/Broll"
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
            remote_files = yandex_disk.list_video_files(broll_dir)
        except Exception as list_error:
            logging.warning("Task %s: failed to list Yandex.Disk b-roll folder: %s", task_id, list_error)
            meta["status"] = "failed"
            meta["reason"] = "yandex_list_failed"
            meta["error"] = str(list_error)
            return base_video_path, meta

        if not remote_files:
            meta["reason"] = "no_video_files_in_yandex_dir"
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
        thumbnail_prompt = None
        thumbnail_meta: dict = {
            "status": "skipped",
            "reason": "thumbnail_prompt_empty",
            "output_path": None,
            "used_reference_count": 0,
            "face_path": user.thumbnail_face_path,
        }
        try:
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
                if review.get("prompt") != thumbnail_prompt or review.get("status") not in {"approved", "rejected"}:
                    review = {
                        "status": "pending",
                        "prompt": thumbnail_prompt,
                        "created_at": datetime.datetime.utcnow().isoformat(),
                    }
                    meta["thumbnail_prompt_review"] = review
                    task.script_meta = meta
                    db.commit()
                    send_thumbnail_prompt_review_to_telegram(task, thumbnail_prompt)

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
                        thumbnail_prompt = (review.get("approved_prompt") or thumbnail_prompt).strip()
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
                .filter(models.ThumbnailReference.user_id == user.id)
                .order_by(models.ThumbnailReference.created_at.desc(), models.ThumbnailReference.id.desc())
                .all()
            )
            reference_paths = [item.file_path for item in references if item and item.file_path]
            thumbnail_output_path = os.path.join(
                os.getenv("OUTPUT_DIR", "./output").strip(),
                f"thumbnail_{task_id}.png",
            )
            update_task_status_message(
                db,
                task,
                stage="Обложка",
                detail=detail_text,
            )
            generated_thumbnail = thumbnail_generator.generate_thumbnail(
                prompt=thumbnail_prompt,
                face_path=user.thumbnail_face_path,
                reference_paths=reference_paths,
                output_path=thumbnail_output_path,
            )
            if generated_thumbnail:
                thumbnail_meta = {
                    "status": "generated",
                    "reason": None,
                    "output_path": generated_thumbnail,
                    "used_reference_count": len(reference_paths[:5]),
                    "face_path": user.thumbnail_face_path,
                }
                update_task_status_message(
                    db,
                    task,
                    stage="Telegram",
                    detail="Отправляю готовую обложку в Telegram.",
                )
                send_thumbnail_to_telegram(task, generated_thumbnail)
            else:
                thumbnail_meta = {
                    "status": "failed",
                    "reason": "generator_failed_or_unconfigured",
                    "output_path": None,
                    "used_reference_count": len(reference_paths[:5]),
                    "face_path": user.thumbnail_face_path,
                }
        return thumbnail_prompt, thumbnail_meta

    def _apply_vertical_thumbnail_intro(
        *,
        source_video_path: str,
        clip_title: str | None,
        clip_index: int,
    ) -> tuple[str, dict]:
        clean_title = (clip_title or "").strip()
        meta: dict = {
            "status": "skipped",
            "reason": None,
            "clip_title": clean_title,
            "prompt": None,
            "image_path": None,
            "intro_duration_seconds": VERTICAL_THUMBNAIL_INTRO_SECONDS,
            "used_reference_count": 0,
            "face_path": user.vertical_thumbnail_face_path,
        }
        if task.type in AVATAR_TASK_TYPES:
            meta["reason"] = "avatar_not_applicable"
            return source_video_path, meta
        if not clean_title:
            meta["reason"] = "clip_title_empty"
            return source_video_path, meta

        references = (
            db.query(models.ThumbnailReference)
            .filter(models.ThumbnailReference.user_id == user.id, models.ThumbnailReference.kind == "vertical")
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
            prompt = llm.generate_vertical_thumbnail_prompt(clean_title)
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
            reference_paths=reference_paths,
            output_path=image_output_path,
            aspect_ratio="9:16",
            max_style_references=int(os.getenv("VERTICAL_THUMBNAIL_MAX_STYLE_REFERENCES", "4")),
        )
        meta["prompt"] = prompt
        meta["used_reference_count"] = len(reference_paths[: int(os.getenv("VERTICAL_THUMBNAIL_MAX_STYLE_REFERENCES", "4"))])
        if not generated_image:
            meta["status"] = "failed"
            meta["reason"] = "generator_failed_or_unconfigured"
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

    def _apply_short_avatar_vertical_cover(source_video_path: str, script_text: str) -> tuple[str, dict]:
        meta: dict = {
            "status": "skipped",
            "reason": None,
            "prompt": None,
            "image_path": None,
            "intro_duration_seconds": REELS_VERTICAL_COVER_SECONDS,
            "used_reference_count": 0,
            "face_path": user.vertical_thumbnail_face_path,
        }
        if task.type not in SHORT_AVATAR_TASK_TYPES:
            meta["reason"] = "not_short_avatar"
            return source_video_path, meta

        references = (
            db.query(models.ThumbnailReference)
            .filter(models.ThumbnailReference.user_id == user.id, models.ThumbnailReference.kind == "vertical")
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

        output_dir = os.getenv("OUTPUT_DIR", "./output").strip()
        os.makedirs(output_dir, exist_ok=True)
        image_output_path = os.path.join(output_dir, f"reels_vertical_cover_{task_id}.png")
        max_refs = int(os.getenv("VERTICAL_THUMBNAIL_MAX_STYLE_REFERENCES", "4"))
        generated_image = thumbnail_generator.generate_thumbnail(
            prompt=prompt,
            face_path=user.vertical_thumbnail_face_path,
            reference_paths=reference_paths,
            output_path=image_output_path,
            aspect_ratio="9:16",
            max_style_references=max_refs,
        )
        meta["prompt"] = prompt
        meta["used_reference_count"] = len(reference_paths[:max_refs])
        if not generated_image:
            meta["status"] = "failed"
            meta["reason"] = "generator_failed_or_unconfigured"
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

        created_at = getattr(task, "created_at", None)
        if isinstance(created_at, datetime.datetime):
            date_folder = created_at.strftime("%d.%m.%Y")
        else:
            date_folder = datetime.datetime.utcnow().strftime("%d.%m.%Y")

        update_task_status_message(
            db,
            task,
            stage="Выгрузка",
            detail=f"Сохраняю видео и обложку в Яндекс.Диск (disk/Heygen/{date_folder}).",
        )
        target_root = (os.getenv("YANDEX_DISK_AVATAR_DIR") or "disk:/Heygen").strip()
        target_dir = f"{target_root.rstrip('/')}/{date_folder}"
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

        elif task.type == "avatar_youtube" and _extract_heygen_video_id(source_url_raw):
            heygen_video_id = _extract_heygen_video_id(source_url_raw)
            if not heygen_video_id:
                raise Exception("Invalid HeyGen video_id for avatar_youtube task")

            update_task_status_message(
                db,
                task,
                stage="HeyGen",
                detail=f"Получаю уже готовое видео HeyGen по id={heygen_video_id}.",
            )
            logging.info("Task %s: avatar_youtube using existing HeyGen video_id=%s", task_id, heygen_video_id)

            final_video_url = asyncio.run(heygen_client.poll_video_status(heygen_video_id))
            if not final_video_url:
                raise Exception(f"HeyGen video with id={heygen_video_id} is unavailable, failed, or timed out")

            update_task_status_message(db, task, stage="Монтаж", detail="Скачиваю готовое видео из HeyGen.")
            local_avatar_video = downloader.download_media(final_video_url, f"heygen_{task_id}")
            if not local_avatar_video:
                raise Exception("Failed to download existing HeyGen video")

            transcribed_text = ""
            inferred_outline = ""
            if ENABLE_HEYGEN_READY_TRANSCRIBE and deepgram_client.is_configured:
                update_task_status_message(
                    db,
                    task,
                    stage="Сценарий",
                    detail="Транскрибирую готовое видео через Deepgram для точного хука и темы обложки.",
                )
                try:
                    transcribed_text = (deepgram_client.transcribe_media_text(local_avatar_video) or "").strip()
                except Exception as transcribe_error:
                    logging.warning(
                        "Task %s: Deepgram transcription failed for existing HeyGen video: %s",
                        task_id,
                        transcribe_error,
                    )
                    transcribed_text = ""
                if transcribed_text:
                    try:
                        inferred_outline = (llm.generate_factual_outline(transcribed_text) or "").strip()
                    except Exception as outline_error:
                        logging.warning(
                            "Task %s: factual outline generation from Deepgram transcript failed: %s",
                            task_id,
                            outline_error,
                        )
                        inferred_outline = ""
                    if not (task.script_text or "").strip():
                        task.script_text = transcribed_text
                    if inferred_outline and not (task.factual_outline or "").strip():
                        task.factual_outline = inferred_outline
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
                detail_text="Генерирую обложку YouTube по теме готового HeyGen-видео.",
            )

            hook_text, trigger_title, cta_text, final_description_text = _build_avatar_description_text(
                script_text=thumbnail_script,
                factual_outline=thumbnail_outline,
                source_title=task.source_title,
                description_template=user.youtube_description_template,
            )
            description_txt_path = _write_avatar_description_file(task_id, final_description_text)

            update_task_status_message(db, task, stage="Монтаж", detail="Рендерю стильную графику через Remotion (AI)...")
            remotion_output = _run_remotion_pipeline(task_id, local_avatar_video, thumbnail_script)
            if remotion_output:
                local_avatar_video = remotion_output
                logging.info(f"Task {task_id}: Successfully replaced raw video with Remotion output.")
            else:
                raise Exception(
                    "Remotion rendering failed for avatar_youtube task. "
                    "Raw HeyGen fallback is disabled by policy."
                )

            local_avatar_video, insert_meta = _apply_avatar_insert_montage(local_avatar_video)
            existing_meta = dict(task.script_meta or {})
            existing_meta["avatar_insert_montage"] = insert_meta
            existing_meta["thumbnail_prompt"] = thumbnail_prompt
            existing_meta["thumbnail"] = thumbnail_meta
            existing_meta["youtube_description"] = {
                "hook_text": hook_text,
                "trigger_title": trigger_title,
                "cta_text": cta_text,
                "template": (user.youtube_description_template or "").strip(),
                "final_text": final_description_text,
                "txt_path": description_txt_path,
            }
            task.script_meta = existing_meta
            db.commit()

            input_videos.append(local_avatar_video)
            input_video_titles.append(task.source_title or f"Avatar Video {task_id}")

        elif task.type in AVATAR_TASK_TYPES:
            cleaned_reels_transcript = ""
            local_reel_source = None
            if task.type == "avatar_instagram":
                update_task_status_message(db, task, stage="Сценарий", detail="Получаю данные Instagram Reels.")
                t_data = scraper.get_instagram_details(source_url)
                caption = ((t_data or {}).get("caption") or "").strip()
                creator = ((t_data or {}).get("creator") or "").strip()
                view_count = (t_data or {}).get("view_count")
                download_url = _normalize_external_url(((t_data or {}).get("download_url") or "").strip())
                source_title = (task.source_title or "").strip()
                if not source_title:
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
                    raise Exception("Failed to retrieve usable text for Instagram Reel")
                raw_reels_transcript = "\n".join(
                    part for part in [
                        f"Transcript: {reel_transcript}" if reel_transcript else "",
                        f"Caption: {caption}" if caption else "",
                        f"Creator: @{creator}" if creator else "",
                        f"Views: {view_count}" if view_count else "",
                    ]
                    if part
                )
                update_task_status_message(db, task, stage="Сценарий", detail="Удаляю CTA и промо из Reels.")
                cleaned_reels_transcript = (
                    llm.remove_cta_from_transcript(raw_reels_transcript)
                    or _strip_cta_fallback(raw_reels_transcript)
                ).strip()
                if not cleaned_reels_transcript:
                    raise Exception("Failed to clean Instagram Reel transcript")
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
                raise Exception("Failed to generate factual outline for Avatar task")
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

            if task.type in SHORT_AVATAR_TASK_TYPES:
                original_char_count = count_script_chars(cleaned_reels_transcript)
                target_chars = max(80, int(round(original_char_count * 0.9)))
                min_chars = max(40, int(round(target_chars * 0.97)))
                max_chars = max(min_chars + 10, int(round(target_chars * 1.03)))
                update_task_status_message(
                    db,
                    task,
                    stage="Сценарий",
                    detail="Повторяю оригинальный короткий ролик на 10% короче и усиливаю хук.",
                )
                script = llm.rewrite_reels_avatar_script(
                    cleaned_transcript=cleaned_reels_transcript,
                    style_profile=style_profile,
                    target_chars=target_chars,
                    min_chars=min_chars,
                    max_chars=max_chars,
                )
                if not script:
                    raise Exception("Failed to generate short Avatar script")
                word_count = llm.estimate_word_count(script)
                char_count = count_script_chars(script)
                if char_count < min_chars or char_count > max_chars:
                    adjusted_script = llm.adjust_script_length_chars(
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
                    raise Exception("Failed to generate styled script for Avatar task")

                word_count = llm.estimate_word_count(script)
                char_count = count_script_chars(script)
                if target_chars and min_chars and max_chars and (char_count < min_chars or char_count > max_chars):
                    update_task_status_message(
                        db,
                        task,
                        stage="Сценарий",
                        detail=f"Подгоняю длину сценария под {target_duration_minutes} мин.",
                    )
                    adjusted_script = llm.adjust_script_length_chars(
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
                    adjusted_script = llm.adjust_script_length_chars(
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
                        "target_is_10_percent_shorter": True,
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

            update_task_status_message(db, task, stage="Telegram", detail="Отправляю готовое аудио в Telegram.")
            send_avatar_audio_to_telegram(task, audio_output_path, estimated_minutes=estimated_minutes)
            
            # --- HeyGen Video Generation ---
            avatar_id = (user.heygen_avatar_id or os.getenv("HEYGEN_AVATAR_ID", "788070966a344933a30c6a8581005a30")).strip()
            update_task_status_message(
                db,
                task,
                stage="HeyGen",
                detail=f"Отправляю аудио в HeyGen (Avatar: {avatar_id}).",
            )
            
            # 1. Upload audio to HeyGen assets
            audio_asset_id = asyncio.run(heygen_client.upload_asset(audio_output_path))
            if not audio_asset_id:
                raise Exception("Failed to upload audio to HeyGen assets")
                
            # 2. Generate video
            update_task_status_message(db, task, stage="HeyGen", detail="Генерирую видео с аватаром...")
            heygen_video_id = asyncio.run(heygen_client.generate_avatar_video(avatar_id, audio_asset_id))
            if not heygen_video_id:
                raise Exception("Failed to submit video generation to HeyGen")
                
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

            local_avatar_video, broll_meta = _create_short_avatar_broll(
                base_video_path=local_avatar_video,
                script_text=script,
                source_video_path=local_reel_source,
            )
            if task.type in SHORT_AVATAR_TASK_TYPES:
                current_meta = dict(task.script_meta or {})
                current_meta["broll"] = broll_meta
                task.script_meta = current_meta
                db.commit()
                
            # --- Remotion AI Rendering ---
            update_task_status_message(db, task, stage="Монтаж", detail="Рендерю стильную графику через Remotion (AI)...")
            remotion_output = _run_remotion_pipeline(task_id, local_avatar_video, script)
            if remotion_output:
                local_avatar_video = remotion_output
                logging.info(f"Task {task_id}: Successfully replaced raw video with Remotion output.")
            else:
                raise Exception(
                    "Remotion rendering failed for avatar_youtube task. "
                    "Raw HeyGen fallback is disabled by policy."
                )

            local_avatar_video, insert_meta = _apply_avatar_insert_montage(local_avatar_video)
            current_meta = dict(task.script_meta or {})
            current_meta["avatar_insert_montage"] = insert_meta
            task.script_meta = current_meta
            db.commit()

            if task.type in SHORT_AVATAR_TASK_TYPES:
                local_avatar_video, vertical_cover_meta = _apply_short_avatar_vertical_cover(local_avatar_video, script)
                current_meta = dict(task.script_meta or {})
                current_meta["short_vertical_cover"] = vertical_cover_meta
                task.script_meta = current_meta
                db.commit()
                
            # --- Final Post-Processing (Plates/Endings) ---
            # We treat this video as the 'source' for the final step
            input_videos.append(local_avatar_video)
            input_video_titles.append(task.source_title or f"Avatar Video {task_id}")
            # Continue to standard processing loop below


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
        if task.type in AVATAR_TASK_TYPES:
            # Avatar flow always has a single HeyGen source clip and must not fan out by clip.
            process_all_clips = False
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
        target_account_ids = [] if task.type == "local_upload" else _get_target_account_ids(db, user.id)
        if task.type in AVATAR_TASK_TYPES:
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

        account_platform_map = _get_account_platform_map(target_account_ids)
        if task.type in AVATAR_TASK_TYPES:
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
        vertical_thumbnail_intro_meta: List[dict] = []
        publish_index = 0

        for clip_index, video_path, clip_title in source_items:
            if not video_path:
                raise Exception("Downloaded video path is empty")
            if task.vizard_project_id:
                video_path, vertical_meta = _apply_vertical_thumbnail_intro(
                    source_video_path=video_path,
                    clip_title=clip_title,
                    clip_index=clip_index,
                )
                vertical_thumbnail_intro_meta.append({"clip_index": clip_index, **vertical_meta})

            video_root, _ = os.path.splitext(video_path)
            clip_used_ending_ids_by_platform: dict[str, set[int]] = {}

            if target_account_ids:
                for account_id in target_account_ids:
                    slot_idx = account_variant_index.get(account_id, 1)
                    platform_code = account_platform_map.get(account_id, "universal")
                    account_output = f"{video_root}_final_s{slot_idx}_a{account_id}.mp4"

                    if task.type in AVATAR_TASK_TYPES:
                        logging.info(
                            "Task %s: clip=%s account=%s platform=%s slot=%s using Remotion-only output (no plate/CTA overlay)",
                            task_id,
                            clip_index,
                            account_id,
                            platform_code,
                            slot_idx,
                        )
                        shutil.copy2(video_path, account_output)
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
                if task.type in AVATAR_TASK_TYPES:
                    shutil.copy2(video_path, base_output)
                    rendered_outputs.append(
                        {
                            "output_path": base_output,
                            "publish_at": None,
                            "target_account_id": None,
                            "target_platform": "instagram" if task.type == "avatar_instagram" else "youtube",
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
                        "source_title": clip_title,
                        "source_label": _build_source_label(
                            base_source,
                            clip_index=clip_index if process_all_clips else None,
                        ),
                    }
                )

        if not rendered_outputs:
            raise Exception("No rendered outputs were produced")

        yandex_uploads_meta: List[dict] = []
        yandex_upload_error: str | None = None
        try:
            yandex_uploads_meta = _upload_to_yandex_disk_if_needed(rendered_outputs)
        except Exception as upload_error:
            yandex_upload_error = str(upload_error).strip() or "unknown_error"
            logging.exception(
                "Task %s: Yandex.Disk upload failed, task will continue without remote upload: %s",
                task_id,
                yandex_upload_error,
            )
            update_task_status_message(
                db,
                task,
                stage="Выгрузка",
                detail=f"Не удалось выгрузить в Яндекс.Диск: {yandex_upload_error[:220]}. Продолжаю без выгрузки.",
            )

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
        if task.type in AVATAR_TASK_TYPES:
            current_meta = dict(task.script_meta or {})
            current_meta["yandex_disk_uploads"] = yandex_uploads_meta
            if yandex_upload_error:
                current_meta["yandex_disk_upload_error"] = yandex_upload_error
            task.script_meta = current_meta
        db.commit()
        db.refresh(task)
        if task.type in AVATAR_TASK_TYPES:
            send_yandex_disk_links_to_telegram(task, yandex_uploads_meta)
        if task.type in SHORT_AVATAR_TASK_TYPES and task.output_path:
            label = "Reels Avatar" if task.type == "avatar_instagram" else "Shorts Avatar"
            update_task_status_message(
                db,
                task,
                stage="Telegram",
                detail=f"Отправляю финальный {label} в Telegram.",
            )
            send_avatar_video_to_telegram(
                task,
                task.output_path,
                caption=f"✅ Финальный {label} готов.\nВидео #{getattr(task, 'id', '-')}",
            )
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

        # avatar_youtube не публикуется через PostMyPost; файл сохраняется в Яндекс.Диск.

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
