import os
import re
import random
import logging
from typing import List

from .. import models
from ..publish_planner import plan_next_publish_times
from ..worker import pmp_client
from .media_utils import _resolve_media_file_path


def _normalize_platform_code(value: str | None) -> str:
    code = (value or "").strip().lower()
    if not code:
        return "universal"

    normalized = code.replace("-", "_").replace(" ", "_")
    aliases = {
        "ig": "instagram",
        "insta": "instagram",
        "yt": "youtube",
        "you_tube": "youtube",
        "youtube_shorts": "youtube",
        "instagram_reels": "instagram",
        "instagram_reel": "instagram",
    }
    normalized = aliases.get(normalized, normalized)

    if normalized in {"instagram", "youtube", "tiktok", "universal"}:
        return normalized

    # PostMyPost channel codes can vary by network/type; infer by tokens.
    tokens = set(re.split(r"[^a-z0-9]+", normalized))
    if "instagram" in normalized or {"ig", "insta", "instagram"} & tokens:
        return "instagram"
    if "youtube" in normalized or {"yt", "youtube"} & tokens:
        return "youtube"
    if "tiktok" in normalized or {"tt", "tiktok"} & tokens:
        return "tiktok"

    return "universal"


def _parse_env_account_ids(env_val: str) -> List[int]:
    if not env_val:
        return []
    try:
        return [int(x.strip()) for x in env_val.split(",") if x.strip().isdigit()]
    except Exception:
        return []


def _get_target_account_ids(db, user_id: int) -> List[int]:
    ids = [
        item.account_id
        for item in db.query(models.UserPublishChannel).filter(
            models.UserPublishChannel.user_id == user_id,
            models.UserPublishChannel.enabled.is_(True),
        ).order_by(models.UserPublishChannel.account_id.asc()).all()
    ]
    if ids:
        return ids

    env_ids = _parse_env_account_ids(os.getenv("POSTMYPOST_CHANNEL_IDS", ""))
    if env_ids:
        return env_ids

    # Fallback: if user did not configure channel toggles yet, use all
    # accounts available in the selected PostMyPost project.
    try:
        if pmp_client.api_key:
            project_id_raw = os.getenv("POSTMYPOST_PROJECT_ID", "").strip()
            project_id = int(project_id_raw) if project_id_raw else None
            project_id = pmp_client.ensure_project_id(project_id)
            accounts = pmp_client.get_accounts(project_id=project_id)
            account_ids = sorted(
                {
                    int(item["id"])
                    for item in accounts
                    if isinstance(item, dict) and item.get("id") is not None
                }
            )
            if account_ids:
                logging.info(
                    "No explicit enabled channels for user %s, fallback to all project accounts: %s",
                    user_id,
                    account_ids,
                )
                return account_ids
    except Exception as e:
        logging.warning("Failed to load fallback PostMyPost account ids: %s", e)

    return []


def _get_account_platform_map(account_ids: List[int]) -> dict[int, str]:
    if not account_ids or not pmp_client.api_key:
        return {}
    try:
        project_id_raw = os.getenv("POSTMYPOST_PROJECT_ID", "").strip()
        project_id = int(project_id_raw) if project_id_raw else None
        project_id = pmp_client.ensure_project_id(project_id)
        accounts = pmp_client.get_accounts(project_id=project_id)
        channels = pmp_client.get_channels()
        channels_by_id = {
            int(item["id"]): item
            for item in channels
            if isinstance(item, dict) and item.get("id") is not None
        }
        account_set = set(account_ids)
        result: dict[int, str] = {}
        for account in accounts:
            account_id = account.get("id")
            if account_id is None:
                continue
            account_id = int(account_id)
            if account_id not in account_set:
                continue
            channel_id_raw = account.get("chanel_id", account.get("channel_id"))
            channel_id = int(channel_id_raw) if channel_id_raw is not None else None
            channel_info = channels_by_id.get(channel_id) if channel_id is not None else None
            channel_code = channel_info.get("code") if channel_info else None
            channel_name = channel_info.get("name") if channel_info else None
            result[account_id] = _normalize_platform_code(channel_code or channel_name)
        return result
    except Exception as e:
        logging.warning(f"Failed to resolve account platform map from PostMyPost: {e}")
        return {}


def _get_channel_plate_config(
    db,
    user: models.User,
    account_id: int | None,
) -> tuple[str | None, int]:
    selected_plate_ids: list[int] = []
    if getattr(user, "selected_plate_id", None) is not None:
        selected_plate_ids = [int(user.selected_plate_id)]
    plate_start_percent = max(0, min(100, int(getattr(user, "plate_start_percent", 0) or 0)))

    if account_id is not None:
        row = db.query(models.UserPublishChannel).filter(
            models.UserPublishChannel.user_id == user.id,
            models.UserPublishChannel.account_id == account_id,
        ).first()
        if row:
            if isinstance(row.selected_plate_ids, list):
                selected_plate_ids = [int(item) for item in row.selected_plate_ids if item is not None]
            elif row.selected_plate_id is not None:
                selected_plate_ids = [int(row.selected_plate_id)]
            if row.plate_start_percent is not None:
                plate_start_percent = max(0, min(100, int(row.plate_start_percent or 0)))

    active_plate = None
    if selected_plate_ids:
        candidates = db.query(models.Plate).filter(models.Plate.id.in_(selected_plate_ids)).all()
        if candidates:
            active_plate = random.choice(candidates)
    plate_path = _resolve_media_file_path(active_plate.file_path if active_plate else None, media_kind="plates")
    return plate_path, plate_start_percent


def _pick_platform_ending(
    clips: List[models.CTAClip],
    platform: str,
    account_id: int | None,
    used_ids_by_platform: dict[str, set[int]],
) -> models.CTAClip | None:
    normalized = _normalize_platform_code(platform)
    exact_account = [
        clip for clip in clips
        if getattr(clip, "account_id", None) == account_id
        and _normalize_platform_code(getattr(clip, "platform", None)) == normalized
    ]
    exact_global = [
        clip for clip in clips
        if getattr(clip, "account_id", None) is None
        and _normalize_platform_code(getattr(clip, "platform", None)) == normalized
    ]
    universal_account = [
        clip for clip in clips
        if getattr(clip, "account_id", None) == account_id
        and _normalize_platform_code(getattr(clip, "platform", None)) == "universal"
    ]
    universal_global = [
        clip for clip in clips
        if getattr(clip, "account_id", None) is None
        and _normalize_platform_code(getattr(clip, "platform", None)) == "universal"
    ]
    fallback_any = [
        clip for clip in clips
        if getattr(clip, "account_id", None) in {None, account_id}
    ]
    pool = (
        exact_account
        if exact_account else exact_global
        if exact_global else universal_account
        if universal_account else universal_global
        if universal_global else fallback_any
    )
    if not pool:
        return None

    used_key = f"{account_id}:{normalized}" if pool is not fallback_any else f"{account_id}:fallback_any"
    used = used_ids_by_platform.setdefault(used_key, set())
    available = [clip for clip in pool if clip.id not in used]
    if available:
        choice = random.choice(available)
        used.add(choice.id)
        return choice
    return random.choice(pool)


def _build_account_variant_plan(
    account_ids: List[int],
    account_platform_map: dict[int, str],
) -> tuple[int, dict[int, int]]:
    if not account_ids:
        return 1, {}

    groups: dict[str, List[int]] = {}
    for account_id in account_ids:
        platform_code = _normalize_platform_code(account_platform_map.get(account_id))
        groups.setdefault(platform_code, []).append(account_id)

    variant_count = max((len(items) for items in groups.values()), default=1)
    account_variant_index: dict[int, int] = {}
    for account_group in groups.values():
        for slot_idx, account_id in enumerate(account_group, start=1):
            account_variant_index[account_id] = slot_idx

    return max(1, variant_count), account_variant_index
