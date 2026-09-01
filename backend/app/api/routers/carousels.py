import datetime
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ... import models, schemas
from ...core.config import celery_client, pmp_client
from ...carousel_publication_service import schedule_carousel_publications
from ...services.carousel_pipeline import suggest_package_slide_count
from ...services.project_cta_settings import get_project_ctas
from ...services.reference_sources import resolve_project_platform_accounts
from ...integrations.telegram_carousel import send_carousel_text_review_to_telegram
from ...utils.postmypost_projects import resolve_user_postmypost_project_id
from ..deps import ensure_admin_access, get_db, get_or_create_user
from ..utils import normalize_utc_naive

router = APIRouter(prefix="/carousels", tags=["carousels"])


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
        platform_accounts = resolve_project_platform_accounts(project_id, pmp_client, db, user.id)
        if not platform_accounts:
            raise ValueError("В проекте нет активных подключенных аккаунтов")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logging.exception("Failed to prepare carousel draft")
        raise HTTPException(status_code=502, detail=f"Не удалось подготовить карусель: {exc}")

    carousel_ctas, story_ctas = get_project_ctas(db, user.id, project_id)
    missing_ctas = [
        platform for platform in platform_accounts
        if not carousel_ctas.get(platform) or not story_ctas.get(platform)
    ]
    if missing_ctas:
        raise HTTPException(
            status_code=400,
            detail="Заполните CTA карусели и Stories для: " + ", ".join(missing_ctas),
        )
    package_slide_count = suggest_package_slide_count(master_text)
    draft = models.CarouselDraft(
        user_id=user.id,
        project_id=project_id,
        master_text=master_text,
        status="awaiting_approval",
        slide_count=package_slide_count,
        story_slide_count=package_slide_count,
        reference_paths=[],
        story_reference_paths=[],
        platform_accounts=platform_accounts,
        ctas=carousel_ctas,
        story_ctas=story_ctas,
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
    try:
        schedule_carousel_publications(
            db,
            user,
            draft,
            pmp_client,
            manual_post_at=normalize_utc_naive(post_at),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logging.exception("Failed to schedule carousel draft %s", draft_id)
        raise HTTPException(status_code=502, detail=f"Не удалось запланировать публикации: {exc}")
    db.refresh(draft)
    return draft


@router.post("/{telegram_id}/{draft_id}/schedule", response_model=schemas.CarouselDraftOut)
def auto_schedule_carousel(
    telegram_id: str,
    draft_id: int,
    db: Session = Depends(get_db),
):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    draft = _get_draft(db, user.id, draft_id)
    if draft.status != "ready" or not isinstance(draft.slides, dict):
        raise HTTPException(status_code=400, detail="Карусель еще не готова")
    try:
        schedule_carousel_publications(db, user, draft, pmp_client)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logging.exception("Failed to auto-schedule carousel draft %s", draft_id)
        raise HTTPException(status_code=502, detail=f"Не удалось запланировать публикации: {exc}")
    db.refresh(draft)
    return draft
