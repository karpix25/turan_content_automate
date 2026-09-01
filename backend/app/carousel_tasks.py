import logging
import os

from . import models
from .core.config import llm, pmp_client, scraper
from .database import SessionLocal
from .integrations.carousel_renderer import CarouselRendererClient
from .integrations.cloudinary_storage import CloudinaryStorage
from .services.carousel_pipeline import (
    get_design_profile,
    limit_words,
    output_dir,
    split_master_text,
)
from .services.carousel_copy import build_platform_texts, is_russian_text, strip_source_cta
from .services.carousel_template import build_carousel_render_request
from .services.project_cta_settings import get_project_image_prompt
from .services.design_composition import analyze_design_composition
from .services.reference_sources import resolve_project_account_handles
from .services.account_avatars import sync_missing_account_avatars
from .integrations.telegram_carousel import send_carousel_ready_to_telegram
from .worker import celery_app

logger = logging.getLogger(__name__)


def _render_slide(
    renderer: CarouselRendererClient,
    part: str,
    composition_contract: str,
    cta: str,
    author: str,
    avatar_url: str,
    output_path: str,
    design_format: str,
) -> str:
    template, data = build_carousel_render_request(
        part,
        composition_contract,
        design_format,
        cta,
        author,
        avatar_url,
    )
    return renderer.render(template, data, output_path)


@celery_app.task(name="generate_carousel_task", soft_time_limit=3600, time_limit=3900)
def generate_carousel_task(draft_id: int) -> None:
    db = SessionLocal()
    try:
        draft = db.query(models.CarouselDraft).filter(models.CarouselDraft.id == draft_id).first()
        if not draft:
            return
        renderer = CarouselRendererClient()
        reference_storage = CloudinaryStorage(
            timeout_seconds=180.0,
            folder=(os.getenv("DESIGN_REFERENCES_CLOUDINARY_FOLDER") or "turan/design-references").strip(),
        )
        destination = output_dir(draft.id)
        destination.mkdir(parents=True, exist_ok=True)
        text = strip_source_cta(draft.approved_text or draft.master_text)
        if not is_russian_text(text):
            raise RuntimeError("Текст карусели содержит латинские слова: генерация остановлена")
        platforms = list(draft.platform_accounts or {})
        platform_texts = build_platform_texts(llm, text, platforms)
        user = db.query(models.User).filter(models.User.id == draft.user_id).first()
        account_handles = resolve_project_account_handles(
            draft.project_id,
            pmp_client,
            draft.platform_accounts or {},
            fallback_source=user.training_source if user else None,
            db=db,
            user_id=draft.user_id,
        )
        account_avatars = {
            int(row.account_id): row.account_avatar_url
            for row in db.query(models.UserPublishChannel).filter(
                models.UserPublishChannel.user_id == draft.user_id,
                models.UserPublishChannel.postmypost_project_id == draft.project_id,
            ).all()
            if row.account_avatar_url
        }
        try:
            pmp_accounts = pmp_client.get_accounts(project_id=draft.project_id)
            pmp_channels = pmp_client.get_channels()
            channels_by_id = {
                int(channel["id"]): channel
                for channel in pmp_channels
                if isinstance(channel, dict) and channel.get("id") is not None
            }
            account_avatars.update(sync_missing_account_avatars(
                db,
                draft.user_id,
                draft.project_id,
                pmp_accounts,
                channels_by_id,
                scraper,
            ))
        except Exception:
            logger.exception("Failed to resolve account avatars for draft %s", draft.id)
        image_instructions = get_project_image_prompt(db, draft.user_id, draft.project_id)
        generated: dict[str, list[str]] = {}
        story_generated: dict[str, list[str]] = {}
        for design_format, slide_count, references, ctas, target in (
            ("carousel", draft.slide_count, draft.reference_paths, draft.ctas, generated),
            ("story", draft.story_slide_count, draft.story_reference_paths or draft.reference_paths, draft.story_ctas, story_generated),
        ):
            if not references:
                raise RuntimeError(f"Не найден дизайн-референс для формата {design_format}")
            reference_urls = []
            for index, reference in enumerate(references, start=1):
                raw_reference = str(reference).strip()
                public_url = raw_reference if raw_reference.startswith(("http://", "https://")) else reference_storage.upload_file(
                    raw_reference,
                    prefix=f"composition_{design_format}_{index}",
                )
                if public_url and public_url not in reference_urls:
                    reference_urls.append(public_url)
            composition_contract = analyze_design_composition(
                llm,
                reference_urls,
                design_format,
                additional_instructions=image_instructions,
            )
            safe_ctas = {}
            for platform in platforms:
                safe_cta = limit_words((ctas or {}).get(platform), 8)
                if safe_cta and not is_russian_text(safe_cta):
                    logger.warning("Skipping non-Russian CTA for platform %s", platform)
                    safe_cta = None
                safe_ctas[platform] = safe_cta or ""
            profile = get_design_profile(design_format)
            for platform in platforms:
                variant_text = platform_texts.get(platform) or text
                parts = split_master_text(variant_text, min(slide_count, profile["max_slides"]), profile["max_words"])
                account_ids = [int(account_id) for account_id in (draft.platform_accounts or {}).get(platform, [])]
                for account_id in account_ids:
                    variant_key = platform if len(account_ids) == 1 else f"{platform}:{account_id}"
                    author = account_handles.get(platform, {}).get(account_id, "")
                    avatar_url = account_avatars.get(account_id, "")
                    paths = []
                    for index, part in enumerate(parts, start=1):
                        path = str(destination / f"{design_format}-{platform}-{account_id}-{index}.png")
                        _render_slide(
                            renderer,
                            part,
                            composition_contract,
                            safe_ctas[platform] if index == len(parts) else "",
                            author,
                            avatar_url,
                            path,
                            design_format,
                        )
                        paths.append(path)
                    target[variant_key] = paths

        if not generated or not story_generated:
            raise RuntimeError("Нет поддерживаемых социальных сетей для карусели")
        draft.slides = generated
        draft.story_slides = story_generated
        draft.platform_texts = platform_texts
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
