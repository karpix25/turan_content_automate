from pydantic import BaseModel
from typing import Optional
import datetime

class UserSettingsUpdate(BaseModel):
    font_name: Optional[str] = None
    font_size: Optional[int] = None
    font_color: Optional[str] = None
    subtitles_enabled: Optional[bool] = None
    auto_schedule_enabled: Optional[bool] = None
    publish_limit_per_day: Optional[int] = None
    publish_window_start_msk: Optional[str] = None
    publish_window_end_msk: Optional[str] = None
    selected_plate_id: Optional[int] = None
    plate_start_percent: Optional[int] = None
    heygen_avatar_id: Optional[str] = None
    heygen_vertical_avatar_id: Optional[str] = None
    elevenlabs_voice_id: Optional[str] = None
    thumbnail_face_path: Optional[str] = None
    vertical_thumbnail_face_path: Optional[str] = None
    avatar_script_duration_minutes: Optional[int] = None
    avatar_insert_start_percent: Optional[int] = None
    avatar_insert_end_percent: Optional[int] = None
    avatar_insert_clips_count: Optional[int] = None
    reels_broll_yandex_dir: Optional[str] = None
    reels_broll_start_percent: Optional[int] = None
    reels_broll_end_percent: Optional[int] = None
    reels_broll_clips_count: Optional[int] = None
    reels_broll_coverage_percent: Optional[int] = None
    youtube_description_template: Optional[str] = None

    telegram_chat_id: Optional[str] = None
    telegram_status_message_id: Optional[str] = None

class VideoTaskAvatarScriptOut(BaseModel):
    factual_outline: Optional[str] = None
    script_text: Optional[str] = None
    script_meta: Optional[dict] = None

class StyleTrainingRequest(BaseModel):
    channel_url: str
    video_count: int = 5

class VideoTaskCreate(BaseModel):
    source_url: str
    type: str
    source_title: Optional[str] = None
    publish_at: Optional[datetime.datetime] = None
    telegram_chat_id: Optional[str] = None
    telegram_status_message_id: Optional[str] = None

class VideoTaskScheduleUpdate(BaseModel):
    publish_at: Optional[datetime.datetime] = None

class ThumbnailPromptReviewUpdate(BaseModel):
    action: str
    prompt: Optional[str] = None

class VideoTaskOut(BaseModel):
    id: int
    user_id: int
    source_url: str
    type: str
    status: str
    output_path: Optional[str]
    target_account_id: Optional[int]
    target_platform: Optional[str]
    source_title: Optional[str]
    preview_url: Optional[str]
    publish_at: Optional[datetime.datetime]
    publishing_status: str
    postmypost_file_id: Optional[int]
    
    # New fields for Avatar/Script flow
    factual_outline: Optional[str] = None
    script_text: Optional[str] = None
    script_meta: Optional[dict] = None

    created_at: datetime.datetime
    updated_at: datetime.datetime

    class Config:
        from_attributes = True

class ChannelPreferenceUpdate(BaseModel):
    account_ids: list[int] = []
    descriptions: Optional[dict[str, str]] = None
    selected_plate_ids: Optional[dict[str, list[int]]] = None
    plate_start_percents: Optional[dict[str, int | None]] = None

class PlateAssetOut(BaseModel):
    id: int
    file_path: str

    class Config:
        from_attributes = True

class PostMyPostAccountOut(BaseModel):
    account_id: int
    account_name: str
    account_login: Optional[str]
    channel_id: Optional[int]
    channel_code: Optional[str]
    channel_name: Optional[str]
    enabled: bool
    description: Optional[str]
    selected_plate_id: Optional[int]
    selected_plate_ids: list[int] = []
    plate_start_percent: Optional[int]
    plate_file_path: Optional[str]
    plate_assets: list[PlateAssetOut] = []


class EndingClipOut(BaseModel):
    id: int
    user_id: int
    account_id: Optional[int]
    file_path: str
    label: Optional[str]
    platform: str

    class Config:
        from_attributes = True


class ThumbnailReferenceOut(BaseModel):
    id: int
    user_id: int
    file_path: str
    kind: str = "horizontal"
    created_at: datetime.datetime

    class Config:
        from_attributes = True


class ThumbnailReferenceUpdate(BaseModel):
    kind: str


class ThumbnailFaceReferenceOut(BaseModel):
    id: int
    user_id: int
    file_path: str
    created_at: datetime.datetime

    class Config:
        from_attributes = True


class AvatarInsertClipOut(BaseModel):
    id: int
    user_id: int
    file_path: str
    created_at: datetime.datetime

    class Config:
        from_attributes = True

class UserSettings(BaseModel):
    id: int
    telegram_id: str
    font_name: str
    font_size: int
    font_color: str
    subtitles_enabled: bool
    auto_schedule_enabled: bool
    publish_limit_per_day: int
    publish_window_start_msk: str
    publish_window_end_msk: str
    selected_plate_id: Optional[int]
    plate_start_percent: int
    author_style_profile: Optional[str] = None
    training_source: Optional[str] = None
    heygen_avatar_id: Optional[str] = None
    heygen_vertical_avatar_id: Optional[str] = None
    elevenlabs_voice_id: Optional[str] = None
    elevenlabs_voice_speeds: Optional[dict] = None
    thumbnail_face_path: Optional[str] = None
    vertical_thumbnail_face_path: Optional[str] = None
    avatar_script_duration_minutes: int
    avatar_insert_start_percent: int
    avatar_insert_end_percent: int
    avatar_insert_clips_count: int
    reels_broll_yandex_dir: str
    reels_broll_start_percent: int
    reels_broll_end_percent: int
    reels_broll_clips_count: int
    reels_broll_coverage_percent: int
    youtube_description_template: Optional[str] = None

    class Config:
        from_attributes = True
