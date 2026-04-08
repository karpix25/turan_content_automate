from fastapi import FastAPI, Depends, UploadFile, File, BackgroundTasks
from sqlalchemy.orm import Session
from .database import engine, SessionLocal, Base
from . import models, schemas
import os
from dotenv import load_dotenv

load_dotenv()

# Initialize DB
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Content Processing API")

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Content processing API is running"}

# User Settings API
@app.get("/settings/{telegram_id}")
def get_settings(telegram_id: str, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.telegram_id == telegram_id).first()
    if not user:
        user = models.User(telegram_id=telegram_id)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user

@app.post("/settings/{telegram_id}/update")
def update_settings(telegram_id: str, settings: schemas.UserSettingsUpdate, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.telegram_id == telegram_id).first()
    if user:
        update_data = settings.dict(exclude_unset=True)
        # Handle publish_at separately if needed or just sync it to a 'default' or current task
        # For now, let's assume the user sets it per task if they send a link, 
        # or we store a 'default_schedule' in User model.
        # Let's add it to the user model as a default.
        for key, value in update_data.items():
            setattr(user, key, value)
        db.commit()
    return {"status": "updated"}

# File Uploads (Plates & CTA)
@app.post("/upload/plate/{telegram_id}")
async def upload_plate(telegram_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.telegram_id == telegram_id).first()
    file_name = f"{telegram_id}_{file.filename}"
    file_path = os.path.join(os.getenv("PLATES_DIR", "plates"), file_name)
    
    with open(file_path, "wb") as f:
        f.write(await file.read())
        
    new_plate = models.Plate(user_id=user.id, file_path=file_path)
    db.add(new_plate)
    db.commit()
    return {"status": "uploaded", "plate_id": new_plate.id}

@app.post("/upload/cta/{telegram_id}")
async def upload_cta(telegram_id: str, label: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.telegram_id == telegram_id).first()
    file_name = f"{telegram_id}_{file.filename}"
    file_path = os.path.join(os.getenv("CTA_DIR", "cta"), file_name)
    
    with open(file_path, "wb") as f:
        f.write(await file.read())
        
    new_cta = models.CTAClip(user_id=user.id, file_path=file_path, label=label)
    db.add(new_cta)
    db.commit()
    return {"status": "uploaded", "cta_id": new_cta.id}
