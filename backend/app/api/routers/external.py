import os
import logging
import requests
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ...core.config import ELEVENLABS_API_KEY
from ..deps import get_db, ensure_admin_access

router = APIRouter(tags=["external"])

@router.get("/elevenlabs/voices")
def get_elevenlabs_voices(telegram_id: str = None, db: Session = Depends(get_db)):
    if telegram_id:
        ensure_admin_access(telegram_id)
    
    api_key = ELEVENLABS_API_KEY.strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="ELEVENLABS_API_KEY is not configured")
    
    headers = {
        "xi-api-key": api_key,
        "Accept": "application/json"
    }
    url = "https://api.elevenlabs.io/v2/voices?category=cloned"
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logging.error(f"Failed to fetch ElevenLabs voices: {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch voices from ElevenLabs")
