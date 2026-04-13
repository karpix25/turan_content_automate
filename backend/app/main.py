from fastapi import FastAPI, Depends, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from .database import SessionLocal, init_database
from . import models, schemas
from .integrations.postmypost import PostMyPostClient
from .publish_planner import validate_schedule_settings
from .telegram_progress import update_task_status_message
import os
import logging
import datetime
import re
from urllib.parse import urlparse, parse_qs
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

# Initialize DB
init_database()

celery_client = Celery("api_client", broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"))
pmp_client = PostMyPostClient(api_key=os.getenv("POSTMYPOST_API_KEY", ""))

app = FastAPI(title="Content Processing API")


def _parse_csv_env(value: str | None) -> list[str]:
    raw = (value or "").strip()
    if not raw:
        return []
    parts = re.split(r"[,\n; ]+", raw)
    return [item.strip() for item in parts if item.strip()]


def get_allowed_cors_origins() -> list[str]:
    return _parse_csv_env(os.getenv("CORS_ALLOWED_ORIGINS"))


def get_telegram_admin_ids() -> set[str]:
    return {item for item in _parse_csv_env(os.getenv("TELEGRAM_ADMIN_IDS")) if item.isdigit()}


allowed_cors_origins = get_allowed_cors_origins()
if allowed_cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Authorization", "Content-Type", "X-Requested-With"],
    )

telegram_admin_ids = get_telegram_admin_ids()

@app.on_event("startup")
async def startup_event():
    logging.info("--- Backend Startup Configuration ---")
    if not telegram_admin_ids:
        logging.warning("TELEGRAM_ADMIN_IDS is not configured. Admin endpoints are publicly accessible!")
    else:
        logging.info(f"Loaded {len(telegram_admin_ids)} admin IDs: {', '.join(list(telegram_admin_ids)[:5])}{'...' if len(telegram_admin_ids) > 5 else ''}")
    
    pmp_key = os.getenv("POSTMYPOST_API_KEY", "").strip()
    if not pmp_key or pmp_key == "your_postmypost_key":
        logging.error("POSTMYPOST_API_KEY is missing or contains placeholder value!")
    else:
        # Mask the key for logs
        masked_key = pmp_key[:4] + "*" * (len(pmp_key) - 8) + pmp_key[-4:] if len(pmp_key) > 8 else "****"
        logging.info(f"POSTMYPOST_API_KEY is configured: {masked_key}")
    
    pmp_project = os.getenv("POSTMYPOST_PROJECT_ID", "").strip()
    logging.info(f"POSTMYPOST_PROJECT_ID: {pmp_project or 'Not set (will use default from API)')}")
    logging.info("-------------------------------------")



def ensure_admin_access(telegram_id: str) -> None:
    if not telegram_admin_ids:
        logging.warning("TELEGRAM_ADMIN_IDS is empty; admin endpoints are not restricted")
        return
    if str(telegram_id).strip() not in telegram_admin_ids:
        raise HTTPException(status_code=403, detail="Access denied")

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_or_create_user(db: Session, telegram_id: str) -> models.User:
    user = db.query(models.User).filter(models.User.telegram_id == telegram_id).first()
    if user:
        return user
    user = models.User(telegram_id=telegram_id)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

def normalize_utc_naive(value: datetime.datetime | None) -> datetime.datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return value

def get_user_task_or_404(db: Session, user_id: int, task_id: int) -> models.VideoTask:
    task = db.query(models.VideoTask).filter(
        models.VideoTask.id == task_id,
        models.VideoTask.user_id == user_id
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def resolve_output_file_path(output_path: str) -> str | None:
    value = (output_path or "").strip()
    if not value:
        return None

    candidates: list[str] = []
    if os.path.isabs(value):
        candidates.append(value)
    else:
        normalized = value.lstrip("./")
        candidates.extend(
            [
                os.path.abspath(value),
                os.path.join("/app", normalized),
                os.path.join("/app/database/media/output", os.path.basename(normalized)),
            ]
        )

    seen: set[str] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        if os.path.isfile(path):
            return path
    return None


def extract_vizard_project_id(url: str) -> str | None:
    raw = (url or "").strip()
    match = re.search(r"vizard\.ai/(?:project|dashboard/editor)/(\d+)", raw, re.IGNORECASE)
    if match:
        return match.group(1)
    if raw.isdigit():
        return raw
    return None


def normalize_source_url(value: str, task_type: str | None = None) -> str:
    url = (value or "").strip().strip("<>()[]{}\"'.,;")
    if not url:
        raise HTTPException(status_code=400, detail="source_url is empty")
    
    t_type = (task_type or "").strip().lower()
    if t_type == "youtube":
        return normalize_youtube_url(url)
    if t_type == "vizard":
        v_id = extract_vizard_project_id(url)
        if v_id:
            return v_id
            
    if not url.startswith(("http://", "https://")) and not url.isdigit():
        url = f"https://{url}"
    return url



def extract_youtube_video_id(url: str) -> str | None:
    raw = (url or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", raw):
        return raw

    parsed = urlparse(raw)
    host = parsed.netloc.lower()
    path_parts = [part for part in parsed.path.split("/") if part]

    if "youtu.be" in host:
        candidate = path_parts[0] if path_parts else ""
        return candidate if len(candidate) == 11 else None

    if "youtube.com" in host:
        if len(path_parts) >= 2 and path_parts[0] == "shorts":
            candidate = path_parts[1]
            return candidate if len(candidate) == 11 else None
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [""])[0]
            return candidate if len(candidate) == 11 else None

    return None


def normalize_youtube_url(url: str) -> str:
    raw = (url or "").strip()
    video_id = extract_youtube_video_id(raw)
    if not video_id:
        return raw

    if re.fullmatch(r"[A-Za-z0-9_-]{11}", raw):
        return f"https://www.youtube.com/watch?v={video_id}"

    parsed = urlparse(raw)
    host = parsed.netloc.lower()
    path_parts = [part for part in parsed.path.split("/") if part]

    if "youtube.com" in host and len(path_parts) >= 2 and path_parts[0] == "shorts":
        return f"https://www.youtube.com/shorts/{video_id}"

    return f"https://www.youtube.com/watch?v={video_id}"


def validate_youtube_url(url: str) -> None:
    if extract_youtube_video_id(url) is None:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

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
            plate_assets.append(schemas.PlateAssetOut(id=plate.id, file_path=plate.file_path))
        plate_file_path = plate_assets[0].file_path if plate_assets else None
        result.append(
            schemas.PostMyPostAccountOut(
                account_id=account_id,
                account_name=str(account.get("name", f"Account {account_id}")),
                account_login=account.get("login"),
                channel_id=channel_id,
                channel_code=channel_info.get("code") if channel_info else None,
                channel_name=channel_info.get("name") if channel_info else None,
                enabled=bool(row.enabled) if row else True,
                description=(row.publication_description if row else None),
                selected_plate_id=selected_plate_id,
                selected_plate_ids=selected_plate_ids,
                plate_start_percent=plate_start_percent,
                plate_file_path=plate_file_path,
                plate_assets=plate_assets,
            )
        )
    return result


def normalize_ending_platform(value: str | None) -> str:
    platform = (value or "").strip().lower()
    aliases = {
        "ig": "instagram",
        "insta": "instagram",
        "yt": "youtube",
        "you_tube": "youtube",
        "tt": "tiktok",
    }
    platform = aliases.get(platform, platform)
    if platform in {"instagram", "youtube", "tiktok", "universal"}:
        return platform
    raise HTTPException(status_code=400, detail="platform must be one of: instagram, youtube, tiktok, universal")


def parse_optional_account_id(value: str | None) -> int | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="account_id must be an integer")


def normalize_percent(value: int | None, *, field_name: str) -> int:
    if value is None:
        raise HTTPException(status_code=400, detail=f"{field_name} is required")
    if value < 0 or value > 100:
        raise HTTPException(status_code=400, detail=f"{field_name} must be between 0 and 100")
    return int(value)

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Content processing API is running"}

# User Settings API
@app.get("/settings/{telegram_id}")
def get_settings(telegram_id: str, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    return user

@app.post("/settings/{telegram_id}/update")
def update_settings(telegram_id: str, settings: schemas.UserSettingsUpdate, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    update_data = settings.dict(exclude_unset=True)

    has_schedule_fields = any(
        key in update_data
        for key in ("publish_limit_per_day", "publish_window_start_msk", "publish_window_end_msk")
    )
    if has_schedule_fields:
        try:
            normalized_limit, normalized_start, normalized_end = validate_schedule_settings(
                update_data.get("publish_limit_per_day", user.publish_limit_per_day),
                update_data.get("publish_window_start_msk", user.publish_window_start_msk),
                update_data.get("publish_window_end_msk", user.publish_window_end_msk),
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        update_data["publish_limit_per_day"] = normalized_limit
        update_data["publish_window_start_msk"] = normalized_start
        update_data["publish_window_end_msk"] = normalized_end

    if "plate_start_percent" in update_data:
        update_data["plate_start_percent"] = normalize_percent(
            update_data.get("plate_start_percent"),
            field_name="plate_start_percent",
        )

    for key, value in update_data.items():
        setattr(user, key, value)
    db.commit()
    return {"status": "updated"}

@app.post("/tasks/{telegram_id}")
def create_task(telegram_id: str, payload: schemas.VideoTaskCreate, db: Session = Depends(get_db)):
    user = get_or_create_user(db, telegram_id)
    publish_at = normalize_utc_naive(payload.publish_at)
    source_url = normalize_source_url(payload.source_url, payload.type)

    if payload.type == "youtube":
        validate_youtube_url(source_url)

    new_task = models.VideoTask(
        user_id=user.id,
        source_url=source_url,
        type=payload.type,
        status="pending",
        publish_at=publish_at,
        publishing_status="scheduled" if publish_at else "not_published",
        telegram_chat_id=(payload.telegram_chat_id or "").strip() or None,
        telegram_status_message_id=(payload.telegram_status_message_id or "").strip() or None,
    )
    db.add(new_task)
    db.commit()
    db.refresh(new_task)

    update_task_status_message(
        db,
        new_task,
        stage="Задача создана",
        detail="Видео добавлено в очередь обработки.",
    )

    try:
        celery_client.send_task("process_content_task", args=[new_task.id])
    except Exception as e:
        logging.error(f"Failed to enqueue task {new_task.id}: {e}")
        raise HTTPException(status_code=500, detail="Task created but queue enqueue failed")

    return {"status": "queued", "task_id": new_task.id, "type": payload.type}

@app.get("/postmypost/channels/{telegram_id}", response_model=list[schemas.PostMyPostAccountOut])
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
        logging.exception(f"CRITICAL: Failed to load PostMyPost channels/accounts for user {telegram_id}: {e}")
        # Provide better detail to UI
        error_detail = str(e)
        if hasattr(e, 'response') and hasattr(e.response, 'text'):
            error_detail += f" | API Response: {e.response.text[:200]}"
            
        raise HTTPException(
            status_code=502, 
            detail=f"PostMyPost Error: {error_detail}"
        )
    return build_postmypost_channels_response(db=db, user=user, accounts=accounts, channels=channels)


@app.post("/postmypost/channels/{telegram_id}", response_model=list[schemas.PostMyPostAccountOut])
def update_postmypost_channels(
    telegram_id: str,
    payload: schemas.ChannelPreferenceUpdate,
    db: Session = Depends(get_db)
):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    selected_ids = {int(item) for item in (payload.account_ids or [])}
    descriptions_raw = payload.descriptions or {}
    selected_plate_ids_raw = payload.selected_plate_ids or {}
    plate_start_percents_raw = payload.plate_start_percents or {}

    try:
        project_id = get_postmypost_project_id()
        accounts = pmp_client.get_accounts(project_id=project_id)
        channels = pmp_client.get_channels()
    except Exception as e:
        logging.error(f"Failed to load PostMyPost accounts before update: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to load accounts from PostMyPost: {e}")

    valid_ids = {int(item["id"]) for item in accounts if isinstance(item, dict) and item.get("id") is not None}
    selected_ids = selected_ids.intersection(valid_ids)

    existing_rows = db.query(models.UserPublishChannel).filter(
        models.UserPublishChannel.user_id == user.id
    ).all()
    existing_by_account = {row.account_id: row for row in existing_rows}

    normalized_descriptions: dict[int, str | None] = {}
    normalized_selected_plate_ids: dict[int, list[int]] = {}
    normalized_plate_start_percents: dict[int, int | None] = {}
    for key, value in descriptions_raw.items():
        try:
            account_id = int(key)
        except (TypeError, ValueError):
            continue
        if account_id not in valid_ids:
            continue
        text_value = (value or "").strip()
        normalized_descriptions[account_id] = text_value if text_value else None

    for key, value in selected_plate_ids_raw.items():
        try:
            account_id = int(key)
        except (TypeError, ValueError):
            continue
        if account_id not in valid_ids:
            continue
        raw_items = value if isinstance(value, list) else []
        normalized_items: list[int] = []
        for item in raw_items:
            try:
                normalized_items.append(int(item))
            except (TypeError, ValueError):
                continue
        normalized_selected_plate_ids[account_id] = list(dict.fromkeys(normalized_items))

    for key, value in plate_start_percents_raw.items():
        try:
            account_id = int(key)
        except (TypeError, ValueError):
            continue
        if account_id not in valid_ids:
            continue
        if value in (None, ""):
            normalized_plate_start_percents[account_id] = None
            continue
        normalized_plate_start_percents[account_id] = normalize_percent(value, field_name="plate_start_percent")

    for account_id in valid_ids:
        should_enable = account_id in selected_ids
        account_description = normalized_descriptions.get(account_id)
        row = existing_by_account.get(account_id)
        if row:
            row.enabled = should_enable
            if account_id in normalized_descriptions:
                row.publication_description = account_description
            if account_id in normalized_selected_plate_ids:
                row.selected_plate_ids = normalized_selected_plate_ids[account_id]
                row.selected_plate_id = normalized_selected_plate_ids[account_id][0] if normalized_selected_plate_ids[account_id] else None
            if account_id in normalized_plate_start_percents:
                row.plate_start_percent = normalized_plate_start_percents[account_id]
        elif (
            should_enable
            or account_id in normalized_descriptions
            or account_id in normalized_selected_plate_ids
            or account_id in normalized_plate_start_percents
        ):
            db.add(
                models.UserPublishChannel(
                    user_id=user.id,
                    account_id=account_id,
                    enabled=should_enable,
                    publication_description=account_description,
                    selected_plate_ids=normalized_selected_plate_ids.get(account_id),
                    selected_plate_id=(normalized_selected_plate_ids.get(account_id) or [None])[0],
                    plate_start_percent=normalized_plate_start_percents.get(account_id),
                )
            )

    db.commit()
    return build_postmypost_channels_response(db=db, user=user, accounts=accounts, channels=channels)

@app.get("/tasks/{telegram_id}", response_model=list[schemas.VideoTaskOut])
def list_user_tasks(telegram_id: str, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    tasks = db.query(models.VideoTask).filter(
        models.VideoTask.user_id == user.id
    ).order_by(models.VideoTask.created_at.desc()).limit(100).all()
    return tasks


@app.get("/tasks/{telegram_id}/{task_id}/file")
def download_task_output(telegram_id: str, task_id: int, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    task = get_user_task_or_404(db, user.id, task_id)

    if not task.output_path:
        raise HTTPException(status_code=400, detail="Task has no rendered output yet")

    resolved_path = resolve_output_file_path(task.output_path)
    if not resolved_path:
        raise HTTPException(status_code=404, detail="Rendered file not found on disk")

    return FileResponse(
        path=resolved_path,
        filename=os.path.basename(resolved_path),
        media_type="video/mp4",
    )

@app.patch("/tasks/{telegram_id}/{task_id}/schedule", response_model=schemas.VideoTaskOut)
def update_task_schedule(
    telegram_id: str,
    task_id: int,
    payload: schemas.VideoTaskScheduleUpdate,
    db: Session = Depends(get_db)
):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    task = get_user_task_or_404(db, user.id, task_id)

    if task.publishing_status == "published":
        raise HTTPException(status_code=400, detail="Cannot reschedule already published task")

    publish_at = normalize_utc_naive(payload.publish_at)
    task.publish_at = publish_at
    task.publishing_status = "scheduled" if publish_at else "not_published"
    db.commit()

    try:
        if publish_at and task.status == "completed" and (task.output_path or task.postmypost_file_id):
            celery_client.send_task("sync_publication_task", args=[task.id], kwargs={"force_now": False})
        if publish_at is None:
            celery_client.send_task("unschedule_publication_task", args=[task.id])
    except Exception as e:
        logging.error(f"Failed to enqueue schedule sync for task {task.id}: {e}")

    db.refresh(task)
    return task

@app.post("/tasks/{telegram_id}/{task_id}/publish-now", response_model=schemas.VideoTaskOut)
def publish_task_now(telegram_id: str, task_id: int, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    task = get_user_task_or_404(db, user.id, task_id)

    if task.status != "completed":
        raise HTTPException(status_code=400, detail="Task is not processed yet")
    if not task.output_path and not task.postmypost_file_id:
        raise HTTPException(status_code=400, detail="Task has no render output or uploaded PostMyPost file")
    if task.publishing_status == "published":
        raise HTTPException(status_code=400, detail="Task already published")

    task.publish_at = datetime.datetime.utcnow()
    task.publishing_status = "in_progress"
    db.commit()

    try:
        celery_client.send_task("sync_publication_task", args=[task.id], kwargs={"force_now": True})
    except Exception as e:
        logging.error(f"Failed to enqueue publish-now for task {task.id}: {e}")
        task.publishing_status = "failed"
        db.commit()
        raise HTTPException(status_code=500, detail="Queue enqueue failed")

    db.refresh(task)
    return task

@app.delete("/tasks/{telegram_id}/{task_id}")
def delete_task(telegram_id: str, task_id: int, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    task = get_user_task_or_404(db, user.id, task_id)
    db.delete(task)
    db.commit()
    return {"ok": True}

# File Uploads (Plates & CTA)
@app.post("/upload/plate/{telegram_id}", response_model=schemas.PlateAssetOut)
async def upload_plate(telegram_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    plates_dir = os.getenv("PLATES_DIR", "/app/database/media/plates")
    os.makedirs(plates_dir, exist_ok=True)
    file_name = f"{telegram_id}_{file.filename}"
    file_path = os.path.join(plates_dir, file_name)
    
    with open(file_path, "wb") as f:
        f.write(await file.read())
        
    new_plate = models.Plate(user_id=user.id, file_path=file_path)
    db.add(new_plate)
    db.commit()
    db.refresh(new_plate)
    return schemas.PlateAssetOut(id=new_plate.id, file_path=file_path)


@app.delete("/plates/{telegram_id}/{plate_id}")
def delete_plate(telegram_id: str, plate_id: int, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    plate = db.query(models.Plate).filter(
        models.Plate.id == plate_id,
        models.Plate.user_id == user.id,
    ).first()
    if not plate:
        raise HTTPException(status_code=404, detail="Plate not found")

    for row in db.query(models.UserPublishChannel).filter(models.UserPublishChannel.user_id == user.id).all():
        plate_ids = [int(item) for item in (row.selected_plate_ids or []) if item is not None]
        if plate_id in plate_ids:
            plate_ids = [item for item in plate_ids if item != plate_id]
            row.selected_plate_ids = plate_ids
            row.selected_plate_id = plate_ids[0] if plate_ids else None
        elif row.selected_plate_id == plate_id:
            row.selected_plate_id = None
    if user.selected_plate_id == plate_id:
        user.selected_plate_id = None

    file_path = plate.file_path
    db.delete(plate)
    db.commit()

    if file_path and os.path.isfile(file_path):
        try:
            os.remove(file_path)
        except OSError:
            logging.warning("Failed to remove plate file: %s", file_path)

    return {"status": "deleted", "plate_id": plate_id}

@app.post("/upload/cta/{telegram_id}")
async def upload_cta(
    telegram_id: str,
    label: str = Form(""),
    platform: str = Form("universal"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    normalized_platform = normalize_ending_platform(platform)
    cta_dir = os.getenv("CTA_DIR", "/app/database/media/cta")
    os.makedirs(cta_dir, exist_ok=True)
    file_name = f"{telegram_id}_{normalized_platform}_{file.filename}"
    file_path = os.path.join(cta_dir, file_name)
    
    with open(file_path, "wb") as f:
        f.write(await file.read())
        
    new_cta = models.CTAClip(
        user_id=user.id,
        file_path=file_path,
        label=label or file.filename,
        platform=normalized_platform,
    )
    db.add(new_cta)
    db.commit()
    return {"status": "uploaded", "cta_id": new_cta.id, "file_path": file_path}


@app.post("/upload/ending/{telegram_id}", response_model=schemas.EndingClipOut)
async def upload_ending(
    telegram_id: str,
    platform: str = Form(...),
    label: str = Form(""),
    account_id: str = Form(""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    normalized_platform = normalize_ending_platform(platform)
    normalized_account_id = parse_optional_account_id(account_id)
    endings_dir = os.getenv("CTA_DIR", "/app/database/media/cta")
    os.makedirs(endings_dir, exist_ok=True)

    account_segment = f"_a{normalized_account_id}" if normalized_account_id is not None else ""
    file_name = f"{telegram_id}_{normalized_platform}{account_segment}_{file.filename}"
    file_path = os.path.join(endings_dir, file_name)
    with open(file_path, "wb") as f:
        f.write(await file.read())

    ending = models.CTAClip(
        user_id=user.id,
        account_id=normalized_account_id,
        file_path=file_path,
        label=label or file.filename,
        platform=normalized_platform,
    )
    db.add(ending)
    db.commit()
    db.refresh(ending)
    return ending


@app.delete("/endings/{telegram_id}/{ending_id}")
def delete_ending(telegram_id: str, ending_id: int, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    ending = db.query(models.CTAClip).filter(
        models.CTAClip.id == ending_id,
        models.CTAClip.user_id == user.id,
    ).first()
    if not ending:
        raise HTTPException(status_code=404, detail="Ending not found")

    file_path = ending.file_path
    db.delete(ending)
    db.commit()

    if file_path and os.path.isfile(file_path):
        try:
            os.remove(file_path)
        except OSError:
            logging.warning("Failed to remove ending file: %s", file_path)

    return {"status": "deleted", "ending_id": ending_id}


@app.get("/endings/{telegram_id}", response_model=list[schemas.EndingClipOut])
def list_endings(telegram_id: str, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    return db.query(models.CTAClip).filter(
        models.CTAClip.user_id == user.id
    ).order_by(models.CTAClip.account_id.asc().nullsfirst(), models.CTAClip.id.desc()).all()
