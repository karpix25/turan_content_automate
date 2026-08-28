import logging

from . import models
from .core.config import pmp_client
from .database import SessionLocal
from .carousel_publication_service import schedule_carousel_publications
from .worker import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="schedule_carousel_publications_task")
def schedule_carousel_publications_task(draft_id: int) -> None:
    db = SessionLocal()
    try:
        draft = db.query(models.CarouselDraft).filter(models.CarouselDraft.id == draft_id).first()
        if not draft or draft.status != "ready":
            return
        user = db.query(models.User).filter(models.User.id == draft.user_id).first()
        if not user or not user.auto_schedule_enabled:
            return
        schedule_carousel_publications(db, user, draft, pmp_client)
    except Exception:
        logger.exception("Automatic carousel scheduling failed for draft %s", draft_id)
        raise
    finally:
        db.close()
