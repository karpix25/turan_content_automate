from __future__ import annotations

from sqlalchemy.orm import Session

from .. import models

UNIQUEIZATION_MODES = {"auto", "light", "standard", "aggressive", "off"}
DEFAULT_UNIQUEIZATION_MODE = "auto"


def normalize_uniqueization_mode(value: str | None) -> str:
    mode = (value or DEFAULT_UNIQUEIZATION_MODE).strip().lower()
    if mode not in UNIQUEIZATION_MODES:
        raise ValueError(f"Unsupported uniqueization mode: {value}")
    return mode


def get_project_uniqueization_mode(db: Session, user_id: int, project_id: int | None) -> str:
    return DEFAULT_UNIQUEIZATION_MODE


def set_project_uniqueization_mode(
    db: Session,
    *,
    user_id: int,
    project_id: int,
    mode: str | None,
) -> models.PostMyPostProjectSetting:
    normalized_mode = normalize_uniqueization_mode(mode)
    row = (
        db.query(models.PostMyPostProjectSetting)
        .filter(
            models.PostMyPostProjectSetting.user_id == user_id,
            models.PostMyPostProjectSetting.project_id == int(project_id),
        )
        .first()
    )
    if row is None:
        row = models.PostMyPostProjectSetting(
            user_id=user_id,
            project_id=int(project_id),
            uniqueization_mode=normalized_mode,
        )
        db.add(row)
    else:
        row.uniqueization_mode = normalized_mode
    return row


def resolve_output_uniqueization_mode(
    *,
    project_mode: str | None,
    has_duplicate_platform: bool,
) -> str:
    mode = normalize_uniqueization_mode(project_mode)
    if mode != "auto":
        return mode
    return "standard" if has_duplicate_platform else "light"


def uniqueization_variations_enabled(mode: str | None) -> bool:
    return normalize_uniqueization_mode(mode) != "off"
