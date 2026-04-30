import logging
import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from ... import models, schemas
from ...core.config import celery_client
from ...telegram_progress import update_task_status_message
from ..deps import get_db, ensure_admin_access, get_or_create_user, get_user_task_or_404
from ..utils import normalize_source_url, validate_youtube_url, resolve_output_file_path, normalize_utc_naive

router = APIRouter(prefix="/tasks", tags=["tasks"])

@router.post("/{telegram_id}")
def create_task(telegram_id: str, payload: schemas.VideoTaskCreate, db: Session = Depends(get_db)):
    user = get_or_create_user(db, telegram_id)
    publish_at = normalize_utc_naive(payload.publish_at)
    source_url = normalize_source_url(payload.source_url, payload.type)

    if payload.type == "youtube":
        validate_youtube_url(source_url)

    new_task = models.VideoTask(
        user_id=user.id,
        source_url=source_url,
        type=payload.type,
        source_title=(payload.source_title or "").strip() or None,
        status="pending",
        publish_at=publish_at,
        publishing_status="scheduled" if publish_at else "not_published",
        telegram_chat_id=(payload.telegram_chat_id or "").strip() or None,
        telegram_status_message_id=(payload.telegram_status_message_id or "").strip() or None,
    )
    db.add(new_task)
    db.commit()
    db.refresh(new_task)

    update_task_status_message(
        db,
        new_task,
        stage="Задача создана",
        detail="Видео добавлено в очередь обработки.",
    )

    try:
        celery_client.send_task("process_content_task", args=[new_task.id])
    except Exception as e:
        logging.error(f"Failed to enqueue task {new_task.id}: {e}")
        raise HTTPException(status_code=500, detail="Task created but queue enqueue failed")

    return {"status": "queued", "task_id": new_task.id, "type": payload.type}

@router.get("/{telegram_id}", response_model=list[schemas.VideoTaskOut])
def list_user_tasks(telegram_id: str, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    tasks = db.query(models.VideoTask).filter(
        models.VideoTask.user_id == user.id
    ).order_by(models.VideoTask.created_at.desc()).limit(100).all()
    return tasks

@router.get("/{telegram_id}/{task_id}/file")
def download_task_output(telegram_id: str, task_id: int, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    task = get_user_task_or_404(db, user.id, task_id)

    if not task.output_path:
        raise HTTPException(status_code=400, detail="Task has no rendered output yet")

    resolved_path = resolve_output_file_path(task.output_path)
    if not resolved_path:
        raise HTTPException(status_code=404, detail="Rendered file not found on disk")

    import os
    return FileResponse(
        path=resolved_path,
        filename=os.path.basename(resolved_path),
        media_type="video/mp4",
    )

@router.patch("/{telegram_id}/{task_id}/schedule", response_model=schemas.VideoTaskOut)
def update_task_schedule(
    telegram_id: str,
    task_id: int,
    payload: schemas.VideoTaskScheduleUpdate,
    db: Session = Depends(get_db)
):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    task = get_user_task_or_404(db, user.id, task_id)

    if task.publishing_status == "published":
        raise HTTPException(status_code=400, detail="Cannot reschedule already published task")

    publish_at = normalize_utc_naive(payload.publish_at)
    task.publish_at = publish_at
    task.publishing_status = "scheduled" if publish_at else "not_published"
    db.commit()

    try:
        if publish_at and task.status == "completed" and (task.output_path or task.postmypost_file_id):
            celery_client.send_task("sync_publication_task", args=[task.id], kwargs={"force_now": False})
        if publish_at is None:
            celery_client.send_task("unschedule_publication_task", args=[task.id])
    except Exception as e:
        logging.error(f"Failed to enqueue schedule sync for task {task.id}: {e}")

    db.refresh(task)
    return task

@router.post("/{telegram_id}/{task_id}/publish-now", response_model=schemas.VideoTaskOut)
def publish_task_now(telegram_id: str, task_id: int, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    task = get_user_task_or_404(db, user.id, task_id)

    if task.status != "completed":
        raise HTTPException(status_code=400, detail="Task is not processed yet")
    if not task.output_path and not task.postmypost_file_id:
        raise HTTPException(status_code=400, detail="Task has no render output or uploaded PostMyPost file")
    if task.publishing_status == "published":
        raise HTTPException(status_code=400, detail="Task already published")

    task.publish_at = datetime.datetime.utcnow()
    task.publishing_status = "in_progress"
    db.commit()

    try:
        celery_client.send_task("sync_publication_task", args=[task.id], kwargs={"force_now": True})
    except Exception as e:
        logging.error(f"Failed to enqueue publish-now for task {task.id}: {e}")
        task.publishing_status = "failed"
        db.commit()
        raise HTTPException(status_code=500, detail="Queue enqueue failed")

    db.refresh(task)
    return task

@router.delete("/{telegram_id}/{task_id}")
def delete_task(telegram_id: str, task_id: int, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    task = get_user_task_or_404(db, user.id, task_id)
    db.delete(task)
    db.commit()
    return {"ok": True}
