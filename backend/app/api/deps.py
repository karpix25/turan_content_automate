import logging
from fastapi import HTTPException
from sqlalchemy.orm import Session
from .. import models
from ..database import SessionLocal
from .utils import get_telegram_admin_ids

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def ensure_admin_access(telegram_id: str) -> None:
    admin_ids = get_telegram_admin_ids()
    if not admin_ids:
        logging.warning("TELEGRAM_ADMIN_IDS is empty; admin endpoints are not restricted")
        return
    if str(telegram_id).strip() not in admin_ids:
        raise HTTPException(status_code=403, detail="Access denied")

def get_or_create_user(db: Session, telegram_id: str) -> models.User:
    admin_ids = get_telegram_admin_ids()
    effective_id = str(telegram_id).strip()
    if effective_id in admin_ids:
        effective_id = "shared_admin"
        
    user = db.query(models.User).filter(models.User.telegram_id == effective_id).first()
    if user:
        return user
    user = models.User(telegram_id=effective_id)

    db.add(user)
    db.commit()
    db.refresh(user)
    return user

def get_user_task_or_404(db: Session, user_id: int, task_id: int) -> models.VideoTask:
    task = db.query(models.VideoTask).filter(
        models.VideoTask.id == task_id,
        models.VideoTask.user_id == user_id
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
