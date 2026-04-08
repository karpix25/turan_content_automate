import os
import random
import logging
from celery import Celery
from .integrations.vizard import VizardClient
from .integrations.scrape_creators import ScrapeCreatorsClient
from .integrations.downloader import Downloader
from .processor import VideoProcessor
from .database import SessionLocal
from . import models
from dotenv import load_dotenv

load_dotenv()

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
            p_id = vizard.create_project(task.source_url)
            if not p_id:
                raise Exception("Failed to create Vizard project")
            task.vizard_project_id = p_id
            db.commit()

            # 2. Poll Vizard
            clips = vizard.poll_until_complete(p_id)
            if not clips:
                raise Exception("Vizard conversion timed out or failed")
            
            # 3. Download clips
            for i, clip in enumerate(clips):
                url = clip.get("videoUrl")
                local_file = downloader.download_video(url, f"vizard_{p_id}_{i}")
                input_videos.append(local_file)

        elif task.type == "instagram":
            details = scraper.get_instagram_details(task.source_url)
            if details and details.get("download_url"):
                local_file = downloader.download_video(details["download_url"], f"insta_{task_id}")
                input_videos.append(local_file)
            else:
                raise Exception("Failed to get Instagram download link")

        elif task.type == "youtube":
            # For YouTube Shorts or direct videos
            local_file = downloader.download_video(task.source_url, f"yt_{task_id}")
            input_videos.append(local_file)

        # 4. Processing Layer
        for i, video_path in enumerate(input_videos):
            final_output = video_path.replace(".mp4", "_final.mp4")
            
            # Transcribe
            segments = processor.transcribe(video_path)
            
            # Subtitles (Use user settings)
            ass_path = video_path.replace(".mp4", ".ass")
            ass_content = processor.generate_ass_subtitles(
                segments, 
                font_name=user.font_name, 
                font_size=user.font_size, 
                font_color=user.font_color
            )
            with open(ass_path, "w") as f:
                f.write(ass_content)

            # Get random CTA
            cta_clips = db.query(models.CTAClip).filter(models.CTAClip.user_id == user.id).all()
            selected_cta = random.choice(cta_clips).file_path if cta_clips else None
            
            # Get User Plate
            active_plate = db.query(models.Plate).filter(models.Plate.id == user.selected_plate_id).first()
            plate_path = active_plate.file_path if active_plate else None

            # Render
            processor.process_video(
                input_path=video_path,
                output_path=final_output,
                plate_path=plate_path,
                ass_path=ass_path,
                cta_path=selected_cta
            )
            
            # Update task
            task.output_path = final_output
            task.status = "completed"
            db.commit()
            
            # TODO: Send notification to TG via Bot API
            # notify_user(user.telegram_id, final_output)

    except Exception as e:
        logging.error(f"Task {task_id} failed: {e}")
        task.status = "failed"
        db.commit()
    finally:
        db.close()
