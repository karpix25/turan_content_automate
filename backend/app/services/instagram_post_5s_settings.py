from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from .. import models


@dataclass(frozen=True)
class InstagramPost5sProjectSettings:
    cta_text: str | None
    image_prompt: str | None


def normalize_cta_text(value: str | None) -> str | None:
    raw_text = str(value or "")
    lines = [" ".join(line.split()) for line in raw_text.replace("\r\n", "\n").split("\n")]
    normalized = "\n".join(line for line in lines if line).strip()
    return normalized[:220] or None


def normalize_image_prompt(value: str | None) -> str | None:
    normalized = " ".join(str(value or "").replace("\r\n", "\n").split()).strip()
    return normalized[:1200] or None


def get_or_create_project_settings(
    db: Session,
    *,
    user_id: int,
    project_id: int,
) -> models.PostMyPostProjectSetting:
    row = (
        db.query(models.PostMyPostProjectSetting)
        .filter(
            models.PostMyPostProjectSetting.user_id == user_id,
            models.PostMyPostProjectSetting.project_id == int(project_id),
        )
        .first()
    )
    if row is None:
        row = models.PostMyPostProjectSetting(user_id=user_id, project_id=int(project_id))
        db.add(row)
    return row


def get_instagram_post_5s_project_settings(
    db: Session,
    *,
    user: models.User,
    project_id: int | None,
) -> InstagramPost5sProjectSettings:
    row = None
    if project_id is not None:
        row = (
            db.query(models.PostMyPostProjectSetting)
            .filter(
                models.PostMyPostProjectSetting.user_id == user.id,
                models.PostMyPostProjectSetting.project_id == int(project_id),
            )
            .first()
        )
    if row is not None:
        row_cta_text = getattr(row, "instagram_post_5s_cta_text", None)
        row_image_prompt = getattr(row, "instagram_post_5s_image_prompt", None)
        return InstagramPost5sProjectSettings(
            cta_text=(
                normalize_cta_text(row_cta_text)
                if row_cta_text is not None
                else normalize_cta_text(getattr(user, "instagram_post_5s_cta_text", None))
            ),
            image_prompt=(
                normalize_image_prompt(row_image_prompt)
                if row_image_prompt is not None
                else normalize_image_prompt(getattr(user, "instagram_post_5s_image_prompt", None))
            ),
        )
    return InstagramPost5sProjectSettings(
        cta_text=normalize_cta_text(getattr(user, "instagram_post_5s_cta_text", None)),
        image_prompt=normalize_image_prompt(getattr(user, "instagram_post_5s_image_prompt", None)),
    )


def set_instagram_post_5s_project_settings(
    db: Session,
    *,
    user: models.User,
    project_id: int,
    cta_text: str | None,
    image_prompt: str | None,
) -> models.PostMyPostProjectSetting:
    row = get_or_create_project_settings(db, user_id=user.id, project_id=project_id)
    row.instagram_post_5s_cta_text = normalize_cta_text(cta_text) or ""
    row.instagram_post_5s_image_prompt = normalize_image_prompt(image_prompt) or ""
    return row
