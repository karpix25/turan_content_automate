import os
import asyncio
import random
import logging
from typing import List
from celery import Celery
from .integrations.vizard import VizardClient
from .integrations.scrape_creators import ScrapeCreatorsClient
from .integrations.downloader import Downloader
from .processor import VideoProcessor
from .database import SessionLocal, init_database
from . import models
from dotenv import load_dotenv

load_dotenv()
init_database()

celery_app = Celery('tasks', broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"))

# Initialize clients
vizard = VizardClient(api_key=os.getenv("VIZARD_API_KEY", ""))
scraper = ScrapeCreatorsClient(api_key=os.getenv("SCRAPE_CREATORS_API_KEY", ""))
downloader = Downloader(output_dir=os.getenv("OUTPUT_DIR", "./output"))
processor = VideoProcessor(
    model_size=os.getenv("WHISPER_MODEL", "large-v3"),
    device=os.getenv("WHISPER_DEVICE", "cpu"),
    compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "int8")
)

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
    return _parse_env_account_ids(os.getenv("POSTMYPOST_CHANNEL_IDS", ""))

def _upsert_variant_task(
    db,
    base_task: models.VideoTask,
    output_path: str,
    variant_index: int,
    publish_at,
    target_account_id: int | None,
) -> models.VideoTask:
    existing = db.query(models.VideoTask).filter(
        models.VideoTask.user_id == base_task.user_id,
        models.VideoTask.output_path == output_path,
        models.VideoTask.id != base_task.id,
    ).first()

    publishing_status = "scheduled" if publish_at else "not_published"

    if existing:
        existing.type = base_task.type
        existing.status = "completed"
        existing.vizard_project_id = base_task.vizard_project_id
        existing.publish_at = publish_at
        existing.target_account_id = target_account_id
        existing.publishing_status = publishing_status
        db.commit()
        db.refresh(existing)
        return existing

    variant_task = models.VideoTask(
        user_id=base_task.user_id,
        source_url=f"{base_task.source_url} [variant {variant_index}]",
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

    try:
        input_videos = []

        if task.type == "vizard":
            # 1. Send to Vizard
            p_id = asyncio.run(vizard.create_project(task.source_url))
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
            details = scraper.get_instagram_details(task.source_url)
            if details and details.get("download_url"):
                local_file = downloader.download_video(details["download_url"], f"insta_{task_id}")
                if not local_file:
                    raise Exception("Failed to download Instagram video")
                input_videos.append(local_file)
            else:
                raise Exception("Failed to get Instagram download link")

        elif task.type == "youtube":
            details = scraper.get_youtube_details(task.source_url)
            download_url = None
            if details:
                download_url = details.get("download_url") or details.get("original_url")

            # ScrapeCreators is the primary source for YouTube metadata/URL.
            target_url = download_url or task.source_url
            local_file = downloader.download_video(target_url, f"yt_{task_id}")
            if not local_file:
                raise Exception("Failed to download YouTube video (ScrapeCreators/URL)")
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

        subtitles_enabled = bool(getattr(user, "subtitles_enabled", True))
        ass_path = None
        if subtitles_enabled:
            segments = processor.transcribe(video_path)
            ass_path = f"{video_root}.ass"
            ass_content = processor.generate_ass_subtitles(
                segments,
                font_name=user.font_name,
                font_size=user.font_size,
                font_color=user.font_color
            )
            with open(ass_path, "w") as f:
                f.write(ass_content)

        cta_clips = db.query(models.CTAClip).filter(models.CTAClip.user_id == user.id).all()
        selected_cta = random.choice(cta_clips).file_path if cta_clips else None

        active_plate = db.query(models.Plate).filter(models.Plate.id == user.selected_plate_id).first()
        plate_path = active_plate.file_path if active_plate else None
        target_account_ids = _get_target_account_ids(db, user.id)
        variants_count = len(target_account_ids) if target_account_ids else 1

        variant_outputs = processor.render_unique_variants(
            input_path=video_path,
            output_base_path=base_output,
            variants_count=variants_count,
            plate_path=plate_path,
            ass_path=ass_path,
            cta_path=selected_cta,
            subtitles_enabled=subtitles_enabled,
        )
        if not variant_outputs:
            raise Exception("Rendering returned no output variants")

        task.output_path = variant_outputs[0]
        task.target_account_id = target_account_ids[0] if target_account_ids else None
        task.status = "completed"
        task.publishing_status = "scheduled" if task.publish_at else "not_published"
        db.commit()
        db.refresh(task)

        if task.publish_at:
            celery_app.send_task("sync_publication_task", args=[task.id])

        for idx, variant_output in enumerate(variant_outputs[1:], start=2):
            variant_task = _upsert_variant_task(
                db=db,
                base_task=task,
                output_path=variant_output,
                variant_index=idx,
                publish_at=task.publish_at,
                target_account_id=target_account_ids[idx - 1] if len(target_account_ids) >= idx else None,
            )
            if variant_task.publish_at:
                celery_app.send_task("sync_publication_task", args=[variant_task.id])

    except Exception as e:
        logging.exception(f"Task {task_id} failed: {e}")
        task.status = "failed"
        db.commit()
        raise
    finally:
        db.close()

# Import scheduler to register publication sync tasks on the same Celery app.
from . import scheduler  # noqa: E402,F401
