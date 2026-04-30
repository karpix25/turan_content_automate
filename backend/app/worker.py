import os
import asyncio
import random
import logging
import re
import shutil
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
from .telegram_progress import update_task_status_message, send_avatar_audio_to_telegram, send_thumbnail_to_telegram
from .integrations.elevenlabs_client import ElevenLabsClient
from .integrations.heygen_client import HeyGenClient
from .integrations.thumbnail_generator import ThumbnailGeneratorClient

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


ENABLE_REMOTION_STAGE = _is_truthy(os.getenv("ENABLE_REMOTION_STAGE", "0"))


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
        max_insert_seconds = float(os.getenv("AVATAR_INSERT_CLIP_MAX_SECONDS", "7"))
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

            thumbnail_outline = (
                task.factual_outline
                or task.source_title
                or f"YouTube-ролик с аватаром по теме бизнеса и финансов (HeyGen ID: {heygen_video_id})"
            ).strip()
            thumbnail_script = (
                task.script_text
                or task.source_title
                or f"Сделай триггерную обложку под видео с аватаром. Опора на тему: {thumbnail_outline}"
            ).strip()
            thumbnail_prompt, thumbnail_meta = _generate_avatar_thumbnail(
                factual_outline=thumbnail_outline,
                script_text=thumbnail_script,
                detail_text="Генерирую обложку YouTube по теме готового HeyGen-видео.",
            )

            if ENABLE_REMOTION_STAGE:
                update_task_status_message(db, task, stage="Монтаж", detail="Рендерю стильную графику через Remotion (AI)...")
                remotion_output = _run_remotion_pipeline(task_id, local_avatar_video, "")
                if remotion_output:
                    local_avatar_video = remotion_output
                    logging.info(f"Task {task_id}: Successfully replaced raw video with Remotion output.")
                else:
                    raise Exception(
                        "Remotion rendering failed for avatar_youtube task. "
                        "Raw HeyGen fallback is disabled by policy."
                    )
            else:
                update_task_status_message(
                    db,
                    task,
                    stage="Монтаж",
                    detail="Remotion временно отключен. Пропускаю графический рендер.",
                )
                logging.info(
                    "Task %s: Remotion stage skipped for avatar_youtube existing HeyGen flow (ENABLE_REMOTION_STAGE=0).",
                    task_id,
                )

            local_avatar_video, insert_meta = _apply_avatar_insert_montage(local_avatar_video)
            existing_meta = dict(task.script_meta or {})
            existing_meta["avatar_insert_montage"] = insert_meta
            existing_meta["thumbnail_prompt"] = thumbnail_prompt
            existing_meta["thumbnail"] = thumbnail_meta
            task.script_meta = existing_meta
            db.commit()

            input_videos.append(local_avatar_video)
            input_video_titles.append(task.source_title or f"Avatar Video {task_id}")

        elif task.type == "avatar_youtube":
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
            
            # rewrite with style
            update_task_status_message(
                db,
                task,
                stage="Сценарий",
                detail="Пишу сценарий в вашем стиле на 4-6 минут.",
            )
            style_profile = user.author_style_profile
            min_words = AVATAR_SCRIPT_MIN_MINUTES * AVATAR_SCRIPT_WPM
            max_words = AVATAR_SCRIPT_MAX_MINUTES * AVATAR_SCRIPT_WPM

            structured_source = (
                "FACTUAL OUTLINE (ключевые смыслы):\n"
                f"{outline}\n\n"
                "RAW TRANSCRIPT (оригинальный поток речи, может быть не по порядку):\n"
                f"{transcript}"
            )
            script = llm.rewrite_to_script(
                structured_source,
                style_profile,
                min_minutes=AVATAR_SCRIPT_MIN_MINUTES,
                max_minutes=AVATAR_SCRIPT_MAX_MINUTES,
                words_per_minute=AVATAR_SCRIPT_WPM,
            )
            if not script:
                raise Exception("Failed to generate styled script for Avatar task")

            word_count = llm.estimate_word_count(script)
            if word_count < min_words or word_count > max_words:
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

            # humanize pass (remove AI-like patterns and strengthen opening)
            update_task_status_message(
                db,
                task,
                stage="Сценарий",
                detail="Очеловечиваю текст и усиливаю начало.",
            )
            humanized_script = llm.humanize_russian_text(
                script=script,
                style_profile=style_profile,
                min_words=min_words,
                max_words=max_words,
            )
            if humanized_script:
                script = humanized_script
                word_count = llm.estimate_word_count(script)

            # final length guard after humanization
            if word_count < min_words or word_count > max_words:
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

            # faithfulness check
            update_task_status_message(db, task, stage="Сценарий", detail="Проверяю сценарий на соответствие фактам.")
            validation = llm.verify_faithfulness(outline, script)
            estimated_minutes = _estimate_script_minutes(script, AVATAR_SCRIPT_WPM)
            thumbnail_prompt, thumbnail_meta = _generate_avatar_thumbnail(
                factual_outline=outline,
                script_text=script,
            )
            task.script_text = script
            task.script_meta = {
                **(validation or {}),
                "target_minutes": [AVATAR_SCRIPT_MIN_MINUTES, AVATAR_SCRIPT_MAX_MINUTES],
                "words_per_minute_assumption": AVATAR_SCRIPT_WPM,
                "word_count": word_count,
                "estimated_minutes": estimated_minutes,
                "thumbnail_prompt": thumbnail_prompt,
                "thumbnail": thumbnail_meta,
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
            
            # Determine voice ID (User setting -> ENV -> Default Brian)
            voice_id = (user.elevenlabs_voice_id or os.getenv("ELEVENLABS_VOICE_ID", "nPczCjzB2oQXqZ4mU67e")).strip()
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
                
            # --- Remotion AI Rendering ---
            if ENABLE_REMOTION_STAGE:
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
            else:
                update_task_status_message(
                    db,
                    task,
                    stage="Монтаж",
                    detail="Remotion временно отключен. Пропускаю графический рендер.",
                )
                logging.info(
                    "Task %s: Remotion stage skipped for avatar_youtube full flow (ENABLE_REMOTION_STAGE=0).",
                    task_id,
                )

            local_avatar_video, insert_meta = _apply_avatar_insert_montage(local_avatar_video)
            current_meta = dict(task.script_meta or {})
            current_meta["avatar_insert_montage"] = insert_meta
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
        if task.type == "avatar_youtube":
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
        if task.type == "avatar_youtube":
            youtube_only_accounts = [
                account_id
                for account_id in target_account_ids
                if _normalize_platform_code(account_platform_map.get(account_id)) == "youtube"
            ]
            if not youtube_only_accounts:
                raise Exception(
                    "No YouTube target accounts configured/enabled for avatar_youtube task. "
                    "Enable at least one YouTube channel in PostMyPost settings."
                )
            target_account_ids = youtube_only_accounts
            logging.info(
                "Task %s: avatar_youtube restricted publication targets to YouTube accounts: %s",
                task_id,
                target_account_ids,
            )

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
                    account_output = f"{video_root}_final_s{slot_idx}_a{account_id}.mp4"

                    if task.type == "avatar_youtube":
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

        # avatar_youtube публикуется через PostMyPost; Telegram delivery для финального видео отключен.

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
