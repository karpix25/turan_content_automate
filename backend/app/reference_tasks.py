import datetime
import logging
import os
import tempfile

import httpx

from . import models
from .core.config import llm, pmp_client
from .database import SessionLocal
from .services.carousel_copy import build_reference_rewrite_prompt, fallback_reference_text
from .services.carousel_pipeline import resolve_reference_paths, suggest_package_slide_count
from .services.project_cta_settings import get_project_ctas
from .services.reference_sources import extract_reference_post, reference_post_content, resolve_project_platform_accounts
from .integrations.deepgram_client import DeepgramClient
from .telegram_progress import send_carousel_text_review_to_telegram
from .integrations.scrape_creators import ScrapeCreatorsClient
from .worker import celery_app

logger = logging.getLogger(__name__)


def _fetch_items(scraper, channel: models.ReferenceChannel) -> list[dict]:
    if channel.platform == "youtube":
        payload = scraper.get_channel_videos(channel.source_url, sort="latest") or {}
        from .api.utils import _get_channel_videos_list
        return _get_channel_videos_list(payload)[:20]
    if channel.platform == "instagram":
        return (scraper.get_instagram_user_reels(channel.source_url, max_items=20) or {}).get("items") or []
    details = scraper.get_tiktok_details(channel.source_url) or {}
    return [details] if details.get("caption") or details.get("transcript_only_text") else []


def _prepare_item(channel: models.ReferenceChannel, item: dict) -> dict | None:
    prepared = dict(item)
    if channel.platform == "youtube":
        video_id = prepared.get("videoId") or prepared.get("video_id") or prepared.get("id")
        if video_id and not prepared.get("url"):
            prepared["url"] = f"https://www.youtube.com/watch?v={video_id}"
    if channel.platform == "instagram":
        code = prepared.get("shortcode") or prepared.get("code")
        if code and not prepared.get("url"):
            prepared["url"] = f"https://www.instagram.com/p/{code}/"
    if channel.platform == "tiktok":
        prepared["url"] = channel.source_url
        prepared["id"] = channel.source_url
        prepared["description"] = prepared.get("caption") or prepared.get("transcript_only_text")
    return extract_reference_post(channel, prepared)


def _upsert_posts(db, channel: models.ReferenceChannel, items: list[dict]) -> list[models.ReferencePost]:
    result = []
    for item in items:
        normalized = _prepare_item(channel, item)
        if not normalized:
            continue
        post = db.query(models.ReferencePost).filter(
            models.ReferencePost.channel_id == channel.id,
            models.ReferencePost.external_id == normalized["external_id"],
        ).first()
        if not post:
            post = models.ReferencePost(channel_id=channel.id, external_id=normalized["external_id"])
            db.add(post)
        for key, value in normalized.items():
            setattr(post, key, value)
        result.append(post)
    db.commit()
    return result


def _pick_top_posts(posts: list[models.ReferencePost]) -> list[models.ReferencePost]:
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=14)
    fresh = [post for post in posts if not post.published_at or post.published_at >= cutoff]
    return sorted(
        fresh,
        key=lambda post: (post.view_count or 0, post.published_at or datetime.datetime.min),
        reverse=True,
    )[:3]


def _download_transcript(url: str, deepgram: DeepgramClient) -> str:
    if not url or not deepgram.is_configured:
        return ""
    try:
        with httpx.Client(timeout=180.0) as client, tempfile.NamedTemporaryFile(suffix=".mp4") as media:
            response = client.get(url)
            response.raise_for_status()
            media.write(response.content)
            media.flush()
            return (deepgram.transcribe_media_text(media.name) or "").strip()
    except Exception as exc:
        logger.warning("Reference video transcription failed: %s", exc)
        return ""


def _analysis_payload(scraper, post: models.ReferencePost) -> dict:
    payload = reference_post_content(post)
    if payload["transcript"] or payload["content_kind"] != "video":
        return payload
    details = {}
    if post.source_url and post.raw:
        platform = "instagram" if "instagram" in str(post.source_url).lower() else ""
        if platform:
            details = scraper.get_instagram_details(post.source_url) or {}
        elif "tiktok" in str(post.source_url).lower():
            details = scraper.get_tiktok_details(post.source_url) or {}
        elif "youtube" in str(post.source_url).lower() or "youtu.be" in str(post.source_url).lower():
            details = scraper.get_youtube_details(post.source_url) or {}
    details_caption = details.get("caption") or ""
    if isinstance(details_caption, dict):
        details_caption = details_caption.get("text") or ""
    payload["caption"] = payload["caption"] or str(details_caption).strip()
    payload["image_urls"] = list(dict.fromkeys(payload["image_urls"] + list(details.get("image_urls") or [])))[:8]
    payload["transcript"] = str(details.get("transcript_only_text") or details.get("transcript") or "").strip()
    if not payload["transcript"]:
        payload["transcript"] = _download_transcript(str(details.get("download_url") or ""), DeepgramClient(os.getenv("DEEPGRAM_API_KEY", "")))
    return payload


def _build_master_text(user: models.User, posts: list[models.ReferencePost], scraper=None) -> str:
    payload = [_analysis_payload(scraper, post) if scraper else reference_post_content(post) for post in posts]
    for item in payload:
        source_text = " ".join(
            str(item.get(field) or "") for field in ("title", "caption", "transcript", "body")
        ).strip()
        if item.get("content_kind") == "video" and not item.get("transcript") and len(source_text.split()) < 8:
            raise ValueError("Не удалось извлечь содержательный текст из видео референса")
    generated = llm._complete(build_reference_rewrite_prompt(payload, user.author_style_profile), temperature=0.65)
    text = (generated or fallback_reference_text(payload)).strip()
    if text.upper().startswith("НЕДОСТАТОЧНО ДАННЫХ"):
        raise ValueError("В референсе недостаточно данных для анализа")
    return text


def _create_daily_draft(db, user: models.User, project_id: int, posts: list[models.ReferencePost], scraper) -> bool:
    today = datetime.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    existing = db.query(models.CarouselDraft).filter(
        models.CarouselDraft.user_id == user.id,
        models.CarouselDraft.project_id == project_id,
        models.CarouselDraft.created_at >= today,
        models.CarouselDraft.status != "rejected",
    ).first()
    if existing:
        return False
    platform_accounts = resolve_project_platform_accounts(project_id, pmp_client)
    if not platform_accounts:
        return False
    carousel_ctas, story_ctas = get_project_ctas(db, user.id, project_id)
    if any(not carousel_ctas.get(platform) or not story_ctas.get(platform) for platform in platform_accounts):
        logger.warning("Skipping daily reference draft: CTA is missing for project %s", project_id)
        return False
    try:
        master_text = _build_master_text(user, posts, scraper)
    except ValueError as exc:
        logger.warning("Skipping reference draft for project %s: %s", project_id, exc)
        return False
    package_slide_count = suggest_package_slide_count(master_text)
    reference_paths = resolve_reference_paths(db, user.id, [], project_id=project_id, design_format="carousel")
    story_reference_paths = resolve_reference_paths(db, user.id, [], project_id=project_id, design_format="story")
    draft = models.CarouselDraft(
        user_id=user.id,
        project_id=project_id,
        master_text=master_text,
        status="awaiting_approval",
        slide_count=package_slide_count,
        story_slide_count=package_slide_count,
        reference_paths=reference_paths,
        story_reference_paths=story_reference_paths,
        platform_accounts=platform_accounts,
        ctas=carousel_ctas,
        story_ctas=story_ctas,
        source_post_ids=[post.id for post in posts],
        telegram_chat_id=user.telegram_id,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    send_carousel_text_review_to_telegram(draft)
    return True


@celery_app.task(name="sync_reference_channels_task", soft_time_limit=1200, time_limit=1500)
def sync_reference_channels_task(user_id: int | None = None, project_id: int | None = None) -> int:
    db = SessionLocal()
    scraper = ScrapeCreatorsClient(api_key=(os.getenv("SCRAPE_CREATORS_API_KEY") or "").strip())
    created = 0
    try:
        query = db.query(models.ReferenceChannel).filter(models.ReferenceChannel.is_active.is_(True))
        if user_id is not None:
            query = query.filter(models.ReferenceChannel.user_id == int(user_id))
        if project_id is not None:
            query = query.filter(models.ReferenceChannel.project_id == int(project_id))
        channels = query.order_by(models.ReferenceChannel.id.asc()).all()
        grouped: dict[tuple[int, int], list[models.ReferencePost]] = {}
        for channel in channels:
            try:
                posts = _upsert_posts(db, channel, _fetch_items(scraper, channel))
                channel.last_synced_at = datetime.datetime.utcnow()
                db.commit()
                key = (channel.user_id, channel.project_id)
                grouped.setdefault(key, []).extend(posts)
            except Exception:
                logger.exception("Failed to sync reference channel %s", channel.id)
        for (owner_id, owner_project_id), posts in grouped.items():
            top_posts = _pick_top_posts(posts)
            if len(top_posts) < 1:
                continue
            user = db.query(models.User).filter(models.User.id == owner_id).first()
            if user and _create_daily_draft(db, user, owner_project_id, top_posts, scraper):
                created += 1
        return created
    finally:
        db.close()
