from sqlalchemy.orm import Session

from .. import models

SUPPORTED_CAROUSEL_PLATFORMS = ("instagram", "tiktok", "vk", "telegram")
MAX_CAROUSEL_IMAGE_PROMPT_LENGTH = 2000


def normalize_ctas(value: dict | None) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(platform).strip().lower(): str(text).strip()
        for platform, text in value.items()
        if str(platform).strip().lower() in SUPPORTED_CAROUSEL_PLATFORMS and str(text).strip()
    }


def normalize_image_prompt(value: str | None) -> str | None:
    text = str(value or "").strip()
    return text[:MAX_CAROUSEL_IMAGE_PROMPT_LENGTH] or None


def get_project_ctas(db: Session, user_id: int, project_id: int) -> tuple[dict[str, str], dict[str, str]]:
    row = db.query(models.PostMyPostProjectSetting).filter(
        models.PostMyPostProjectSetting.user_id == user_id,
        models.PostMyPostProjectSetting.project_id == project_id,
    ).first()
    if not row:
        return {}, {}
    return normalize_ctas(row.carousel_ctas), normalize_ctas(row.story_ctas)


def get_project_image_prompt(db: Session, user_id: int, project_id: int) -> str | None:
    row = db.query(models.PostMyPostProjectSetting).filter(
        models.PostMyPostProjectSetting.user_id == user_id,
        models.PostMyPostProjectSetting.project_id == project_id,
    ).first()
    return normalize_image_prompt(row.carousel_image_prompt) if row else None


def set_project_ctas(
    db: Session,
    user_id: int,
    project_id: int,
    carousel_ctas: dict | None = None,
    story_ctas: dict | None = None,
) -> None:
    row = db.query(models.PostMyPostProjectSetting).filter(
        models.PostMyPostProjectSetting.user_id == user_id,
        models.PostMyPostProjectSetting.project_id == project_id,
    ).first()
    if not row:
        row = models.PostMyPostProjectSetting(user_id=user_id, project_id=project_id)
        db.add(row)
    if carousel_ctas is not None:
        row.carousel_ctas = normalize_ctas(carousel_ctas)
    if story_ctas is not None:
        row.story_ctas = normalize_ctas(story_ctas)


def set_project_image_prompt(db: Session, user_id: int, project_id: int, value: str | None) -> None:
    row = db.query(models.PostMyPostProjectSetting).filter(
        models.PostMyPostProjectSetting.user_id == user_id,
        models.PostMyPostProjectSetting.project_id == project_id,
    ).first()
    if not row:
        row = models.PostMyPostProjectSetting(user_id=user_id, project_id=project_id)
        db.add(row)
    row.carousel_image_prompt = normalize_image_prompt(value)
