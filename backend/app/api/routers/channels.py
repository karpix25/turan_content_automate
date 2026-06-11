import os
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ... import models, schemas
from ...core.config import pmp_client
from ...publish_planner import DEFAULT_ACCOUNT_LIMIT_PER_DAY, validate_account_publish_limit
from ...utils.plate_media import get_plate_media_type
from ..deps import get_db, ensure_admin_access, get_or_create_user
from ..utils import normalize_percent

router = APIRouter(prefix="/postmypost", tags=["channels"])

def get_postmypost_project_id() -> int:
    project_id_raw = os.getenv("POSTMYPOST_PROJECT_ID", "").strip()
    project_id = int(project_id_raw) if project_id_raw else None
    return pmp_client.ensure_project_id(project_id)

def get_user_channel_row_map(db: Session, user_id: int) -> dict[int, models.UserPublishChannel]:
    rows = db.query(models.UserPublishChannel).filter(
        models.UserPublishChannel.user_id == user_id
    ).all()
    return {row.account_id: row for row in rows}

def build_postmypost_channels_response(
    db: Session,
    user: models.User,
    accounts: list[dict],
    channels: list[dict],
) -> list[schemas.PostMyPostAccountOut]:
    channels_by_id = {
        int(item["id"]): item
        for item in channels
        if isinstance(item, dict) and item.get("id") is not None
    }
    row_map = get_user_channel_row_map(db, user.id)
    plate_map = {
        plate.id: plate
        for plate in db.query(models.Plate).filter(models.Plate.user_id == user.id).all()
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
        selected_plate_ids = []
        if row and isinstance(row.selected_plate_ids, list):
            selected_plate_ids = [int(item) for item in row.selected_plate_ids if item is not None]
        elif row and row.selected_plate_id is not None:
            selected_plate_ids = [int(row.selected_plate_id)]
        elif user.selected_plate_id is not None:
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
            if not plate:
                continue
            plate_assets.append(
                schemas.PlateAssetOut(
                    id=plate.id,
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

@router.get("/channels/{telegram_id}", response_model=list[schemas.PostMyPostAccountOut])
def get_postmypost_channels(telegram_id: str, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    if not os.getenv("POSTMYPOST_API_KEY", "").strip():
        raise HTTPException(status_code=400, detail="POSTMYPOST_API_KEY is not configured")

    try:
        project_id = get_postmypost_project_id()
        channels = pmp_client.get_channels()
        accounts = pmp_client.get_accounts(project_id=project_id)
    except Exception as e:
        logging.exception(f"CRITICAL: Failed to load PostMyPost channels for user {telegram_id}: {e}")
        raise HTTPException(status_code=502, detail=f"PostMyPost Error: {e}")
    return build_postmypost_channels_response(db=db, user=user, accounts=accounts, channels=channels)

@router.post("/channels/{telegram_id}", response_model=list[schemas.PostMyPostAccountOut])
def update_postmypost_channels(
    telegram_id: str,
    payload: schemas.ChannelPreferenceUpdate,
    db: Session = Depends(get_db)
):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    
    try:
        project_id = get_postmypost_project_id()
        accounts = pmp_client.get_accounts(project_id=project_id)
        channels = pmp_client.get_channels()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to load accounts from PostMyPost: {e}")

    valid_ids = {int(item["id"]) for item in accounts if isinstance(item, dict) and item.get("id") is not None}
    selected_ids = {int(item) for item in (payload.account_ids or [])}.intersection(valid_ids)

    existing_rows = db.query(models.UserPublishChannel).filter(models.UserPublishChannel.user_id == user.id).all()
    existing_by_account = {row.account_id: row for row in existing_rows}

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
        account_plate_ids = [int(p) for p in raw_plate_ids if str(p).isdigit()]
        
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
    return build_postmypost_channels_response(db=db, user=user, accounts=accounts, channels=channels)
