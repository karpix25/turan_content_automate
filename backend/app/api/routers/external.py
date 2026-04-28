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
        return {"voices": []}
    
    headers = {
        "xi-api-key": api_key,
        "Accept": "application/json"
    }
    url = "https://api.elevenlabs.io/v2/voices"
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # Filter to only show user's own voices (Instant and Professional clones)
        if "voices" in data:
            data["voices"] = [
                v for v in data["voices"] 
                if v.get("category") in ("cloned", "professional")
            ]
        return data
    except Exception as e:
        logging.error(f"Failed to fetch ElevenLabs voices: {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch voices from ElevenLabs")

@router.get("/heygen/avatars")
def get_heygen_avatars(telegram_id: str = None, db: Session = Depends(get_db)):
    if telegram_id:
        ensure_admin_access(telegram_id)
    
    from ...core.config import HEYGEN_API_KEY
    api_key = HEYGEN_API_KEY.strip()
    if not api_key:
        return {"data": {"avatars": []}}
    
    headers = {
        "x-api-key": api_key,
        "Accept": "application/json"
    }
    # We'll fetch both public and private avatars for maximum flexibility
    url = "https://api.heygen.com/v3/avatars"
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logging.error(f"Failed to fetch HeyGen avatars: {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch avatars from HeyGen")

