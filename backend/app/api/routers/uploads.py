import os
import uuid
import logging
import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from ... import models, schemas
from ...core.config import celery_client
from ...telegram_progress import update_task_status_message
from ..deps import get_db, ensure_admin_access, get_or_create_user
from ..utils import _build_safe_upload_filename, normalize_ending_platform, parse_optional_account_id

router = APIRouter(tags=["assets"])


def _thumbnail_assets_dir() -> str:
    target = (os.getenv("THUMBNAILS_DIR") or "/app/database/media/thumbnails").strip()
    os.makedirs(target, exist_ok=True)
    return target


def _validate_thumbnail_file(file: UploadFile) -> str:
    safe_name = _build_safe_upload_filename(file.filename, fallback_extension=".png")
    extension = os.path.splitext(safe_name)[1].lower()
    allowed_extensions = {".jpg", ".jpeg", ".png", ".webp"}
    if extension not in allowed_extensions:
        raise HTTPException(status_code=400, detail="Unsupported image type. Use JPG, PNG, or WEBP.")
    return safe_name


def _avatar_inserts_dir() -> str:
    target = (os.getenv("AVATAR_INSERTS_DIR") or "/app/database/media/avatar-inserts").strip()
    os.makedirs(target, exist_ok=True)
    return target


def _validate_avatar_insert_video(file: UploadFile) -> str:
    safe_name = _build_safe_upload_filename(file.filename, fallback_extension=".mp4")
    extension = os.path.splitext(safe_name)[1].lower()
    allowed_extensions = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
    if extension not in allowed_extensions:
        raise HTTPException(status_code=400, detail="Unsupported video type for avatar inserts")
    return safe_name

@router.post("/upload/test-video/{telegram_id}")
async def upload_test_video(
    telegram_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)

    safe_name = _build_safe_upload_filename(file.filename, fallback_extension=".mp4")
    extension = os.path.splitext(safe_name)[1].lower()
    allowed_extensions = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
    if extension not in allowed_extensions:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    uploads_dir = os.getenv("TEST_VIDEO_INPUT_DIR", "/app/database/media/test-input")
    os.makedirs(uploads_dir, exist_ok=True)
    unique_name = f"{telegram_id}_{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}_{safe_name}"
    file_path = os.path.join(uploads_dir, unique_name)

    with open(file_path, "wb") as target:
        target.write(await file.read())

    new_task = models.VideoTask(
        user_id=user.id,
        source_url=file_path,
        source_title=safe_name,
        type="local_upload",
        status="pending",
        publish_at=None,
        publishing_status="not_published",
    )
    db.add(new_task)
    db.commit()
    db.refresh(new_task)

    update_task_status_message(db, new_task, stage="Тестовая задача создана", detail="Локальное видео загружено.")

    try:
        celery_client.send_task("process_content_task", args=[new_task.id])
    except Exception as e:
        logging.error(f"Failed to enqueue local upload task {new_task.id}: {e}")
        raise HTTPException(status_code=500, detail="Task created but queue enqueue failed")

    return {"status": "queued", "task_id": new_task.id}

@router.post("/upload/plate/{telegram_id}", response_model=schemas.PlateAssetOut)
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

@router.delete("/plates/{telegram_id}/{plate_id}")
def delete_plate(telegram_id: str, plate_id: int, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    plate = db.query(models.Plate).filter(models.Plate.id == plate_id, models.Plate.user_id == user.id).first()
    if not plate:
        raise HTTPException(status_code=404, detail="Plate not found")

    # Cleanup references in UserPublishChannel
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
        try: os.remove(file_path)
        except OSError: logging.warning("Failed to remove plate file: %s", file_path)

    return {"status": "deleted", "plate_id": plate_id}

@router.post("/upload/cta/{telegram_id}")
async def upload_cta(
    telegram_id: str,
    label: str = Form(""),
    platform: str = Form("universal"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    norm_platform = normalize_ending_platform(platform)
    cta_dir = os.getenv("CTA_DIR", "/app/database/media/cta")
    os.makedirs(cta_dir, exist_ok=True)
    file_path = os.path.join(cta_dir, f"{telegram_id}_{norm_platform}_{file.filename}")
    
    with open(file_path, "wb") as f:
        f.write(await file.read())
        
    new_cta = models.CTAClip(user_id=user.id, file_path=file_path, label=label or file.filename, platform=norm_platform)
    db.add(new_cta)
    db.commit()
    return {"status": "uploaded", "cta_id": new_cta.id}

@router.post("/upload/ending/{telegram_id}", response_model=schemas.EndingClipOut)
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
    norm_platform = normalize_ending_platform(platform)
    norm_account_id = parse_optional_account_id(account_id)
    endings_dir = os.getenv("CTA_DIR", "/app/database/media/cta")
    os.makedirs(endings_dir, exist_ok=True)

    account_segment = f"_a{norm_account_id}" if norm_account_id is not None else ""
    file_path = os.path.join(endings_dir, f"{telegram_id}_{norm_platform}{account_segment}_{file.filename}")
    with open(file_path, "wb") as f:
        f.write(await file.read())

    ending = models.CTAClip(user_id=user.id, account_id=norm_account_id, file_path=file_path, label=label or file.filename, platform=norm_platform)
    db.add(ending)
    db.commit()
    db.refresh(ending)
    return ending

@router.delete("/endings/{telegram_id}/{ending_id}")
def delete_ending(telegram_id: str, ending_id: int, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    ending = db.query(models.CTAClip).filter(models.CTAClip.id == ending_id, models.CTAClip.user_id == user.id).first()
    if not ending:
        raise HTTPException(status_code=404, detail="Ending not found")

    file_path = ending.file_path
    db.delete(ending)
    db.commit()

    if file_path and os.path.isfile(file_path):
        try: os.remove(file_path)
        except OSError: logging.warning("Failed to remove ending file: %s", file_path)

    return {"status": "deleted", "ending_id": ending_id}

@router.get("/endings/{telegram_id}", response_model=list[schemas.EndingClipOut])
def list_endings(telegram_id: str, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    return db.query(models.CTAClip).filter(models.CTAClip.user_id == user.id).order_by(models.CTAClip.account_id.asc().nullsfirst(), models.CTAClip.id.desc()).all()


@router.post("/upload/thumbnail-reference/{telegram_id}", response_model=schemas.ThumbnailReferenceOut)
async def upload_thumbnail_reference(
    telegram_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    safe_name = _validate_thumbnail_file(file)
    uploads_dir = _thumbnail_assets_dir()
    unique_name = f"ref_{telegram_id}_{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}_{safe_name}"
    file_path = os.path.join(uploads_dir, unique_name)

    with open(file_path, "wb") as target:
        target.write(await file.read())

    item = models.ThumbnailReference(user_id=user.id, file_path=file_path)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/thumbnail-references/{telegram_id}", response_model=list[schemas.ThumbnailReferenceOut])
def list_thumbnail_references(telegram_id: str, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    return (
        db.query(models.ThumbnailReference)
        .filter(models.ThumbnailReference.user_id == user.id)
        .order_by(models.ThumbnailReference.created_at.desc(), models.ThumbnailReference.id.desc())
        .all()
    )


@router.delete("/thumbnail-references/{telegram_id}/{reference_id}")
def delete_thumbnail_reference(telegram_id: str, reference_id: int, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    reference = (
        db.query(models.ThumbnailReference)
        .filter(models.ThumbnailReference.id == reference_id, models.ThumbnailReference.user_id == user.id)
        .first()
    )
    if not reference:
        raise HTTPException(status_code=404, detail="Thumbnail reference not found")

    file_path = reference.file_path
    db.delete(reference)
    db.commit()

    if file_path and os.path.isfile(file_path):
        try:
            os.remove(file_path)
        except OSError:
            logging.warning("Failed to remove thumbnail reference file: %s", file_path)

    return {"status": "deleted", "reference_id": reference_id}


@router.post("/upload/thumbnail-face/{telegram_id}")
async def upload_thumbnail_face(
    telegram_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    safe_name = _validate_thumbnail_file(file)
    uploads_dir = _thumbnail_assets_dir()
    unique_name = f"face_{telegram_id}_{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}_{safe_name}"
    file_path = os.path.join(uploads_dir, unique_name)

    previous_path = user.thumbnail_face_path
    with open(file_path, "wb") as target:
        target.write(await file.read())

    user.thumbnail_face_path = file_path
    db.commit()

    if previous_path and previous_path != file_path and os.path.isfile(previous_path):
        try:
            os.remove(previous_path)
        except OSError:
            logging.warning("Failed to remove previous thumbnail face file: %s", previous_path)

    return {"status": "uploaded", "file_path": file_path}


@router.delete("/thumbnail-face/{telegram_id}")
def delete_thumbnail_face(telegram_id: str, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    previous_path = user.thumbnail_face_path
    user.thumbnail_face_path = None
    db.commit()

    if previous_path and os.path.isfile(previous_path):
        try:
            os.remove(previous_path)
        except OSError:
            logging.warning("Failed to remove thumbnail face file: %s", previous_path)

    return {"status": "deleted"}


@router.post("/upload/avatar-insert/{telegram_id}", response_model=schemas.AvatarInsertClipOut)
async def upload_avatar_insert_clip(
    telegram_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    safe_name = _validate_avatar_insert_video(file)
    target_dir = _avatar_inserts_dir()
    unique_name = f"ins_{telegram_id}_{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}_{safe_name}"
    file_path = os.path.join(target_dir, unique_name)

    with open(file_path, "wb") as target:
        target.write(await file.read())

    clip = models.AvatarInsertClip(user_id=user.id, file_path=file_path)
    db.add(clip)
    db.commit()
    db.refresh(clip)
    return clip


@router.get("/avatar-inserts/{telegram_id}", response_model=list[schemas.AvatarInsertClipOut])
def list_avatar_insert_clips(telegram_id: str, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    return (
        db.query(models.AvatarInsertClip)
        .filter(models.AvatarInsertClip.user_id == user.id)
        .order_by(models.AvatarInsertClip.created_at.desc(), models.AvatarInsertClip.id.desc())
        .all()
    )


@router.delete("/avatar-inserts/{telegram_id}/{clip_id}")
def delete_avatar_insert_clip(telegram_id: str, clip_id: int, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    clip = (
        db.query(models.AvatarInsertClip)
        .filter(models.AvatarInsertClip.id == clip_id, models.AvatarInsertClip.user_id == user.id)
        .first()
    )
    if not clip:
        raise HTTPException(status_code=404, detail="Avatar insert clip not found")

    file_path = clip.file_path
    db.delete(clip)
    db.commit()

    if file_path and os.path.isfile(file_path):
        try:
            os.remove(file_path)
        except OSError:
            logging.warning("Failed to remove avatar insert clip file: %s", file_path)

    return {"status": "deleted", "clip_id": clip_id}
