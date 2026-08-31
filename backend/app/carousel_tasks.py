import logging

from . import models
from .database import SessionLocal
from .integrations.thumbnail_generator import ThumbnailGeneratorClient
from .services.carousel_pipeline import (
    build_package_prompts,
    limit_words,
    normalize_design_image,
    output_dir,
)
from .services.carousel_copy import is_russian_text
from .services.project_cta_settings import get_project_image_prompt
from .integrations.telegram_carousel import send_carousel_ready_to_telegram
from .worker import celery_app

logger = logging.getLogger(__name__)


def _generate_slide(
    generator,
    prompt: str,
    references: list[str],
    output_path: str,
    design_format: str,
) -> str:
    result = generator.generate_image_from_references(
        prompt=prompt,
        reference_paths=references,
        output_path=output_path,
        aspect_ratio="4:5" if design_format == "carousel" else "9:16",
        resolution="1K",
    )
    if not result:
        raise RuntimeError(generator.get_last_error_message_ru() or f"KIE не создал слайд {output_path}")
    return normalize_design_image(result, output_path, design_format)


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
        text = draft.approved_text or draft.master_text
        if not is_russian_text(text):
            raise RuntimeError("Текст карусели содержит латинские слова: генерация остановлена")
        image_instructions = get_project_image_prompt(db, draft.user_id, draft.project_id)
        generated: dict[str, list[str]] = {}
        story_generated: dict[str, list[str]] = {}
        for design_format, slide_count, references, ctas, target in (
            ("carousel", draft.slide_count, draft.reference_paths, draft.ctas, generated),
            ("story", draft.story_slide_count, draft.story_reference_paths or draft.reference_paths, draft.story_ctas, story_generated),
        ):
            if not references:
                raise RuntimeError(f"Не найден дизайн-референс для формата {design_format}")
            platforms = list(draft.platform_accounts or {})
            safe_ctas = {}
            for platform in platforms:
                safe_cta = limit_words(ctas.get(platform), 8)
                if safe_cta and not is_russian_text(safe_cta):
                    logger.warning("Skipping non-Russian CTA for platform %s", platform)
                    safe_cta = None
                safe_ctas[platform] = safe_cta or ""
            shared_prompts, final_prompts = build_package_prompts(
                text,
                slide_count,
                design_format,
                platforms,
                safe_ctas,
                image_instructions,
            )
            shared_paths = [
                str(destination / f"{design_format}-shared-{index}.png")
                for index in range(1, len(shared_prompts) + 1)
            ]
            for prompt, path in zip(shared_prompts, shared_paths):
                _generate_slide(generator, prompt, list(references), path, design_format)

            for platform in platforms:
                account_ids = [int(account_id) for account_id in (draft.platform_accounts or {}).get(platform, [])]
                for account_id in account_ids:
                    variant_key = platform if len(account_ids) == 1 else f"{platform}:{account_id}"
                    final_prompt = final_prompts[platform]
                    if len(account_ids) > 1:
                        final_prompt += (
                            f" Это уникальный вариант для аккаунта {account_id}. "
                            "Измени визуальную композицию и акцент финального слайда, "
                            "но сохрани текст, стиль и CTA."
                        )
                    final_path = str(destination / f"{design_format}-{platform}-{account_id}-final.png")
                    _generate_slide(
                        generator,
                        final_prompt,
                        list(references),
                        final_path,
                        design_format,
                    )
                    target[variant_key] = shared_paths + [final_path]

        if not generated or not story_generated:
            raise RuntimeError("Нет поддерживаемых социальных сетей для карусели")
        draft.slides = generated
        draft.story_slides = story_generated
        draft.status = "ready"
        draft.error = None
        db.commit()
        send_carousel_ready_to_telegram(draft)
        user = db.query(models.User).filter(models.User.id == draft.user_id).first()
        if user and user.auto_schedule_enabled:
            celery_app.send_task("schedule_carousel_publications_task", args=[draft.id])
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
