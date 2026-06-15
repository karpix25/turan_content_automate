import logging
import os
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

    start_percent = update_data.get("avatar_insert_start_percent", user.avatar_insert_start_percent)
    end_percent = update_data.get("avatar_insert_end_percent", user.avatar_insert_end_percent)
    clips_count = update_data.get("avatar_insert_clips_count", user.avatar_insert_clips_count)
    if start_percent is not None:
        start_percent = normalize_percent(start_percent, field_name="avatar_insert_start_percent")
        if start_percent >= 100:
            raise HTTPException(status_code=400, detail="avatar_insert_start_percent must be below 100")
        update_data["avatar_insert_start_percent"] = start_percent
    if end_percent is not None:
        end_percent = normalize_percent(end_percent, field_name="avatar_insert_end_percent")
        if end_percent <= 0:
            raise HTTPException(status_code=400, detail="avatar_insert_end_percent must be above 0")
        update_data["avatar_insert_end_percent"] = end_percent
    if start_percent is not None and end_percent is not None and end_percent <= start_percent:
        raise HTTPException(status_code=400, detail="avatar_insert_end_percent must be greater than avatar_insert_start_percent")

    if clips_count is not None:
        try:
            clips_value = int(clips_count)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="avatar_insert_clips_count must be an integer")
        if clips_value < 0 or clips_value > 20:
            raise HTTPException(status_code=400, detail="avatar_insert_clips_count must be between 0 and 20")
        update_data["avatar_insert_clips_count"] = clips_value

    for field_name in (
        "avatar_overlay_x_percent",
        "avatar_overlay_y_percent",
        "avatar_overlay_opacity_percent",
    ):
        if field_name in update_data:
            update_data[field_name] = normalize_percent(update_data.get(field_name), field_name=field_name)

    if "avatar_overlay_size_percent" in update_data:
        try:
            size_value = int(update_data.get("avatar_overlay_size_percent") or 61)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="avatar_overlay_size_percent must be an integer")
        if size_value < 5 or size_value > 100:
            raise HTTPException(status_code=400, detail="avatar_overlay_size_percent must be between 5 and 100")
        update_data["avatar_overlay_size_percent"] = size_value

    broll_start_percent = update_data.get("reels_broll_start_percent", user.reels_broll_start_percent)
    broll_end_percent = update_data.get("reels_broll_end_percent", user.reels_broll_end_percent)
    broll_clips_count = update_data.get("reels_broll_clips_count", user.reels_broll_clips_count)
    if broll_start_percent is not None:
        broll_start_percent = normalize_percent(broll_start_percent, field_name="reels_broll_start_percent")
        if broll_start_percent >= 100:
            raise HTTPException(status_code=400, detail="reels_broll_start_percent must be below 100")
        update_data["reels_broll_start_percent"] = broll_start_percent
    if broll_end_percent is not None:
        broll_end_percent = normalize_percent(broll_end_percent, field_name="reels_broll_end_percent")
        if broll_end_percent <= 0:
            raise HTTPException(status_code=400, detail="reels_broll_end_percent must be above 0")
        update_data["reels_broll_end_percent"] = broll_end_percent
    if broll_start_percent is not None and broll_end_percent is not None and broll_end_percent <= broll_start_percent:
        raise HTTPException(status_code=400, detail="reels_broll_end_percent must be greater than reels_broll_start_percent")

    if broll_clips_count is not None:
        try:
            broll_count_value = int(broll_clips_count)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="reels_broll_clips_count must be an integer")
        if broll_count_value < 0 or broll_count_value > 20:
            raise HTTPException(status_code=400, detail="reels_broll_clips_count must be between 0 and 20")
        update_data["reels_broll_clips_count"] = broll_count_value

    if "reels_broll_yandex_dir" in update_data:
        broll_dir = (update_data.get("reels_broll_yandex_dir") or "").strip()
        update_data["reels_broll_yandex_dir"] = broll_dir or "disk:/Видео для REELS"

    if "reels_broll_coverage_percent" in update_data:
        update_data["reels_broll_coverage_percent"] = normalize_percent(
            update_data.get("reels_broll_coverage_percent"),
            field_name="reels_broll_coverage_percent",
        )

    if "instagram_post_5s_audio_profile" in update_data:
        update_data["instagram_post_5s_audio_profile"] = (
            update_data.get("instagram_post_5s_audio_profile") or ""
        ).strip() or None

    if "instagram_post_5s_overlay_path" in update_data:
        overlay_path = (update_data.get("instagram_post_5s_overlay_path") or "").strip()
        if overlay_path and not os.path.isfile(overlay_path):
            raise HTTPException(status_code=400, detail="instagram_post_5s_overlay_path file does not exist")
        update_data["instagram_post_5s_overlay_path"] = overlay_path or None

    if "instagram_post_5s_cta_text" in update_data:
        raw_cta_text = str(update_data.get("instagram_post_5s_cta_text") or "")
        cta_lines = [" ".join(line.split()) for line in raw_cta_text.replace("\r\n", "\n").split("\n")]
        cta_text = "\n".join(line for line in cta_lines if line).strip()
        update_data["instagram_post_5s_cta_text"] = cta_text[:220] or None

    if "instagram_post_5s_image_prompt" in update_data:
        raw_image_prompt = str(update_data.get("instagram_post_5s_image_prompt") or "")
        image_prompt = " ".join(raw_image_prompt.replace("\r\n", "\n").split()).strip()
        update_data["instagram_post_5s_image_prompt"] = image_prompt[:1200] or None

    if "avatar_script_duration_minutes" in update_data:
        try:
            duration_value = int(update_data.get("avatar_script_duration_minutes"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="avatar_script_duration_minutes must be an integer")
        if duration_value < 1 or duration_value > 30:
            raise HTTPException(status_code=400, detail="avatar_script_duration_minutes must be between 1 and 30")
        update_data["avatar_script_duration_minutes"] = duration_value

    if "avatar_vertical_duration_seconds" in update_data:
        try:
            vertical_duration_value = int(update_data.get("avatar_vertical_duration_seconds") or 0)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="avatar_vertical_duration_seconds must be an integer")
        if vertical_duration_value != 0 and (vertical_duration_value < 5 or vertical_duration_value > 300):
            raise HTTPException(status_code=400, detail="avatar_vertical_duration_seconds must be 0 or between 5 and 300")
        update_data["avatar_vertical_duration_seconds"] = vertical_duration_value

    if "heygen_avatar_engine" in update_data:
        engine = (update_data.get("heygen_avatar_engine") or "avatar_iv").strip().lower()
        if engine not in {"avatar_iv", "avatar_v"}:
            raise HTTPException(status_code=400, detail="heygen_avatar_engine must be avatar_iv or avatar_v")
        update_data["heygen_avatar_engine"] = engine

    if "heygen_video_api_version" in update_data:
        api_version = (update_data.get("heygen_video_api_version") or "v2").strip().lower()
        if api_version not in {"v2", "v3"}:
            raise HTTPException(status_code=400, detail="heygen_video_api_version must be v2 or v3")
        update_data["heygen_video_api_version"] = api_version

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
        "heygen_vertical_avatar_id": user.heygen_vertical_avatar_id,
        "heygen_video_api_version": getattr(user, "heygen_video_api_version", None) or "v2",
        "heygen_avatar_engine": getattr(user, "heygen_avatar_engine", None) or "avatar_iv",
        "elevenlabs_voice_id": user.elevenlabs_voice_id,
        "elevenlabs_voice_speeds": user.elevenlabs_voice_speeds or {},
        "thumbnail_face_path": user.thumbnail_face_path,
        "vertical_thumbnail_face_path": user.vertical_thumbnail_face_path,
        "avatar_script_duration_minutes": user.avatar_script_duration_minutes,
        "avatar_vertical_duration_seconds": getattr(user, "avatar_vertical_duration_seconds", 0) or 0,
        "avatar_insert_start_percent": user.avatar_insert_start_percent,
        "avatar_insert_end_percent": user.avatar_insert_end_percent,
        "avatar_insert_clips_count": user.avatar_insert_clips_count,
        "avatar_overlay_x_percent": getattr(user, "avatar_overlay_x_percent", 70),
        "avatar_overlay_y_percent": getattr(user, "avatar_overlay_y_percent", 100),
        "avatar_overlay_size_percent": getattr(user, "avatar_overlay_size_percent", 61),
        "avatar_overlay_opacity_percent": getattr(user, "avatar_overlay_opacity_percent", 100),
        "reels_broll_yandex_dir": user.reels_broll_yandex_dir,
        "reels_broll_start_percent": user.reels_broll_start_percent,
        "reels_broll_end_percent": user.reels_broll_end_percent,
        "reels_broll_clips_count": user.reels_broll_clips_count,
        "reels_broll_coverage_percent": user.reels_broll_coverage_percent,
        "youtube_description_template": user.youtube_description_template,
        "instagram_post_5s_audio_profile": user.instagram_post_5s_audio_profile,
        "instagram_post_5s_audio_status": user.instagram_post_5s_audio_status,
        "instagram_post_5s_audio_error": user.instagram_post_5s_audio_error,
        "instagram_post_5s_audio_refreshed_at": user.instagram_post_5s_audio_refreshed_at,
        "instagram_post_5s_overlay_path": user.instagram_post_5s_overlay_path,
        "instagram_post_5s_cta_text": getattr(user, "instagram_post_5s_cta_text", None),
        "instagram_post_5s_image_prompt": getattr(user, "instagram_post_5s_image_prompt", None),
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
