import hashlib
from typing import Mapping, Sequence

from .video_uniqueization_profiles import resolve_uniqueization_mode


def build_unique_seed(
    *,
    project_id: int | None,
    clip_index: int,
    account_id: int | None,
    slot_index: int,
) -> int:
    seed_source = f"{project_id or 0}:{clip_index}:{account_id or 0}:{slot_index}"
    digest = hashlib.sha256(seed_source.encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


def choose_uniqueization_mode(
    *,
    requested_mode: str | None = "auto",
    force_unique_variations: bool = False,
    has_duplicate_platform_accounts: bool = False,
    env_enabled: bool = False,
) -> str:
    return resolve_uniqueization_mode(
        requested_mode,
        force_enabled=force_unique_variations or has_duplicate_platform_accounts,
        env_enabled=env_enabled,
    )


def get_duplicate_platform_account_ids(
    account_ids: Sequence[int],
    account_platform_map: Mapping[int, str],
) -> set[int]:
    platform_accounts: dict[str, list[int]] = {}
    for account_id in account_ids:
        platform = (account_platform_map.get(account_id) or "universal").strip().lower()
        platform_accounts.setdefault(platform, []).append(account_id)

    duplicate_ids: set[int] = set()
    for platform_account_ids in platform_accounts.values():
        if len(platform_account_ids) > 1:
            duplicate_ids.update(platform_account_ids)
    return duplicate_ids
