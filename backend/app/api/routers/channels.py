import os
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ... import models, schemas
from ...core.config import pmp_client
from ...publish_planner import DEFAULT_ACCOUNT_LIMIT_PER_DAY, validate_account_publish_limit
from ...utils.plate_media import get_plate_media_type
from ...utils.postmypost_projects import (
    normalize_postmypost_project,
    resolve_user_postmypost_project_id,
)
from ...services.video_uniqueization import (
    get_project_uniqueization_mode,
    normalize_uniqueization_mode,
    set_project_uniqueization_mode,
)
from ..deps import get_db, ensure_admin_access, get_or_create_user
from ..utils import normalize_percent

router = APIRouter(prefix="/postmypost", tags=["channels"])

def get_postmypost_project_id(user: models.User, project_id: int | None = None) -> int:
    return int(project_id) if project_id else resolve_user_postmypost_project_id(user, pmp_client)

def disable_accounts_absent_from_project(
    db: Session,
    user_id: int,
    valid_account_ids: set[int],
    project_id: int,
) -> None:
    existing_rows = db.query(models.UserPublishChannel).filter(
        models.UserPublishChannel.user_id == user_id,
        models.UserPublishChannel.postmypost_project_id == project_id,
    ).all()
    for row in existing_rows:
        if row.account_id not in valid_account_ids and row.enabled:
            logging.warning(
                "Disabling stale PostMyPost account %s for user %s: account is absent from project %s",
                row.account_id,
                user_id,
                project_id,
            )
            row.enabled = False


def build_project_out(
    db: Session,
    user_id: int,
    project: dict,
    selected_project_id: int | None,
) -> schemas.PostMyPostProjectOut:
    normalized_project = normalize_postmypost_project(project, selected_project_id)
    normalized_project["uniqueization_mode"] = get_project_uniqueization_mode(
        db,
        user_id,
        int(normalized_project["id"]),
    )
    return schemas.PostMyPostProjectOut(**normalized_project)

def get_user_channel_row_map(db: Session, user_id: int, project_id: int) -> dict[int, models.UserPublishChannel]:
    rows = db.query(models.UserPublishChannel).filter(
        models.UserPublishChannel.user_id == user_id,
        models.UserPublishChannel.postmypost_project_id == project_id,
    ).all()
    return {row.account_id: row for row in rows}


def _selected_plate_ids(row: models.UserPublishChannel | None) -> list[int]:
    if not row:
        return []
    if isinstance(row.selected_plate_ids, list):
        return [int(item) for item in row.selected_plate_ids if item is not None]
    if row.selected_plate_id is not None:
        return [int(row.selected_plate_id)]
    return []


def _project_row_has_custom_settings(row: models.UserPublishChannel) -> bool:
    return any(
        [
            bool(row.enabled),
            bool((row.publication_description or "").strip()),
            validate_account_publish_limit(row.publish_limit_per_day) != DEFAULT_ACCOUNT_LIMIT_PER_DAY,
            bool(_selected_plate_ids(row)),
            row.plate_start_percent not in (None, 25),
        ]
    )


def migrate_legacy_project_assets(
    db: Session,
    user: models.User,
    project_id: int,
    valid_account_ids: set[int],
) -> None:
    legacy_rows = db.query(models.UserPublishChannel).filter(
        models.UserPublishChannel.user_id == user.id,
        models.UserPublishChannel.postmypost_project_id.is_(None),
        models.UserPublishChannel.account_id.in_(valid_account_ids or {-1}),
    ).all()
    if not legacy_rows:
        return

    project_rows = db.query(models.UserPublishChannel).filter(
        models.UserPublishChannel.user_id == user.id,
        models.UserPublishChannel.postmypost_project_id == project_id,
        models.UserPublishChannel.account_id.in_(valid_account_ids or {-1}),
    ).all()
    project_by_account = {row.account_id: row for row in project_rows}
    changed = False

    for legacy in legacy_rows:
        legacy_plate_ids = _selected_plate_ids(legacy)
        row = project_by_account.get(legacy.account_id)
        if row is None:
            row = models.UserPublishChannel(
                user_id=user.id,
                postmypost_project_id=project_id,
                account_id=legacy.account_id,
            )
            db.add(row)
            project_by_account[legacy.account_id] = row
            changed = True
        elif _project_row_has_custom_settings(row):
            continue

        row.enabled = legacy.enabled
        row.publication_description = legacy.publication_description
        row.publish_limit_per_day = validate_account_publish_limit(legacy.publish_limit_per_day)
        row.selected_plate_ids = legacy_plate_ids
        row.selected_plate_id = legacy_plate_ids[0] if legacy_plate_ids else None
        row.plate_start_percent = legacy.plate_start_percent
        changed = True

        if legacy_plate_ids:
            db.query(models.Plate).filter(
                models.Plate.user_id == user.id,
                models.Plate.id.in_(legacy_plate_ids),
                models.Plate.postmypost_project_id.is_(None),
            ).update(
                {
                    models.Plate.postmypost_project_id: project_id,
                    models.Plate.account_id: legacy.account_id,
                },
                synchronize_session=False,
            )
            changed = True

    migrated_endings = db.query(models.CTAClip).filter(
        models.CTAClip.user_id == user.id,
        models.CTAClip.postmypost_project_id.is_(None),
        models.CTAClip.account_id.in_(valid_account_ids or {-1}),
    ).update({models.CTAClip.postmypost_project_id: project_id}, synchronize_session=False)
    changed = changed or bool(migrated_endings)

    if changed:
        logging.info(
            "Migrated legacy PostMyPost channel assets for user=%s project=%s accounts=%s",
            user.id,
            project_id,
            sorted(valid_account_ids),
        )
        db.commit()


def build_postmypost_channels_response(
    db: Session,
    user: models.User,
    project_id: int,
    accounts: list[dict],
    channels: list[dict],
) -> list[schemas.PostMyPostAccountOut]:
    channels_by_id = {
        int(item["id"]): item
        for item in channels
        if isinstance(item, dict) and item.get("id") is not None
    }
    row_map = get_user_channel_row_map(db, user.id, project_id)
    plate_map = {
        plate.id: plate
        for plate in db.query(models.Plate).filter(
            models.Plate.user_id == user.id,
            models.Plate.postmypost_project_id == project_id,
        ).all()
    }

    result: list[schemas.PostMyPostAccountOut] = []
    for account in accounts:
        account_id = account.get("id")
        if account_id is None:
            continue
        account_id = int(account_id)
        channel_id_raw = account.get("chanel_id", account.get("channel_id"))
        channel_id = int(channel_id_raw) if channel_id_raw is not None else None
        channel_info = channels_by_id.get(channel_id) if channel_id is not None else None

        row = row_map.get(account_id)
        selected_plate_ids = _selected_plate_ids(row)
        if not selected_plate_ids and user.selected_plate_id is not None:
            selected_plate_ids = [int(user.selected_plate_id)]

        selected_plate_id = selected_plate_ids[0] if selected_plate_ids else None
        plate_start_percent = (
            row.plate_start_percent
            if row and row.plate_start_percent is not None
            else user.plate_start_percent
        )
        plate_assets = []
        for plate_id in selected_plate_ids:
            plate = plate_map.get(int(plate_id))
            if not plate or plate.account_id != account_id:
                continue
            plate_assets.append(
                schemas.PlateAssetOut(
                    id=plate.id,
                    postmypost_project_id=plate.postmypost_project_id,
                    account_id=plate.account_id,
                    file_path=plate.file_path,
                    media_type=get_plate_media_type(plate.file_path),
                )
            )
        plate_file_path = plate_assets[0].file_path if plate_assets else None
        result.append(
            schemas.PostMyPostAccountOut(
                account_id=account_id,
                account_name=str(account.get("name", f"Account {account_id}")),
                account_login=account.get("login"),
                channel_id=channel_id,
                channel_code=channel_info.get("code") if channel_info else None,
                channel_name=channel_info.get("name") if channel_info else None,
                enabled=bool(row.enabled) if row else False,
                description=(row.publication_description if row else None),
                publish_limit_per_day=validate_account_publish_limit(
                    row.publish_limit_per_day if row else DEFAULT_ACCOUNT_LIMIT_PER_DAY
                ),
                selected_plate_id=selected_plate_id,
                selected_plate_ids=selected_plate_ids,
                plate_start_percent=plate_start_percent,
                plate_file_path=plate_file_path,
                plate_assets=plate_assets,
            )
        )
    return result

@router.get("/projects/{telegram_id}", response_model=schemas.PostMyPostProjectsOut)
def get_postmypost_projects(telegram_id: str, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    if not os.getenv("POSTMYPOST_API_KEY", "").strip():
        raise HTTPException(status_code=400, detail="POSTMYPOST_API_KEY is not configured")

    try:
        projects = pmp_client.get_projects()
        selected_project_id = get_postmypost_project_id(user) if projects else None
        selected_mode = get_project_uniqueization_mode(db, user.id, selected_project_id)
    except Exception as e:
        logging.exception(f"CRITICAL: Failed to load PostMyPost projects for user {telegram_id}: {e}")
        raise HTTPException(status_code=502, detail=f"PostMyPost Error: {e}")

    return schemas.PostMyPostProjectsOut(
        selected_project_id=selected_project_id,
        selected_project_uniqueization_mode=selected_mode,
        projects=[
            build_project_out(db, user.id, project, selected_project_id)
            for project in projects
            if isinstance(project, dict) and project.get("id") is not None
        ],
    )

@router.post("/projects/{telegram_id}", response_model=schemas.PostMyPostProjectsOut)
def update_postmypost_project(
    telegram_id: str,
    payload: schemas.PostMyPostProjectUpdate,
    db: Session = Depends(get_db),
):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)

    try:
        projects = pmp_client.get_projects()
        project_ids = {
            int(project["id"])
            for project in projects
            if isinstance(project, dict) and project.get("id") is not None
        }
        selected_project_id = int(payload.project_id)
        if selected_project_id not in project_ids:
            raise HTTPException(status_code=400, detail="PostMyPost project is not available for this API key")

        accounts = pmp_client.get_accounts(project_id=selected_project_id)
        valid_account_ids = {
            int(account["id"])
            for account in accounts
            if isinstance(account, dict) and account.get("id") is not None
        }
        user.postmypost_project_id = selected_project_id
        migrate_legacy_project_assets(db, user, selected_project_id, valid_account_ids)
        if payload.uniqueization_mode is not None:
            set_project_uniqueization_mode(
                db,
                user_id=user.id,
                project_id=selected_project_id,
                mode=payload.uniqueization_mode,
            )
        selected_mode = get_project_uniqueization_mode(db, user.id, selected_project_id)
        disable_accounts_absent_from_project(db, user.id, valid_account_ids, selected_project_id)
        db.commit()
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logging.exception(f"CRITICAL: Failed to update PostMyPost project for user {telegram_id}: {e}")
        raise HTTPException(status_code=502, detail=f"PostMyPost Error: {e}")

    return schemas.PostMyPostProjectsOut(
        selected_project_id=selected_project_id,
        selected_project_uniqueization_mode=selected_mode,
        projects=[
            build_project_out(db, user.id, project, selected_project_id)
            for project in projects
            if isinstance(project, dict) and project.get("id") is not None
        ],
    )

@router.get("/channels/{telegram_id}", response_model=list[schemas.PostMyPostAccountOut])
def get_postmypost_channels(telegram_id: str, project_id: int | None = None, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    if not os.getenv("POSTMYPOST_API_KEY", "").strip():
        raise HTTPException(status_code=400, detail="POSTMYPOST_API_KEY is not configured")

    try:
        project_id = get_postmypost_project_id(user, project_id)
        channels = pmp_client.get_channels()
        accounts = pmp_client.get_accounts(project_id=project_id)
        valid_account_ids = {
            int(account["id"])
            for account in accounts
            if isinstance(account, dict) and account.get("id") is not None
        }
        migrate_legacy_project_assets(db, user, project_id, valid_account_ids)
    except Exception as e:
        logging.exception(f"CRITICAL: Failed to load PostMyPost channels for user {telegram_id}: {e}")
        raise HTTPException(status_code=502, detail=f"PostMyPost Error: {e}")
    return build_postmypost_channels_response(db=db, user=user, project_id=project_id, accounts=accounts, channels=channels)

@router.post("/channels/{telegram_id}", response_model=list[schemas.PostMyPostAccountOut])
def update_postmypost_channels(
    telegram_id: str,
    payload: schemas.ChannelPreferenceUpdate,
    project_id: int | None = None,
    db: Session = Depends(get_db)
):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    
    try:
        project_id = get_postmypost_project_id(user, project_id)
        accounts = pmp_client.get_accounts(project_id=project_id)
        channels = pmp_client.get_channels()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to load accounts from PostMyPost: {e}")

    valid_ids = {int(item["id"]) for item in accounts if isinstance(item, dict) and item.get("id") is not None}
    selected_ids = {int(item) for item in (payload.account_ids or [])}.intersection(valid_ids)

    existing_rows = db.query(models.UserPublishChannel).filter(
        models.UserPublishChannel.user_id == user.id,
        models.UserPublishChannel.postmypost_project_id == project_id,
    ).all()
    existing_by_account = {row.account_id: row for row in existing_rows}
    disable_accounts_absent_from_project(db, user.id, valid_ids, project_id)

    # Normalize data from payload
    descriptions = payload.descriptions or {}
    publish_limits = payload.publish_limits_per_day or {}
    plate_ids_map = payload.selected_plate_ids or {}
    percents_map = payload.plate_start_percents or {}

    for account_id in valid_ids:
        should_enable = account_id in selected_ids
        row = existing_by_account.get(account_id)
        
        account_desc = (descriptions.get(str(account_id)) or "").strip() or None
        raw_limit = publish_limits.get(str(account_id))
        account_limit = validate_account_publish_limit(raw_limit) if raw_limit not in (None, "") else DEFAULT_ACCOUNT_LIMIT_PER_DAY
        
        raw_plate_ids = plate_ids_map.get(str(account_id), [])
        requested_plate_ids = [int(p) for p in raw_plate_ids if str(p).isdigit()]
        valid_plate_rows = db.query(models.Plate).filter(
            models.Plate.user_id == user.id,
            models.Plate.postmypost_project_id == project_id,
            models.Plate.account_id == account_id,
            models.Plate.id.in_(requested_plate_ids or [-1]),
        ).all()
        account_plate_ids = [int(plate.id) for plate in valid_plate_rows]
        
        raw_percent = percents_map.get(str(account_id))
        account_percent = normalize_percent(raw_percent, field_name="plate_start_percent") if raw_percent not in (None, "") else None

        if row:
            row.enabled = should_enable
            if str(account_id) in descriptions: row.publication_description = account_desc
            if str(account_id) in publish_limits: row.publish_limit_per_day = account_limit
            if str(account_id) in plate_ids_map:
                row.selected_plate_ids = account_plate_ids
                row.selected_plate_id = account_plate_ids[0] if account_plate_ids else None
            if str(account_id) in percents_map: row.plate_start_percent = account_percent
        else:
            db.add(
                models.UserPublishChannel(
                    user_id=user.id,
                    postmypost_project_id=project_id,
                    account_id=account_id,
                    enabled=should_enable,
                    publication_description=account_desc,
                    publish_limit_per_day=account_limit,
                    selected_plate_ids=account_plate_ids,
                    selected_plate_id=account_plate_ids[0] if account_plate_ids else None,
                    plate_start_percent=account_percent,
                )
            )

    db.commit()
    return build_postmypost_channels_response(db=db, user=user, project_id=project_id, accounts=accounts, channels=channels)
