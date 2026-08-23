import os
import uuid
from io import BytesIO

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from PIL import Image, ImageOps
from sqlalchemy.orm import Session

from ... import models, schemas
from ...services.carousel_pipeline import get_design_profile
from ..deps import ensure_admin_access, get_db, get_or_create_user

router = APIRouter(tags=["design-references"])


@router.get("/design-references/{telegram_id}", response_model=list[schemas.DesignReferenceOut])
def list_design_references(
    telegram_id: str,
    project_id: int,
    design_format: str = "carousel",
    db: Session = Depends(get_db),
):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    try:
        get_design_profile(design_format)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return db.query(models.DesignReference).filter(
        models.DesignReference.user_id == user.id,
        models.DesignReference.project_id == project_id,
        models.DesignReference.design_format == design_format,
    ).order_by(models.DesignReference.created_at.desc()).all()


@router.post("/upload/design-reference/{telegram_id}", response_model=schemas.DesignReferenceOut)
async def upload_design_reference(
    telegram_id: str,
    project_id: int = Form(...),
    design_format: str = Form("carousel"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    try:
        profile = get_design_profile(design_format)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        image = Image.open(BytesIO(await file.read())).convert("RGB")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Нужен корректный JPG, PNG или WEBP") from exc

    output_dir = (os.getenv("DESIGN_REFERENCES_DIR") or "/app/database/media/design-references").strip()
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"{user.id}_{project_id}_{design_format}_{uuid.uuid4().hex}.png")
    normalized = ImageOps.fit(image, (profile["width"], profile["height"]), method=Image.Resampling.LANCZOS)
    normalized.save(path, format="PNG", optimize=True)
    item = models.DesignReference(
        user_id=user.id,
        project_id=int(project_id),
        design_format=design_format,
        file_path=path,
        width=profile["width"],
        height=profile["height"],
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/design-references/{telegram_id}/{reference_id}")
def delete_design_reference(telegram_id: str, reference_id: int, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    item = db.query(models.DesignReference).filter(
        models.DesignReference.id == reference_id,
        models.DesignReference.user_id == user.id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Дизайн-референс не найден")
    if item.file_path and os.path.isfile(item.file_path):
        os.remove(item.file_path)
    db.delete(item)
    db.commit()
    return {"status": "deleted"}
