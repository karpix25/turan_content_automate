import logging
import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from ... import models, schemas
from ...core.config import celery_client
from ...core.config import pmp_client
from ...telegram_progress import update_task_status_message
from ...utils.postmypost_projects import (
    ensure_postmypost_project_available,
    resolve_user_postmypost_project_id,
)
from ..deps import get_db, ensure_admin_access, get_or_create_user, get_user_task_or_404
from ..utils import normalize_source_url, validate_youtube_url, resolve_output_file_path, normalize_utc_naive

router = APIRouter(prefix="/tasks", tags=["tasks"])
AVATAR_TASK_TYPES = {
    "avatar_heygen",
    "avatar_horizontal",
    "avatar_vertical",
    "avatar_youtube",
    "avatar_instagram",
    "avatar_instagram_post_5s",
    "avatar_shorts",
    "avatar_tiktok",
}


def _get_queue_snapshot(db: Session, user_id: int, task_id: int) -> tuple[int, int]:
    active_statuses = ["pending", "processing"]
    total = db.query(models.VideoTask).filter(
        models.VideoTask.user_id == user_id,
        models.VideoTask.status.in_(active_statuses),
    ).count()
    position = db.query(models.VideoTask).filter(
        models.VideoTask.user_id == user_id,
        models.VideoTask.status.in_(active_statuses),
        models.VideoTask.id <= task_id,
    ).count()
    return max(1, position), max(position, total)


def _build_created_task_detail(queue_position: int, queue_total: int) -> str:
    return (
        "Видео добавлено в очередь обработки.\n"
        f"Очередь: #{queue_position} из {queue_total}."
    )


@router.post("/{telegram_id}")
def create_task(telegram_id: str, payload: schemas.VideoTaskCreate, db: Session = Depends(get_db)):
    user = get_or_create_user(db, telegram_id)
    source_url = normalize_source_url(payload.source_url, payload.type)
    publish_at = None if payload.type in AVATAR_TASK_TYPES else normalize_utc_naive(payload.publish_at)

    if payload.type == "youtube":
        validate_youtube_url(source_url)

    try:
        postmypost_project_id = int(payload.postmypost_project_id) if payload.postmypost_project_id else resolve_user_postmypost_project_id(user, pmp_client)
        postmypost_project_id = ensure_postmypost_project_available(postmypost_project_id, pmp_client)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    new_task = models.VideoTask(
        user_id=user.id,
        postmypost_project_id=postmypost_project_id,
        source_url=source_url,
        type=payload.type,
        source_title=(payload.source_title or "").strip() or None,
        status="pending",
        publish_at=publish_at,
        publishing_status="scheduled" if publish_at else "not_published",
        telegram_chat_id=(payload.telegram_chat_id or "").strip() or None,
        telegram_status_message_id=(payload.telegram_status_message_id or "").strip() or None,
        telegram_reply_message_id=(payload.telegram_reply_message_id or "").strip() or None,
    )
    db.add(new_task)
    db.commit()
    db.refresh(new_task)
    queue_position, queue_total = _get_queue_snapshot(db, user.id, new_task.id)

    update_task_status_message(
        db,
        new_task,
        stage="Задача создана",
        detail=_build_created_task_detail(queue_position, queue_total),
    )

    try:
        celery_client.send_task("process_content_task", args=[new_task.id])
    except Exception as e:
        logging.error(f"Failed to enqueue task {new_task.id}: {e}")
        raise HTTPException(status_code=500, detail="Task created but queue enqueue failed")

    return {
        "status": "queued",
        "task_id": new_task.id,
        "type": payload.type,
        "queue_position": queue_position,
        "queue_total": queue_total,
    }

@router.get("/{telegram_id}", response_model=list[schemas.VideoTaskOut])
def list_user_tasks(
    telegram_id: str,
    publish_from: datetime.datetime | None = None,
    publish_to: datetime.datetime | None = None,
    project_id: int | None = None,
    db: Session = Depends(get_db),
):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    query = db.query(models.VideoTask).filter(
        models.VideoTask.user_id == user.id
    )
    if project_id is not None:
        query = query.filter(models.VideoTask.postmypost_project_id == int(project_id))
    if publish_from is not None:
        query = query.filter(models.VideoTask.publish_at >= normalize_utc_naive(publish_from))
    if publish_to is not None:
        query = query.filter(models.VideoTask.publish_at <= normalize_utc_naive(publish_to))
    if publish_from is not None or publish_to is not None:
        query = query.filter(models.VideoTask.publish_at.isnot(None))
        tasks = query.order_by(models.VideoTask.publish_at.asc()).limit(500).all()
    else:
        tasks = query.order_by(models.VideoTask.created_at.desc()).limit(100).all()
    return tasks

@router.get("/{telegram_id}/{task_id}", response_model=schemas.VideoTaskOut)
def get_task(telegram_id: str, task_id: int, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    return get_user_task_or_404(db, user.id, task_id)

@router.get("/{telegram_id}/{task_id}/file")
def download_task_output(
    telegram_id: str,
    task_id: int,
    download: bool = False,
    db: Session = Depends(get_db),
):
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
        content_disposition_type="attachment" if download else "inline",
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

    if task.type in AVATAR_TASK_TYPES:
        raise HTTPException(
            status_code=400,
            detail="avatar tasks do not use PostMyPost scheduling; file is uploaded to Yandex.Disk automatically",
        )

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

@router.post("/{telegram_id}/{task_id}/thumbnail-prompt-review", response_model=schemas.VideoTaskOut)
def update_thumbnail_prompt_review(
    telegram_id: str,
    task_id: int,
    payload: schemas.ThumbnailPromptReviewUpdate,
    db: Session = Depends(get_db),
):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    task = get_user_task_or_404(db, user.id, task_id)

    action = (payload.action or "").strip().lower()
    if action not in {"approve", "reject", "edit"}:
        raise HTTPException(status_code=400, detail="action must be approve, reject, or edit")

    meta = dict(task.script_meta or {})
    review = dict(meta.get("thumbnail_prompt_review") or {})
    current_prompt = (review.get("prompt") or "").strip()
    edited_prompt = (payload.prompt or "").strip()

    if action == "edit" and not edited_prompt:
        review["status"] = "awaiting_edit"
    elif action == "reject":
        review["status"] = "rejected"
    else:
        review["status"] = "approved"
        if edited_prompt:
            review["approved_prompt"] = edited_prompt
        elif current_prompt:
            review["approved_prompt"] = current_prompt

    review["action"] = action
    review["updated_at"] = datetime.datetime.utcnow().isoformat()
    meta["thumbnail_prompt_review"] = review
    task.script_meta = meta
    db.commit()
    db.refresh(task)
    return task

@router.post("/{telegram_id}/{task_id}/publish-now", response_model=schemas.VideoTaskOut)
def publish_task_now(telegram_id: str, task_id: int, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    task = get_user_task_or_404(db, user.id, task_id)

    if task.type in AVATAR_TASK_TYPES:
        raise HTTPException(
            status_code=400,
            detail="avatar tasks are not published via PostMyPost; check Yandex.Disk root folder disk:/",
        )

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
