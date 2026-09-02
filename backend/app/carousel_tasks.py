import logging

from . import models
from .core.config import llm, pmp_client, scraper
from .database import SessionLocal
from .integrations.carousel_renderer import CarouselRendererClient
from .services.carousel_pipeline import (
    limit_words,
    output_dir,
)
from .services.carousel_copy import build_template_package, is_russian_text, strip_source_cta
from .services.karpix_carousel import load_template_set, render_account_carousel
from .services.reference_sources import resolve_project_account_handles
from .services.account_avatars import sync_missing_account_avatars
from .integrations.telegram_carousel import send_carousel_ready_to_telegram
from .worker import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="generate_carousel_task", soft_time_limit=3600, time_limit=3900)
def generate_carousel_task(draft_id: int, schedule_after: bool | None = None) -> None:
    db = SessionLocal()
    try:
        draft = db.query(models.CarouselDraft).filter(models.CarouselDraft.id == draft_id).first()
        if not draft:
            return
        renderer = CarouselRendererClient()
        destination = output_dir(draft.id)
        destination.mkdir(parents=True, exist_ok=True)
        text = strip_source_cta(draft.approved_text or draft.master_text)
        if not is_russian_text(text):
            raise RuntimeError("Текст карусели содержит латинские слова: генерация остановлена")
        platforms = list(draft.platform_accounts or {})
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
        template_sets: dict[str, dict] = {"carousel": load_template_set(renderer, "carousel")}
        try:
            template_sets["story"] = load_template_set(renderer, "story")
        except ValueError as exc:
            logger.info("KARPIX Stories templates are not configured: %s", exc)
        format_packages: dict[str, dict[str, dict]] = {}
        format_ctas: dict[str, dict[str, str]] = {}
        for design_format, slide_count in (
            ("carousel", draft.slide_count),
            ("story", draft.story_slide_count),
        ):
            if design_format not in template_sets:
                continue
            ctas = draft.ctas if design_format == "carousel" else (draft.story_ctas or {})
            safe_ctas = {}
            packages = {}
            for platform in platforms:
                safe_cta = limit_words((ctas or {}).get(platform), 8)
                if safe_cta and not is_russian_text(safe_cta):
                    logger.warning("Skipping non-Russian CTA for platform %s", platform)
                    safe_cta = ""
                safe_ctas[platform] = safe_cta
                packages[platform] = build_template_package(
                    llm,
                    text,
                    platform,
                    template_sets[design_format],
                    slide_count,
                    safe_cta,
                )
            format_ctas[design_format] = safe_ctas
            format_packages[design_format] = packages

        platform_packages = {
            platform: {
                design_format: packages[platform]
                for design_format, packages in format_packages.items()
                if platform in packages
            }
            for platform in platforms
        }
        generated: dict[str, list[str]] = {}
        story_generated: dict[str, list[str]] = {}
        for design_format, target in (
            ("carousel", generated),
            ("story", story_generated),
        ):
            if design_format not in template_sets:
                continue
            for platform in platforms:
                account_ids = [int(account_id) for account_id in (draft.platform_accounts or {}).get(platform, [])]
                for account_id in account_ids:
                    variant_key = platform if len(account_ids) == 1 else f"{platform}:{account_id}"
                    author = account_handles.get(platform, {}).get(account_id, "")
                    avatar_url = account_avatars.get(account_id, "")
                    target[variant_key] = render_account_carousel(
                        renderer,
                        template_sets[design_format],
                        format_packages[design_format][platform],
                        format_ctas[design_format][platform],
                        author,
                        avatar_url,
                        destination,
                        design_format,
                        platform,
                        account_id,
                    )

        if not generated:
            raise RuntimeError("Нет поддерживаемых социальных сетей для карусели")
        draft.slides = generated
        draft.story_slides = story_generated
        draft.slide_count = max((len(paths) for paths in generated.values()), default=0)
        draft.story_slide_count = max((len(paths) for paths in story_generated.values()), default=0)
        draft.platform_texts = platform_packages
        draft.status = "ready"
        draft.error = None
        db.commit()
        send_carousel_ready_to_telegram(draft)
        user = db.query(models.User).filter(models.User.id == draft.user_id).first()
        if user and (schedule_after if schedule_after is not None else user.auto_schedule_enabled):
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
