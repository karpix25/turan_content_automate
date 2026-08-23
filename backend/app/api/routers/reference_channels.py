from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ... import models, schemas
from ...core.config import celery_client, pmp_client
from ...services.reference_sources import SUPPORTED_REFERENCE_PLATFORMS, normalize_reference_platform
from ...utils.postmypost_projects import resolve_user_postmypost_project_id
from ..deps import ensure_admin_access, get_db, get_or_create_user

router = APIRouter(prefix="/reference-channels", tags=["reference-channels"])


@router.get("/{telegram_id}", response_model=list[schemas.ReferenceChannelOut])
def list_reference_channels(telegram_id: str, project_id: int | None = None, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    query = db.query(models.ReferenceChannel).filter(models.ReferenceChannel.user_id == user.id)
    if project_id is not None:
        query = query.filter(models.ReferenceChannel.project_id == int(project_id))
    return query.order_by(models.ReferenceChannel.created_at.desc()).all()


@router.post("/{telegram_id}", response_model=schemas.ReferenceChannelOut)
def add_reference_channel(
    telegram_id: str,
    payload: schemas.ReferenceChannelCreate,
    db: Session = Depends(get_db),
):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    platform = normalize_reference_platform(payload.platform)
    if platform not in SUPPORTED_REFERENCE_PLATFORMS:
        raise HTTPException(status_code=400, detail="Источник должен быть YouTube, Instagram или TikTok")
    source_url = (payload.source_url or "").strip()
    if not source_url:
        raise HTTPException(status_code=400, detail="Ссылка на источник обязательна")
    project_id = int(payload.project_id or resolve_user_postmypost_project_id(user, pmp_client))
    existing = db.query(models.ReferenceChannel).filter(
        models.ReferenceChannel.user_id == user.id,
        models.ReferenceChannel.project_id == project_id,
        models.ReferenceChannel.platform == platform,
        models.ReferenceChannel.source_url == source_url,
    ).first()
    if existing:
        return existing
    item = models.ReferenceChannel(
        user_id=user.id,
        project_id=project_id,
        platform=platform,
        source_url=source_url,
        title=(payload.title or "").strip() or None,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{telegram_id}/{channel_id}")
def delete_reference_channel(telegram_id: str, channel_id: int, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    item = db.query(models.ReferenceChannel).filter(
        models.ReferenceChannel.id == channel_id,
        models.ReferenceChannel.user_id == user.id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Референсный канал не найден")
    db.query(models.ReferencePost).filter(models.ReferencePost.channel_id == item.id).delete(synchronize_session=False)
    db.delete(item)
    db.commit()
    return {"status": "deleted"}


@router.post("/{telegram_id}/sync")
def sync_reference_channels(telegram_id: str, project_id: int | None = None, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    target_project_id = int(project_id or resolve_user_postmypost_project_id(user, pmp_client))
    celery_client.send_task("sync_reference_channels_task", args=[user.id, target_project_id])
    return {"status": "queued", "project_id": target_project_id}
