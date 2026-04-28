import logging
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .database import init_database, SessionLocal
from . import models
from dotenv import load_dotenv
from .api.utils import get_allowed_cors_origins, get_telegram_admin_ids
from .api.routers import settings, tasks, channels, uploads, external

load_dotenv()

# Initialize DB
init_database()

app = FastAPI(title="Content Processing API")

# CORS Middleware
allowed_cors_origins = get_allowed_cors_origins()
if allowed_cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Authorization", "Content-Type", "X-Requested-With"],
    )

# Include Routers
app.include_router(settings.router)
app.include_router(tasks.router)
app.include_router(channels.router)
app.include_router(uploads.router)
app.include_router(external.router)

# Static Files for Previews
media_dir = "/app/database/media"
if os.path.exists(media_dir):
    from fastapi.staticfiles import StaticFiles
    app.mount("/media", StaticFiles(directory=media_dir), name="media")
    logging.info(f"Mounted static media directory: {media_dir}")


@app.on_event("startup")
async def startup_event():
    logging.info("--- Backend Startup Configuration ---")
    telegram_admin_ids = get_telegram_admin_ids()
    if not telegram_admin_ids:
        logging.warning("TELEGRAM_ADMIN_IDS is not configured. Admin endpoints are publicly accessible!")
    else:
        logging.info(f"Loaded {len(telegram_admin_ids)} admin IDs")
    
    pmp_key = os.getenv("POSTMYPOST_API_KEY", "").strip()
    if not pmp_key or pmp_key == "your_postmypost_key":
        logging.error("POSTMYPOST_API_KEY is missing or contains placeholder value!")
    
    # Shared Admin Migration
    try:
        db = SessionLocal()
        try:
            shared_user = db.query(models.User).filter(models.User.telegram_id == "shared_admin").first()
            if not shared_user:
                legacy_admin_id = "38061745"
                legacy_user = db.query(models.User).filter(models.User.telegram_id == legacy_admin_id).first()
                if legacy_user:
                    logging.info(f"Migrating legacy admin {legacy_admin_id} to shared_admin profile.")
                    legacy_user.telegram_id = "shared_admin"
                    db.commit()
        finally:
            db.close()
    except Exception as e:
        logging.error(f"Failed to run shared admin migration: {e}")
        
    logging.info("-------------------------------------")

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Content processing API is running (Modular)"}
