import datetime
from collections import defaultdict

from .. import models
from ..utils.platform_utils import _normalize_platform_code

SUPPORTED_REFERENCE_PLATFORMS = {"youtube", "instagram", "tiktok"}
TARGET_PLATFORMS = {"instagram", "tiktok", "vk"}


def normalize_reference_platform(value: str) -> str:
    platform = _normalize_platform_code(value)
    if platform == "vk":
        return "vk"
    return platform


def resolve_project_platform_accounts(project_id: int, pmp_client) -> dict[str, list[int]]:
    accounts = pmp_client.get_accounts(project_id=project_id)
    channels = pmp_client.get_channels()
    channels_by_id = {int(item["id"]): item for item in channels if item.get("id") is not None}
    result: dict[str, list[int]] = defaultdict(list)
    for account in accounts:
        if account.get("id") is None:
            continue
        channel_id = account.get("chanel_id", account.get("channel_id"))
        channel = channels_by_id.get(int(channel_id)) if channel_id is not None else None
        platform = _normalize_platform_code((channel or {}).get("code") or (channel or {}).get("name"))
        if platform in TARGET_PLATFORMS:
            result[platform].append(int(account["id"]))
    return {platform: sorted(set(ids)) for platform, ids in result.items()}


def extract_reference_post(channel: models.ReferenceChannel, item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    raw_id = item.get("id") or item.get("videoId") or item.get("video_id") or item.get("shortcode") or item.get("code")
    source_url = item.get("url") or item.get("video_url") or item.get("link") or item.get("permalink")
    if not raw_id and source_url:
        raw_id = source_url
    if not raw_id:
        return None
    title = item.get("title") or item.get("caption") or item.get("desc") or item.get("description") or ""
    published_at = _parse_datetime(item.get("published_at") or item.get("publishedAt") or item.get("created_at") or item.get("timestamp"))
    view_count = _as_int(item.get("view_count") or item.get("viewCount") or item.get("viewCountInt") or item.get("play_count"))
    return {
        "external_id": str(raw_id)[:255],
        "source_url": str(source_url).strip() if source_url else channel.source_url,
        "title": str(title).strip()[:1000],
        "body": str(title).strip()[:12000],
        "published_at": published_at,
        "view_count": view_count,
        "raw": item,
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
