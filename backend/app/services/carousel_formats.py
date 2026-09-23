"""Per-project output preferences shared by generation and publication."""
from .. import models

SUPPORTED_PUBLICATION_FORMATS = {
    "instagram": ("carousel", "story"),
    "tiktok": ("carousel",),
    "vk": ("carousel", "story"),
    "telegram": ("carousel", "story"),
}


def normalize_formats(value: dict | None) -> dict[str, dict[str, bool]]:
    value = value if isinstance(value, dict) else {}
    return {
        platform: {
            kind: kind in supported and (value.get(platform) or {}).get(kind, True) is True
            for kind in ("carousel", "story")
        }
        for platform, supported in SUPPORTED_PUBLICATION_FORMATS.items()
    }


def enabled_formats(value: dict | None, platform: str) -> tuple[str, ...]:
    return tuple(kind for kind, enabled in normalize_formats(value).get(platform, {}).items() if enabled)


def get_project_carousel_formats(db, user_id: int, project_id: int) -> dict:
    row = db.query(models.PostMyPostProjectSetting).filter(
        models.PostMyPostProjectSetting.user_id == user_id,
        models.PostMyPostProjectSetting.project_id == project_id,
    ).first()
    return normalize_formats(getattr(row, "carousel_formats", None))


def filter_platform_accounts(accounts: dict, formats: dict) -> dict:
    return {platform: ids for platform, ids in accounts.items() if ids and enabled_formats(formats, platform)}


def missing_enabled_ctas(accounts: dict, formats: dict, carousel_ctas: dict, story_ctas: dict) -> list[str]:
    ctas = {"carousel": carousel_ctas, "story": story_ctas}
    labels = {"carousel": "карусель", "story": "сторис"}
    return [
        f"{platform} — {labels[kind]}"
        for platform in accounts
        for kind in enabled_formats(formats, platform)
        if not ctas[kind].get(platform)
    ]
