import httpx
import logging
import os
import re
import tempfile

from .. import models
from ..integrations.deepgram_client import DeepgramClient
from .reference_sources import reference_post_content

logger = logging.getLogger(__name__)


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


def analyze_reference_post(scraper, post: models.ReferencePost) -> dict:
    payload = reference_post_content(post)
    source_url = str(post.source_url).strip()
    lowered_url = source_url.lower()
    is_instagram = "instagram" in lowered_url
    is_tiktok = "tiktok" in lowered_url
    is_youtube = "youtube" in lowered_url or "youtu.be" in lowered_url
    if not scraper or not post.source_url:
        if is_instagram or is_tiktok:
            payload["transcript"] = ""
        return payload
    if is_instagram:
        details = scraper.get_instagram_details(source_url) or {}
    elif is_tiktok:
        details = scraper.get_tiktok_details(source_url) or {}
    elif is_youtube:
        details = scraper.get_youtube_details(source_url) or {}
    else:
        details = {}
    if not details:
        if is_instagram or is_tiktok:
            payload["transcript"] = ""
        return payload
    details_caption = details.get("caption") or ""
    if isinstance(details_caption, dict):
        details_caption = details_caption.get("text") or ""
    payload["caption"] = str(details_caption).strip() or payload["caption"]
    payload["title"] = str(details.get("title") or payload["title"]).strip()
    payload["image_urls"] = list(dict.fromkeys(payload["image_urls"] + list(details.get("image_urls") or [])))[:8]
    if is_instagram or is_tiktok:
        payload["transcript"] = _download_transcript(
            str(details.get("download_url") or ""),
            DeepgramClient(os.getenv("DEEPGRAM_API_KEY", "")),
        )
    else:
        payload["transcript"] = str(
            details.get("transcript_only_text") or details.get("transcript") or payload["transcript"] or ""
        ).strip()
    if not payload["transcript"] and is_youtube:
        transcript_payload = scraper.get_youtube_transcript(source_url) or {}
        payload["transcript"] = str(
            transcript_payload.get("transcript_only_text")
            or transcript_payload.get("transcript")
            or transcript_payload.get("text")
            or ""
        ).strip()
    return payload


def analysis_source_text(item: dict) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for field in ("transcript", "caption", "body", "title"):
        value = re.sub(r"\s+", " ", str(item.get(field) or "").strip())
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            parts.append(value)
    return " ".join(parts)
