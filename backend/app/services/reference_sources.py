import datetime
from typing import Any
from collections import defaultdict
from urllib.parse import urlparse

from .. import models
from ..utils.platform_utils import _normalize_platform_code

SUPPORTED_REFERENCE_PLATFORMS = {"youtube", "instagram", "tiktok"}
TARGET_PLATFORMS = {"instagram", "tiktok", "vk", "telegram"}


def _as_handle(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith(("http://", "https://")):
        parts = [part for part in urlparse(raw).path.split("/") if part]
        raw = parts[0] if parts else ""
    raw = raw.lstrip("@").strip().rstrip("/")
    if not raw or any(char.isspace() for char in raw) or "/" in raw:
        return ""
    return f"@{raw}"


def resolve_project_account_handles(
    project_id: int,
    pmp_client,
    platform_accounts: dict[str, list[int]],
    fallback_source: str | None = None,
    db=None,
    user_id: int | None = None,
) -> dict[str, dict[int, str]]:
    """Resolve and persist PostMyPost handles once; use the trained source only as a fallback."""
    fallback = _as_handle(fallback_source)
    account_ids = {int(account_id) for ids in platform_accounts.values() for account_id in ids or []}
    stored_rows = {}
    if db is not None and user_id is not None and account_ids:
        stored_rows = {
            int(row.account_id): row
            for row in db.query(models.UserPublishChannel).filter(
                models.UserPublishChannel.user_id == int(user_id),
                models.UserPublishChannel.postmypost_project_id == int(project_id),
                models.UserPublishChannel.account_id.in_(account_ids),
            ).all()
        }
    stored_handles = {
        account_id: _as_handle(row.account_handle)
        for account_id, row in stored_rows.items()
        if _as_handle(row.account_handle)
    }
    missing_ids = account_ids - set(stored_handles)
    accounts = []
    if missing_ids:
        try:
            accounts = pmp_client.get_accounts(project_id=project_id)
        except Exception:
            accounts = []
    by_id = {
        int(item["id"]): item
        for item in accounts
        if isinstance(item, dict) and item.get("id") is not None
    }
    fetched_handles: dict[int, str] = {}
    changed = False
    for account_id in missing_ids:
        account = by_id.get(account_id, {})
        handle = next(
            (
                _as_handle(account.get(key))
                for key in ("login", "username", "handle", "screen_name")
                if _as_handle(account.get(key))
            ),
            "",
        )
        if not handle:
            continue
        fetched_handles[account_id] = handle
        row = stored_rows.get(account_id)
        if row is not None and not _as_handle(row.account_handle):
            row.account_handle = handle
            changed = True
    if changed:
        db.commit()
    result: dict[str, dict[int, str]] = {}
    for platform, account_ids in platform_accounts.items():
        result[platform] = {}
        for raw_account_id in account_ids or []:
            account_id = int(raw_account_id)
            account = by_id.get(account_id, {})
            handle = stored_handles.get(account_id) or fetched_handles.get(account_id)
            result[platform][account_id] = handle or fallback or str(account.get("name") or "").strip()
    return result


def normalize_reference_platform(value: str) -> str:
    platform = _normalize_platform_code(value)
    if platform == "vk":
        return "vk"
    return platform


def resolve_project_platform_accounts(
    project_id: int,
    pmp_client,
    db=None,
    user_id: int | None = None,
) -> dict[str, list[int]]:
    accounts = pmp_client.get_accounts(project_id=project_id)
    channels = pmp_client.get_channels()
    channels_by_id = {int(item["id"]): item for item in channels if item.get("id") is not None}
    active_account_ids: set[int] | None = None
    if db is not None and user_id is not None:
        active_rows = db.query(models.UserPublishChannel).filter(
            models.UserPublishChannel.user_id == int(user_id),
            models.UserPublishChannel.postmypost_project_id == int(project_id),
        ).all()
        active_account_ids = {int(row.account_id) for row in active_rows if row.enabled}
    result: dict[str, list[int]] = defaultdict(list)
    for account in accounts:
        if account.get("id") is None:
            continue
        account_id = int(account["id"])
        if active_account_ids is not None and account_id not in active_account_ids:
            continue
        channel_id = account.get("chanel_id", account.get("channel_id"))
        channel = channels_by_id.get(int(channel_id)) if channel_id is not None else None
        platform = _normalize_platform_code((channel or {}).get("code") or (channel or {}).get("name"))
        if platform in TARGET_PLATFORMS:
            result[platform].append(account_id)
    return {platform: sorted(set(ids)) for platform, ids in result.items()}


def extract_reference_post(channel: models.ReferenceChannel, item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    source = item.get("media") if isinstance(item.get("media"), dict) else item
    caption = source.get("caption") or source.get("desc") or source.get("description") or ""
    if isinstance(caption, dict):
        caption = caption.get("text") or ""
    raw_id = source.get("id") or source.get("videoId") or source.get("video_id") or source.get("shortcode") or source.get("code")
    source_url = source.get("url") or source.get("video_url") or source.get("link") or source.get("permalink")
    if not raw_id and source_url:
        raw_id = source_url
    if not raw_id:
        return None
    title = source.get("title") or caption
    published_at = _parse_datetime(source.get("published_at") or source.get("publishedAt") or source.get("created_at") or source.get("timestamp") or source.get("taken_at"))
    view_count = _as_int(source.get("view_count") or source.get("viewCount") or source.get("viewCountInt") or source.get("play_count"))
    return {
        "external_id": str(raw_id)[:255],
        "source_url": str(source_url).strip() if source_url else channel.source_url,
        "title": str(title).strip()[:1000],
        "body": str(title).strip()[:12000],
        "published_at": published_at,
        "view_count": view_count,
        "raw": item,
    }


def _source_payload(raw: Any) -> dict:
    if not isinstance(raw, dict):
        return {}
    return raw.get("media") if isinstance(raw.get("media"), dict) else raw


def _caption_text(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("text") or "").strip()
    return str(value or "").strip()


def _collect_image_urls(value: Any, result: list[str] | None = None) -> list[str]:
    result = result or []
    if isinstance(value, dict):
        for key in ("display_uri", "display_url", "thumbnail_src", "image_url", "url"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
                if key == "url" and not any(token in candidate for token in (".jpg", ".jpeg", ".png", "image")):
                    continue
                if candidate not in result:
                    result.append(candidate)
        for nested in value.values():
            if len(result) >= 8:
                break
            _collect_image_urls(nested, result)
    elif isinstance(value, list):
        for nested in value:
            if len(result) >= 8:
                break
            _collect_image_urls(nested, result)
    return result[:8]


def reference_post_content(post: models.ReferencePost) -> dict[str, Any]:
    source = _source_payload(post.raw)
    caption = _caption_text(source.get("caption"))
    transcript = str(
        source.get("transcript_only_text")
        or source.get("transcript")
        or ""
    ).strip()
    media_type = source.get("media_type")
    image_urls = _collect_image_urls(post.raw)
    if media_type == 8 or source.get("carousel_media"):
        content_kind = "carousel"
    elif source.get("video_versions") or transcript or source.get("download_url"):
        content_kind = "video"
    else:
        content_kind = "post"
    return {
        "content_kind": content_kind,
        "title": (post.title or "").strip(),
        "caption": caption,
        "transcript": transcript,
        "body": (post.body or "").strip(),
        "source_url": post.source_url,
        "image_urls": image_urls,
    }


def _as_int(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _parse_datetime(value) -> datetime.datetime | None:
    if isinstance(value, (int, float)):
        try:
            return datetime.datetime.utcfromtimestamp(value)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None
