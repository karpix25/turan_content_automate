import datetime
import logging
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ... import models, schemas
from ...core.config import celery_client, pmp_client
from ...integrations.postmypost_carousel import create_carousel_publication
from ...services.carousel_pipeline import SUPPORTED_PLATFORMS, resolve_reference_paths
from ...services.project_cta_settings import get_project_ctas
from ...telegram_progress import send_carousel_text_review_to_telegram
from ...utils.platform_utils import _normalize_platform_code
from ...utils.postmypost_projects import resolve_user_postmypost_project_id
from ..deps import ensure_admin_access, get_db, get_or_create_user
from ..utils import normalize_utc_naive

router = APIRouter(prefix="/carousels", tags=["carousels"])


def _project_accounts(user: models.User, project_id: int) -> dict[str, list[int]]:
    accounts = pmp_client.get_accounts(project_id=project_id)
    channels = pmp_client.get_channels()
    channels_by_id = {int(item["id"]): item for item in channels if item.get("id") is not None}
    result: dict[str, list[int]] = defaultdict(list)
    for account in accounts:
        if account.get("id") is None:
            continue
        account_id = int(account["id"])
        channel_id = account.get("chanel_id", account.get("channel_id"))
        channel = channels_by_id.get(int(channel_id)) if channel_id is not None else None
        platform = _normalize_platform_code((channel or {}).get("code") or (channel or {}).get("name"))
        if platform in SUPPORTED_PLATFORMS:
            result[platform].append(account_id)
    return {platform: sorted(set(ids)) for platform, ids in result.items()}


def _get_draft(db: Session, user_id: int, draft_id: int) -> models.CarouselDraft:
    draft = db.query(models.CarouselDraft).filter(
        models.CarouselDraft.id == draft_id,
        models.CarouselDraft.user_id == user_id,
    ).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Карусель не найдена")
    return draft


@router.post("/{telegram_id}", response_model=schemas.CarouselDraftOut)
def create_carousel(
    telegram_id: str,
    payload: schemas.CarouselDraftCreate,
    db: Session = Depends(get_db),
):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    master_text = (payload.master_text or "").strip()
    if not master_text:
        raise HTTPException(status_code=400, detail="Текст карусели не может быть пустым")
    project_id = int(payload.project_id or resolve_user_postmypost_project_id(user, pmp_client))
    try:
        platform_accounts = _project_accounts(user, project_id)
        if not platform_accounts:
            raise ValueError("В проекте нет подключенных Instagram, TikTok или VK аккаунтов")
        reference_paths = resolve_reference_paths(
            db,
            user.id,
            payload.design_reference_ids or payload.reference_ids,
            project_id=project_id,
            design_format="carousel",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logging.exception("Failed to prepare carousel draft")
        raise HTTPException(status_code=502, detail=f"Не удалось подготовить карусель: {exc}")

    carousel_ctas, _ = get_project_ctas(db, user.id, project_id)
    missing_ctas = [platform for platform in platform_accounts if not carousel_ctas.get(platform)]
    if missing_ctas:
        raise HTTPException(
            status_code=400,
            detail="Заполните CTA карусели для: " + ", ".join(missing_ctas),
        )
    draft = models.CarouselDraft(
        user_id=user.id,
        project_id=project_id,
        master_text=master_text,
        status="awaiting_approval",
        slide_count=max(2, min(10, int(payload.slide_count or 5))),
        reference_paths=reference_paths,
        platform_accounts=platform_accounts,
        ctas=carousel_ctas,
        telegram_chat_id=(payload.telegram_chat_id or telegram_id).strip(),
        telegram_reply_message_id=(payload.telegram_reply_message_id or "").strip() or None,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    send_carousel_text_review_to_telegram(draft)
    return draft


@router.get("/{telegram_id}", response_model=list[schemas.CarouselDraftOut])
def list_carousels(telegram_id: str, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    return db.query(models.CarouselDraft).filter(
        models.CarouselDraft.user_id == user.id,
    ).order_by(models.CarouselDraft.created_at.desc()).limit(50).all()


@router.post("/{telegram_id}/{draft_id}/review", response_model=schemas.CarouselDraftOut)
def review_carousel(
    telegram_id: str,
    draft_id: int,
    payload: schemas.CarouselDraftReviewUpdate,
    db: Session = Depends(get_db),
):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    draft = _get_draft(db, user.id, draft_id)
    action = (payload.action or "").strip().lower()
    if action not in {"approve", "edit", "reject"}:
        raise HTTPException(status_code=400, detail="action must be approve, edit, or reject")
    should_generate = False
    if action == "reject":
        draft.status = "rejected"
    elif action == "edit":
        edited = (payload.text or "").strip()
        if not edited:
            raise HTTPException(status_code=400, detail="Новый текст не может быть пустым")
        draft.approved_text = edited
        draft.status = "generating"
        should_generate = True
    else:
        draft.approved_text = draft.master_text
        draft.status = "generating"
        should_generate = True
    db.commit()
    if should_generate:
        celery_client.send_task("generate_carousel_task", args=[draft.id])
    db.refresh(draft)
    return draft


@router.post("/{telegram_id}/{draft_id}/publish", response_model=schemas.CarouselDraftOut)
def publish_carousel(
    telegram_id: str,
    draft_id: int,
    post_at: datetime.datetime,
    db: Session = Depends(get_db),
):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    draft = _get_draft(db, user.id, draft_id)
    if draft.status != "ready" or not isinstance(draft.slides, dict):
        raise HTTPException(status_code=400, detail="Карусель еще не готова")
    for platform, account_ids in (draft.platform_accounts or {}).items():
        paths = (draft.slides or {}).get(platform) or []
        file_ids = [pmp_client.upload_local_file(draft.project_id, path) for path in paths]
        create_carousel_publication(
            pmp_client,
            project_id=draft.project_id,
            account_ids=account_ids,
            post_at=normalize_utc_naive(post_at),
            file_ids=file_ids,
            content=draft.approved_text or draft.master_text,
        )
    draft.status = "published"
    db.commit()
    db.refresh(draft)
    return draft
