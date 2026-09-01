import logging
import re
from typing import Any

from .. import models
from ..utils.platform_utils import _normalize_platform_code

logger = logging.getLogger(__name__)

_AVATAR_FIELDS = {
    "avatar",
    "avatarurl",
    "avatarlarger",
    "avatarmedium",
    "avatarthumb",
    "imageurl",
    "profileimageurl",
    "profilepicurl",
    "profilepicurlhd",
    "profilepicture",
    "profilephoto",
    "profilepictureurl",
    "photo200",
    "photo400",
    "picture",
}


def _normalized_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _find_avatar_url(value: Any, inside_avatar: bool = False) -> str:
    if isinstance(value, str):
        candidate = value.strip()
        return candidate if inside_avatar and candidate.startswith(("http://", "https://")) else ""
    if isinstance(value, list):
        for item in value:
            found = _find_avatar_url(item, inside_avatar)
            if found:
                return found
        return ""
    if not isinstance(value, dict):
        return ""

    for key, child in value.items():
        is_avatar_field = _normalized_key(key) in _AVATAR_FIELDS
        found = _find_avatar_url(child, inside_avatar or is_avatar_field)
        if found:
            return found
    return ""


def _clean_identifier(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return raw.lstrip("@").strip()


def _profile_details(scraper, platform: str, account: dict) -> dict:
    login = _clean_identifier(account.get("login") or account.get("username") or account.get("handle"))
    external_id = _clean_identifier(account.get("external_id"))
    if platform == "instagram" and login:
        return scraper.get_instagram_profile(login) or {}
    if platform == "tiktok":
        return scraper.get_tiktok_profile(login, user_id=external_id) or {}
    if platform == "youtube":
        return scraper.get_youtube_channel(login or external_id) or {}
    if platform == "telegram" and login:
        return scraper.get_telegram_channel(login) or {}
    return {}


def resolve_account_avatar_url(account: dict, channel_code: str | None, scraper=None) -> str:
    direct_url = _find_avatar_url(account)
    if direct_url:
        return direct_url
    if scraper is None or (hasattr(scraper, "api_key") and not scraper.api_key):
        return ""

    platform = _normalize_platform_code(channel_code)
    try:
        return _find_avatar_url(_profile_details(scraper, platform, account))
    except Exception as exc:
        logger.warning("Failed to resolve avatar for PostMyPost account %s: %s", account.get("id"), exc)
        return ""


def sync_missing_account_avatars(
    db,
    user_id: int,
    project_id: int,
    accounts: list[dict],
    channels_by_id: dict[int, dict],
    scraper=None,
) -> dict[int, str]:
    rows = db.query(models.UserPublishChannel).filter(
        models.UserPublishChannel.user_id == int(user_id),
        models.UserPublishChannel.postmypost_project_id == int(project_id),
    ).all()
    rows_by_account = {int(row.account_id): row for row in rows}
    changed = False

    for account in accounts:
        if not isinstance(account, dict) or account.get("id") is None:
            continue
        account_id = int(account["id"])
        row = rows_by_account.get(account_id)
        if row is None or not row.enabled or row.account_avatar_url:
            continue
        channel_id = account.get("chanel_id", account.get("channel_id"))
        channel = channels_by_id.get(int(channel_id)) if channel_id is not None else {}
        avatar_url = resolve_account_avatar_url(account, (channel or {}).get("code"), scraper)
        if avatar_url:
            row.account_avatar_url = avatar_url
            changed = True

    if changed:
        db.commit()
    return {
        account_id: row.account_avatar_url
        for account_id, row in rows_by_account.items()
        if row.account_avatar_url
    }
