from fastapi import FastAPI, Depends, UploadFile, File, HTTPException
from sqlalchemy.orm import Session
from .database import engine, SessionLocal, Base
from . import models, schemas
import os
import logging
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

# Initialize DB
models.Base.metadata.create_all(bind=engine)

celery_client = Celery("api_client", broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"))

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
    # Handle publish_at separately if needed or just sync it to a 'default' or current task
    # For now, let's assume the user sets it per task if they send a link,
    # or we store a 'default_schedule' in User model.
    # Let's add it to the user model as a default.
    for key, value in update_data.items():
        setattr(user, key, value)
    db.commit()
    return {"status": "updated"}

@app.post("/tasks/{telegram_id}")
def create_task(telegram_id: str, payload: schemas.VideoTaskCreate, db: Session = Depends(get_db)):
    user = get_or_create_user(db, telegram_id)

    new_task = models.VideoTask(
        user_id=user.id,
        source_url=payload.source_url,
        type=payload.type,
        status="pending",
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
async def upload_cta(telegram_id: str, label: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    user = get_or_create_user(db, telegram_id)
    cta_dir = os.getenv("CTA_DIR", "cta")
    os.makedirs(cta_dir, exist_ok=True)
    file_name = f"{telegram_id}_{file.filename}"
    file_path = os.path.join(cta_dir, file_name)
    
    with open(file_path, "wb") as f:
        f.write(await file.read())
        
    new_cta = models.CTAClip(user_id=user.id, file_path=file_path, label=label)
    db.add(new_cta)
    db.commit()
    return {"status": "uploaded", "cta_id": new_cta.id, "file_path": file_path}
