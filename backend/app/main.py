from fastapi import FastAPI, Depends, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from .database import SessionLocal, init_database
from . import models, schemas
from .integrations.postmypost import PostMyPostClient
from .publish_planner import validate_schedule_settings
import os
import logging
import datetime
from urllib.parse import urlparse, parse_qs
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

# Initialize DB
init_database()

celery_client = Celery("api_client", broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"))
pmp_client = PostMyPostClient(api_key=os.getenv("POSTMYPOST_API_KEY", ""))

app = FastAPI(title="Content Processing API")

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


def normalize_source_url(value: str) -> str:
    url = (value or "").strip().strip("<>()[]{}\"'.,;")
    if not url:
        raise HTTPException(status_code=400, detail="source_url is empty")
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    return url


def validate_youtube_url(url: str) -> None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path_parts = [part for part in parsed.path.split("/") if part]

    if "youtu.be" in host:
        if not path_parts or len(path_parts[0]) != 11:
            raise HTTPException(status_code=400, detail="Invalid YouTube short link")
        return

    if "youtube.com" in host:
        if len(path_parts) >= 2 and path_parts[0] == "shorts":
            if len(path_parts[1]) != 11:
                raise HTTPException(status_code=400, detail="Invalid YouTube Shorts ID")
            return
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
            if len(video_id) != 11:
                raise HTTPException(status_code=400, detail="Invalid YouTube watch URL")
            return

def get_postmypost_project_id() -> int:
    project_id_raw = os.getenv("POSTMYPOST_PROJECT_ID", "").strip()
    project_id = int(project_id_raw) if project_id_raw else None
    return pmp_client.ensure_project_id(project_id)

def get_user_channel_enabled_map(db: Session, user_id: int) -> dict[int, bool]:
    rows = db.query(models.UserPublishChannel).filter(
        models.UserPublishChannel.user_id == user_id
    ).all()
    return {row.account_id: bool(row.enabled) for row in rows}


def normalize_ending_platform(value: str | None) -> str:
    platform = (value or "").strip().lower()
    aliases = {
        "ig": "instagram",
        "insta": "instagram",
        "yt": "youtube",
        "you_tube": "youtube",
    }
    platform = aliases.get(platform, platform)
    if platform in {"instagram", "youtube", "universal"}:
        return platform
    raise HTTPException(status_code=400, detail="platform must be one of: instagram, youtube, universal")

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Content processing API is running"}

# User Settings API
@app.get("/settings/{telegram_id}")
def get_settings(telegram_id: str, db: Session = Depends(get_db)):
    user = get_or_create_user(db, telegram_id)
    return user

@app.post("/settings/{telegram_id}/update")
def update_settings(telegram_id: str, settings: schemas.UserSettingsUpdate, db: Session = Depends(get_db)):
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

    for key, value in update_data.items():
        setattr(user, key, value)
    db.commit()
    return {"status": "updated"}

@app.post("/tasks/{telegram_id}")
def create_task(telegram_id: str, payload: schemas.VideoTaskCreate, db: Session = Depends(get_db)):
    user = get_or_create_user(db, telegram_id)
    publish_at = normalize_utc_naive(payload.publish_at)
    source_url = normalize_source_url(payload.source_url)

    if payload.type == "youtube":
        validate_youtube_url(source_url)

    new_task = models.VideoTask(
        user_id=user.id,
        source_url=source_url,
        type=payload.type,
        status="pending",
        publish_at=publish_at,
        publishing_status="scheduled" if publish_at else "not_published"
    )
    db.add(new_task)
    db.commit()
    db.refresh(new_task)

    try:
        celery_client.send_task("process_content_task", args=[new_task.id])
    except Exception as e:
        logging.error(f"Failed to enqueue task {new_task.id}: {e}")
        raise HTTPException(status_code=500, detail="Task created but queue enqueue failed")

    return {"status": "queued", "task_id": new_task.id, "type": payload.type}

@app.get("/postmypost/channels/{telegram_id}", response_model=list[schemas.PostMyPostAccountOut])
def get_postmypost_channels(telegram_id: str, db: Session = Depends(get_db)):
    user = get_or_create_user(db, telegram_id)
    if not os.getenv("POSTMYPOST_API_KEY", "").strip():
        raise HTTPException(status_code=400, detail="POSTMYPOST_API_KEY is not configured")

    try:
        project_id = get_postmypost_project_id()
        channels = pmp_client.get_channels()
        accounts = pmp_client.get_accounts(project_id=project_id)
    except Exception as e:
        logging.error(f"Failed to load PostMyPost channels/accounts: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to load channels from PostMyPost: {e}")

    channels_by_id = {int(item["id"]): item for item in channels if isinstance(item, dict) and item.get("id") is not None}
    enabled_map = get_user_channel_enabled_map(db, user.id)

    result: list[schemas.PostMyPostAccountOut] = []
    for account in accounts:
        account_id = account.get("id")
        if account_id is None:
            continue
        account_id = int(account_id)
        channel_id_raw = account.get("chanel_id", account.get("channel_id"))
        channel_id = int(channel_id_raw) if channel_id_raw is not None else None
        channel_info = channels_by_id.get(channel_id) if channel_id is not None else None

        result.append(
            schemas.PostMyPostAccountOut(
                account_id=account_id,
                account_name=str(account.get("name", f"Account {account_id}")),
                account_login=account.get("login"),
                channel_id=channel_id,
                channel_code=channel_info.get("code") if channel_info else None,
                channel_name=channel_info.get("name") if channel_info else None,
                enabled=enabled_map.get(account_id, True),
            )
        )
    return result

@app.post("/postmypost/channels/{telegram_id}", response_model=list[schemas.PostMyPostAccountOut])
def update_postmypost_channels(
    telegram_id: str,
    payload: schemas.ChannelPreferenceUpdate,
    db: Session = Depends(get_db)
):
    user = get_or_create_user(db, telegram_id)
    selected_ids = {int(item) for item in payload.account_ids}

    try:
        project_id = get_postmypost_project_id()
        accounts = pmp_client.get_accounts(project_id=project_id)
    except Exception as e:
        logging.error(f"Failed to load PostMyPost accounts before update: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to load accounts from PostMyPost: {e}")

    valid_ids = {int(item["id"]) for item in accounts if isinstance(item, dict) and item.get("id") is not None}
    selected_ids = selected_ids.intersection(valid_ids)

    existing_rows = db.query(models.UserPublishChannel).filter(
        models.UserPublishChannel.user_id == user.id
    ).all()
    existing_by_account = {row.account_id: row for row in existing_rows}

    for account_id in valid_ids:
        should_enable = account_id in selected_ids
        row = existing_by_account.get(account_id)
        if row:
            row.enabled = should_enable
        elif should_enable:
            db.add(models.UserPublishChannel(user_id=user.id, account_id=account_id, enabled=True))

    db.commit()
    return get_postmypost_channels(telegram_id=telegram_id, db=db)

@app.get("/tasks/{telegram_id}", response_model=list[schemas.VideoTaskOut])
def list_user_tasks(telegram_id: str, db: Session = Depends(get_db)):
    user = get_or_create_user(db, telegram_id)
    tasks = db.query(models.VideoTask).filter(
        models.VideoTask.user_id == user.id
    ).order_by(models.VideoTask.created_at.desc()).limit(100).all()
    return tasks


@app.get("/tasks/{telegram_id}/{task_id}/file")
def download_task_output(telegram_id: str, task_id: int, db: Session = Depends(get_db)):
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
    user = get_or_create_user(db, telegram_id)
    task = get_user_task_or_404(db, user.id, task_id)

    if task.publishing_status == "published":
        raise HTTPException(status_code=400, detail="Cannot reschedule already published task")

    publish_at = normalize_utc_naive(payload.publish_at)
    task.publish_at = publish_at
    task.publishing_status = "scheduled" if publish_at else "not_published"
    db.commit()

    try:
        if publish_at and task.status == "completed" and task.output_path:
            celery_client.send_task("sync_publication_task", args=[task.id], kwargs={"force_now": False})
        if publish_at is None:
            celery_client.send_task("unschedule_publication_task", args=[task.id])
    except Exception as e:
        logging.error(f"Failed to enqueue schedule sync for task {task.id}: {e}")

    db.refresh(task)
    return task

@app.post("/tasks/{telegram_id}/{task_id}/publish-now", response_model=schemas.VideoTaskOut)
def publish_task_now(telegram_id: str, task_id: int, db: Session = Depends(get_db)):
    user = get_or_create_user(db, telegram_id)
    task = get_user_task_or_404(db, user.id, task_id)

    if task.status != "completed":
        raise HTTPException(status_code=400, detail="Task is not processed yet")
    if not task.output_path:
        raise HTTPException(status_code=400, detail="Task has no rendered output")
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

# File Uploads (Plates & CTA)
@app.post("/upload/plate/{telegram_id}")
async def upload_plate(telegram_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    user = get_or_create_user(db, telegram_id)
    plates_dir = os.getenv("PLATES_DIR", "plates")
    os.makedirs(plates_dir, exist_ok=True)
    file_name = f"{telegram_id}_{file.filename}"
    file_path = os.path.join(plates_dir, file_name)
    
    with open(file_path, "wb") as f:
        f.write(await file.read())
        
    new_plate = models.Plate(user_id=user.id, file_path=file_path)
    db.add(new_plate)
    db.commit()
    return {"status": "uploaded", "plate_id": new_plate.id, "file_path": file_path}

@app.post("/upload/cta/{telegram_id}")
async def upload_cta(
    telegram_id: str,
    label: str = Form(""),
    platform: str = Form("universal"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    user = get_or_create_user(db, telegram_id)
    normalized_platform = normalize_ending_platform(platform)
    cta_dir = os.getenv("CTA_DIR", "cta")
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
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    user = get_or_create_user(db, telegram_id)
    normalized_platform = normalize_ending_platform(platform)
    endings_dir = os.getenv("CTA_DIR", "cta")
    os.makedirs(endings_dir, exist_ok=True)

    file_name = f"{telegram_id}_{normalized_platform}_{file.filename}"
    file_path = os.path.join(endings_dir, file_name)
    with open(file_path, "wb") as f:
        f.write(await file.read())

    ending = models.CTAClip(
        user_id=user.id,
        file_path=file_path,
        label=label or file.filename,
        platform=normalized_platform,
    )
    db.add(ending)
    db.commit()
    db.refresh(ending)
    return ending


@app.get("/endings/{telegram_id}", response_model=list[schemas.EndingClipOut])
def list_endings(telegram_id: str, db: Session = Depends(get_db)):
    user = get_or_create_user(db, telegram_id)
    return db.query(models.CTAClip).filter(
        models.CTAClip.user_id == user.id
    ).order_by(models.CTAClip.id.desc()).all()
