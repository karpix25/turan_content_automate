import datetime
import logging

from . import models
from .integrations.postmypost_carousel import create_media_publication
from .publication_guard import verify_publication_payload
from .publication_reconciler import reconcile_scheduled_publications
from .publish_planner import get_min_publish_lead_delta, plan_next_publish_times_for_account_outputs
from .services.carousel_copy import template_package_text

logger = logging.getLogger(__name__)
UTC = datetime.timezone.utc

# PostMyPost documents Stories as type 2. VK receives the carousel package as
# a regular multi-image post, which is VK's supported equivalent.
SUPPORTED_PUBLICATION_FORMATS = {
    "instagram": ("carousel", "story"),
    "tiktok": ("carousel",),
    "vk": ("carousel", "story"),
    "telegram": ("carousel", "story"),
}


def _as_utc(value: datetime.datetime) -> datetime.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _targets(draft: models.CarouselDraft) -> list[dict]:
    result = []
    for platform, account_ids in (draft.platform_accounts or {}).items():
        platform = str(platform).strip().lower()
        for media_format in SUPPORTED_PUBLICATION_FORMATS.get(platform, ()):
            slides = draft.slides if media_format == "carousel" else draft.story_slides
            for account_id in account_ids or []:
                variant_key = f"{platform}:{int(account_id)}"
                paths = (slides or {}).get(variant_key) or (slides or {}).get(platform) or []
                if not paths:
                    continue
                result.append({
                    "platform": platform,
                    "account_id": int(account_id),
                    "format": media_format,
                    "paths": [str(path) for path in paths],
                })
    return result


def _provider_id(payload: dict) -> str | None:
    value = payload.get("id") or payload.get("publication_id")
    return str(value) if value else None


def _publication_content(draft: models.CarouselDraft, platform: str, media_format: str) -> str:
    variants = draft.platform_texts if isinstance(draft.platform_texts, dict) else {}
    variant = variants.get(platform)
    if isinstance(variant, str):
        return variant
    if isinstance(variant, dict):
        package = variant.get(media_format)
        if isinstance(package, dict) and (text := template_package_text(package)):
            return text
    return str(draft.approved_text or draft.master_text)


def _scheduled_rows(db, draft_id: int) -> dict[tuple[str, int, str], models.CarouselPublication]:
    rows = db.query(models.CarouselPublication).filter(
        models.CarouselPublication.draft_id == draft_id,
    ).all()
    return {
        (row.platform, int(row.account_id), row.media_format): row
        for row in rows
    }


def schedule_carousel_publications(
    db,
    user: models.User,
    draft: models.CarouselDraft,
    client,
    manual_post_at: datetime.datetime | None = None,
) -> list[models.CarouselPublication]:
    targets = _targets(draft)
    if not targets:
        raise ValueError("Для проекта нет поддерживаемых пакетов карусели или Stories")

    existing = _scheduled_rows(db, draft.id)
    pending = [
        target for target in targets
        if not (
            (row := existing.get((target["platform"], target["account_id"], target["format"])))
            and row.postmypost_id
            and row.publishing_status in {"scheduled", "in_progress", "published"}
        )
    ]
    if not pending:
        draft.status = "scheduled"
        db.commit()
        return list(existing.values())

    account_ids = [target["account_id"] for target in pending]
    reconcile_scheduled_publications(
        db, user, account_ids, lane="instant", client=client
    )
    if manual_post_at is not None:
        post_at_values = [_as_utc(manual_post_at).replace(tzinfo=None, microsecond=0)] * len(pending)
        if _as_utc(manual_post_at) <= datetime.datetime.now(UTC) + get_min_publish_lead_delta():
            raise ValueError("Время публикации должно быть минимум на час позже текущего")
    else:
        post_at_values = plan_next_publish_times_for_account_outputs(
            db,
            user,
            account_ids,
            lane="instant",
            project_id=draft.project_id,
        )

    uploaded: dict[str, int] = {}
    result = []
    for target, post_at in zip(pending, post_at_values):
        key = (target["platform"], target["account_id"], target["format"])
        row = existing.get(key) or models.CarouselPublication(
            draft_id=draft.id,
            user_id=user.id,
            project_id=draft.project_id,
            platform=target["platform"],
            account_id=target["account_id"],
            media_format=target["format"],
        )
        db.add(row)
        row.post_at = post_at
        row.file_ids = []
        row.publishing_status = "pending"
        row.error = None
        db.commit()

        publication_id = None
        try:
            file_ids = []
            for path in target["paths"]:
                if path not in uploaded:
                    uploaded[path] = int(client.upload_local_file(draft.project_id, path))
                file_ids.append(uploaded[path])
            row.file_ids = file_ids
            response = create_media_publication(
                client,
                project_id=draft.project_id,
                account_ids=[target["account_id"]],
                post_at=post_at,
                file_ids=file_ids,
                content=_publication_content(draft, target["platform"], target["format"]),
                publication_type=2 if target["format"] == "story" else 1,
            )
            publication_id = _provider_id(response)
            if not publication_id:
                raise RuntimeError("PostMyPost не вернул ID публикации")
            payload = client.get_publication(
                int(publication_id), account_ids=[target["account_id"]]
            )
            verify_publication_payload(
                payload,
                expected_post_at=post_at,
                now_utc=datetime.datetime.now(UTC),
                minimum_lead=get_min_publish_lead_delta(),
            )
            row.postmypost_id = publication_id
            row.publishing_status = "scheduled"
            row.error = None
            db.commit()
            result.append(row)
        except Exception as exc:
            if publication_id:
                try:
                    client.delete_publication(
                        publication_id=int(publication_id),
                        account_ids=[target["account_id"]],
                    )
                except Exception:
                    logger.warning("Could not clean invalid carousel publication %s", publication_id)
            row.postmypost_id = None
            row.post_at = None
            row.publishing_status = "failed"
            row.error = str(exc)[:1000]
            db.commit()
            logger.exception("Carousel scheduling failed for draft=%s target=%s", draft.id, key)
            raise

    draft.status = "scheduled"
    draft.error = None
    db.commit()
    from .integrations.telegram_carousel import send_carousel_scheduled_to_telegram
    send_carousel_scheduled_to_telegram(draft, result)
    return result
