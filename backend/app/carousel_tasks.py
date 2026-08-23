import logging

from . import models
from .database import SessionLocal
from .integrations.thumbnail_generator import ThumbnailGeneratorClient
from .services.carousel_pipeline import build_slide_prompts, normalize_design_image, output_dir
from .telegram_progress import send_carousel_ready_to_telegram
from .worker import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="generate_carousel_task", soft_time_limit=3600, time_limit=3900)
def generate_carousel_task(draft_id: int) -> None:
    db = SessionLocal()
    try:
        draft = db.query(models.CarouselDraft).filter(models.CarouselDraft.id == draft_id).first()
        if not draft:
            return
        generator = ThumbnailGeneratorClient()
        destination = output_dir(draft.id)
        destination.mkdir(parents=True, exist_ok=True)
        generated: dict[str, list[str]] = {}
        for platform in (draft.platform_accounts or {}):
            cta = (draft.ctas or {}).get(platform, "")
            generated[platform] = []
            prompts = build_slide_prompts(draft.approved_text or draft.master_text, draft.slide_count, platform, cta)
            for index, prompt in enumerate(prompts, start=1):
                output_path = destination / f"{platform}-{index}.png"
                result = generator.generate_image_from_references(
                    prompt=prompt,
                    reference_paths=list(draft.reference_paths or []),
                    output_path=str(output_path),
                    aspect_ratio="4:5",
                    resolution="1K",
                )
                if not result:
                    raise RuntimeError(generator.get_last_error_message_ru() or f"KIE не создал слайд {platform}-{index}")
                generated[platform].append(normalize_design_image(result, str(output_path), "carousel"))
        if not generated:
            raise RuntimeError("Нет поддерживаемых социальных сетей для карусели")
        draft.slides = generated
        draft.status = "ready"
        draft.error = None
        db.commit()
        send_carousel_ready_to_telegram(draft)
    except Exception as exc:
        logger.exception("Carousel generation failed for draft %s", draft_id)
        draft = db.query(models.CarouselDraft).filter(models.CarouselDraft.id == draft_id).first()
        if draft:
            draft.status = "failed"
            draft.error = str(exc)[:1000]
            db.commit()
        raise
    finally:
        db.close()
