import datetime
import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ... import models, schemas
from ...core.config import pmp_client
from ..deps import ensure_admin_access, get_db, get_or_create_user
from ..upload_storage import save_upload_file_stream
from ..utils import _build_safe_upload_filename

router = APIRouter(tags=["broll"])

ALLOWED_BROLL_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}


def _broll_dir() -> str:
    target = (os.getenv("BROLL_DIR") or "/app/database/media/broll").strip()
    os.makedirs(target, exist_ok=True)
    return target


def _validate_broll_file(file: UploadFile) -> str:
    safe_name = _build_safe_upload_filename(file.filename, fallback_extension=".mp4")
    if os.path.splitext(safe_name)[1].lower() not in ALLOWED_BROLL_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Неподдерживаемый формат B-roll. Используйте MP4, MOV, MKV, WEBM или M4V.",
        )
    return safe_name


def _ensure_project_access(project_id: int) -> None:
    if not os.getenv("POSTMYPOST_API_KEY", "").strip():
        raise HTTPException(status_code=400, detail="POSTMYPOST_API_KEY is not configured")
    try:
        project_ids = {
            int(project["id"])
            for project in pmp_client.get_projects()
            if isinstance(project, dict) and project.get("id") is not None
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"PostMyPost Error: {exc}") from exc
    if project_id not in project_ids:
        raise HTTPException(status_code=400, detail="PostMyPost project is not available for this API key")


def _asset_out(asset: models.BrollAsset) -> schemas.BrollAssetOut:
    return schemas.BrollAssetOut(
        id=asset.id,
        postmypost_project_id=asset.postmypost_project_id,
        file_path=asset.file_path,
        original_filename=asset.original_filename,
        is_active=asset.is_active,
        created_at=asset.created_at,
    )


@router.get("/broll/{telegram_id}", response_model=list[schemas.BrollAssetOut])
def get_broll_assets(
    telegram_id: str,
    project_id: int,
    db: Session = Depends(get_db),
):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    _ensure_project_access(project_id)
    assets = (
        db.query(models.BrollAsset)
        .filter(
            models.BrollAsset.user_id == user.id,
            models.BrollAsset.postmypost_project_id == project_id,
            models.BrollAsset.is_active.is_(True),
        )
        .order_by(models.BrollAsset.created_at.desc(), models.BrollAsset.id.desc())
        .all()
    )
    return [_asset_out(asset) for asset in assets]


@router.post("/upload/broll/{telegram_id}", response_model=list[schemas.BrollAssetOut])
async def upload_broll_assets(
    telegram_id: str,
    project_id: int = Form(...),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    _ensure_project_access(project_id)
    if not files:
        raise HTTPException(status_code=400, detail="Не выбраны файлы B-roll")

    project_dir = os.path.join(_broll_dir(), str(user.id), str(project_id))
    os.makedirs(project_dir, exist_ok=True)
    assets: list[models.BrollAsset] = []
    created_paths: list[str] = []
    try:
        for file in files:
            safe_name = _validate_broll_file(file)
            unique_name = (
                f"{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S')}_"
                f"{uuid.uuid4().hex[:10]}_{safe_name}"
            )
            file_path = os.path.join(project_dir, unique_name)
            await save_upload_file_stream(file, file_path)
            created_paths.append(file_path)
            asset = models.BrollAsset(
                user_id=user.id,
                postmypost_project_id=project_id,
                file_path=file_path,
                original_filename=file.filename or safe_name,
            )
            db.add(asset)
            assets.append(asset)
        db.commit()
        for asset in assets:
            db.refresh(asset)
    except Exception:
        db.rollback()
        for path in created_paths:
            try:
                os.remove(path)
            except OSError:
                pass
        raise
    return [_asset_out(asset) for asset in assets]


@router.delete("/broll/{telegram_id}/{asset_id}")
def delete_broll_asset(
    telegram_id: str,
    asset_id: int,
    project_id: int,
    db: Session = Depends(get_db),
):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    _ensure_project_access(project_id)
    asset = (
        db.query(models.BrollAsset)
        .filter(
            models.BrollAsset.id == asset_id,
            models.BrollAsset.user_id == user.id,
            models.BrollAsset.postmypost_project_id == project_id,
        )
        .first()
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="B-roll не найден")
    file_path = asset.file_path
    db.delete(asset)
    db.commit()
    try:
        os.remove(file_path)
    except OSError:
        pass
    return {"status": "deleted", "id": asset_id}
