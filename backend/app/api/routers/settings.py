import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ... import models, schemas
from ...core.config import llm, scraper
from ...publish_planner import validate_schedule_settings
from ..deps import get_db, ensure_admin_access, get_or_create_user
from ..utils import normalize_percent, _get_channel_videos_list, _extract_video_url_for_transcript

router = APIRouter(prefix="/settings", tags=["settings"])

@router.get("/{telegram_id}")
def get_settings(telegram_id: str, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    return user

@router.post("/{telegram_id}/update")
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

@router.get("/style/{telegram_id}", response_model=dict)
async def get_style_settings(telegram_id: str, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    return {
        "author_style_profile": user.author_style_profile,
        "training_source": user.training_source,
        "heygen_avatar_id": user.heygen_avatar_id,
        "elevenlabs_voice_id": user.elevenlabs_voice_id
    }

@router.post("/train-style/{telegram_id}")
async def train_style(telegram_id: str, req: schemas.StyleTrainingRequest, db: Session = Depends(get_db)):
    ensure_admin_access(telegram_id)
    user = get_or_create_user(db, telegram_id)
    
    logging.info(f"Training style from channel: {req.channel_url} (count: {req.video_count})")
    channel_data = scraper.get_channel_videos(req.channel_url)
    videos = _get_channel_videos_list(channel_data or {})
    if not videos:
        raise HTTPException(
            status_code=400,
            detail="Failed to fetch channel videos (use YouTube channel URL, @handle, channelId, or a public video URL)",
        )
    
    transcripts = []
    for video in videos[:req.video_count]:
        v_url = _extract_video_url_for_transcript(video)
        if not v_url:
            continue
        t_data = scraper.get_youtube_transcript(v_url)
        if t_data and t_data.get("transcript_only_text"):
            transcripts.append(t_data["transcript_only_text"])
            
    if not transcripts:
        raise HTTPException(status_code=400, detail="No transcripts found for training")
        
    style_profile = llm.analyze_style(transcripts)
    if not style_profile:
        raise HTTPException(status_code=500, detail="Style analysis failed")
        
    user.author_style_profile = style_profile
    user.training_source = req.channel_url
    db.commit()
    
    return {"status": "success", "style_profile": style_profile}
