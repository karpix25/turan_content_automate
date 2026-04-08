import os
import logging
import datetime
from sqlalchemy.orm import Session
from .database import SessionLocal
from . import models
from .integrations.postmypost import PostMyPostClient
from .worker import celery_app
from dotenv import load_dotenv

load_dotenv()

pmp_client = PostMyPostClient(api_key=os.getenv("POSTMYPOST_API_KEY", ""))

@celery_app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    # Check for publications every minute
    sender.add_periodic_task(60.0, check_and_publish.s(), name='check_publications_every_minute')

@celery_app.task(name="check_and_publish")
def check_and_publish():
    db = SessionLocal()
    now = datetime.datetime.utcnow()
    
    # Ready to publish tasks
    tasks = db.query(models.VideoTask).filter(
        models.VideoTask.publish_at <= now,
        models.VideoTask.publishing_status == "not_published",
        models.VideoTask.status == "completed"  # Only published finished videos
    ).all()

    for task in tasks:
        task.publishing_status = "in_progress"
        db.commit()
        
        # Trigger the actual publishing
        publish_video_task.delay(task.id)
    
    db.close()

@celery_app.task(name="publish_video_task")
def publish_video_task(task_id: int):
    db = SessionLocal()
    task = db.query(models.VideoTask).get(task_id)
    if not task:
        return

    try:
        # 1. Upload to PostMyPost
        media_id = pmp_client.upload_file(task.output_path)
        if not media_id:
            raise Exception("Failed to upload media to PostMyPost")
        
        # 2. Create Publication
        # For simplicity, we use generic text, but this could be from task metadata
        # channels could be from user settings
        resp = pmp_client.create_publication(
            text="New Reels/Shorts posted from Content Studio!",
            media_ids=[media_id],
            channels=[1, 2, 3] # Placeholders for channel IDs
        )
        
        if resp:
            task.publishing_status = "published"
            task.postmypost_id = str(resp.get("id"))
            db.commit()
            logger.info(f"Task {task_id} successfully published to PostMyPost")
    except Exception as e:
        logger.error(f"Failed to publish task {task_id}: {e}")
        task.publishing_status = "failed"
        db.commit()
    finally:
        db.close()
