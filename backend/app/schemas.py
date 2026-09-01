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
    heygen_video_api_version: Optional[str] = None
    heygen_avatar_engine: Optional[str] = None
    elevenlabs_voice_id: Optional[str] = None
    thumbnail_face_path: Optional[str] = None
    vertical_thumbnail_face_path: Optional[str] = None
    avatar_script_duration_minutes: Optional[int] = None
    avatar_vertical_duration_seconds: Optional[int] = None
    avatar_insert_start_percent: Optional[int] = None
    avatar_insert_end_percent: Optional[int] = None
    avatar_insert_clips_count: Optional[int] = None
    avatar_overlay_x_percent: Optional[int] = None
    avatar_overlay_y_percent: Optional[int] = None
    avatar_overlay_size_percent: Optional[int] = None
    avatar_overlay_opacity_percent: Optional[int] = None
    reels_broll_yandex_dir: Optional[str] = None
    reels_broll_start_percent: Optional[int] = None
    reels_broll_end_percent: Optional[int] = None
    reels_broll_clips_count: Optional[int] = None
    reels_broll_coverage_percent: Optional[int] = None
    youtube_description_template: Optional[str] = None
    instagram_post_5s_audio_profile: Optional[str] = None
    instagram_post_5s_overlay_path: Optional[str] = None
    instagram_post_5s_cta_text: Optional[str] = None
    instagram_post_5s_image_prompt: Optional[str] = None

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
    postmypost_project_id: Optional[int] = None
    publish_at: Optional[datetime.datetime] = None
    telegram_chat_id: Optional[str] = None
    telegram_status_message_id: Optional[str] = None
    telegram_reply_message_id: Optional[str] = None

class VideoTaskScheduleUpdate(BaseModel):
    publish_at: Optional[datetime.datetime] = None

class ThumbnailPromptReviewUpdate(BaseModel):
    action: str
    prompt: Optional[str] = None

class ContentScriptGenerateRequest(BaseModel):
    count: int = 3
    format: str = "short"
    notebook_id: Optional[str] = None
    topic_hint: Optional[str] = None
    telegram_chat_id: Optional[str] = None

class ContentScriptReviewUpdate(BaseModel):
    action: str

class VideoTaskOut(BaseModel):
    id: int
    user_id: int
    source_url: str
    type: str
    status: str
    output_path: Optional[str]
    postmypost_project_id: Optional[int] = None
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

class PostMyPostProjectUpdate(BaseModel):
    project_id: int
    uniqueization_mode: Optional[str] = None
    publish_limit_per_day: Optional[int] = None
    vizard_limit_per_day: Optional[int] = None
    other_formats_limit_per_day: Optional[int] = None
    carousel_ctas: Optional[dict[str, str]] = None
    story_ctas: Optional[dict[str, str]] = None

class PostMyPostProjectOut(BaseModel):
    id: int
    name: str
    timezone_id: Optional[int] = None
    selected: bool = False
    uniqueization_mode: str = "auto"
    publish_limit_per_day: int = 3
    vizard_limit_per_day: int = 1
    other_formats_limit_per_day: int = 3
    carousel_ctas: dict[str, str] = {}
    story_ctas: dict[str, str] = {}

class PostMyPostProjectsOut(BaseModel):
    selected_project_id: Optional[int]
    selected_project_uniqueization_mode: str = "auto"
    projects: list[PostMyPostProjectOut] = []


class CarouselDraftCreate(BaseModel):
    master_text: str
    project_id: Optional[int] = None
    slide_count: Optional[int] = None
    telegram_chat_id: Optional[str] = None
    telegram_reply_message_id: Optional[str] = None


class ReferenceChannelCreate(BaseModel):
    project_id: int
    platform: str
    source_url: str
    title: Optional[str] = None


class ReferenceChannelOut(BaseModel):
    id: int
    project_id: int
    platform: str
    source_url: str
    title: Optional[str]
    is_active: bool
    last_synced_at: Optional[datetime.datetime]
    created_at: datetime.datetime

    class Config:
        from_attributes = True


class DesignReferenceOut(BaseModel):
    id: int
    project_id: int
    design_format: str
    file_path: str
    width: int
    height: int
    created_at: datetime.datetime

    class Config:
        from_attributes = True


class CarouselDraftReviewUpdate(BaseModel):
    action: str
    text: Optional[str] = None


class CarouselDraftOut(BaseModel):
    id: int
    user_id: int
    project_id: int
    master_text: str
    approved_text: Optional[str]
    status: str
    slide_count: int
    story_slide_count: Optional[int] = 1
    platform_accounts: dict
    ctas: dict
    platform_texts: Optional[dict] = None
    story_ctas: Optional[dict] = None
    slides: Optional[dict] = None
    story_slides: Optional[dict] = None
    source_post_ids: Optional[list[int]] = None
    error: Optional[str] = None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    class Config:
        from_attributes = True

class PlateAssetOut(BaseModel):
    id: int
    postmypost_project_id: Optional[int] = None
    account_id: Optional[int] = None
    file_path: str
    media_type: str = "image"

    class Config:
        from_attributes = True


class BrollAssetOut(BaseModel):
    id: int
    postmypost_project_id: int
    file_path: str
    original_filename: str
    is_active: bool = True
    created_at: datetime.datetime

    class Config:
        from_attributes = True

class PostMyPostAccountOut(BaseModel):
    account_id: int
    account_name: str
    account_login: Optional[str]
    account_handle: Optional[str] = None
    account_avatar_url: Optional[str] = None
    channel_id: Optional[int]
    channel_code: Optional[str]
    channel_name: Optional[str]
    enabled: bool
    description: Optional[str]
    publish_limit_per_day: int
    vizard_limit_per_day: int
    other_formats_limit_per_day: int
    selected_plate_id: Optional[int]
    selected_plate_ids: list[int] = []
    plate_start_percent: Optional[int]
    plate_file_path: Optional[str]
    plate_assets: list[PlateAssetOut] = []


class EndingClipOut(BaseModel):
    id: int
    user_id: int
    postmypost_project_id: Optional[int] = None
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


class ThumbnailFaceReferenceUpdate(BaseModel):
    target: str = "both"


class AvatarInsertClipOut(BaseModel):
    id: int
    user_id: int
    file_path: str
    created_at: datetime.datetime

    class Config:
        from_attributes = True


class InstagramPost5sAudioProfileUpdate(BaseModel):
    profile: str


class InstagramPost5sAudioTrackOut(BaseModel):
    id: int
    user_id: int
    source_profile: Optional[str]
    source_url: Optional[str]
    source_code: Optional[str]
    file_path: str
    created_at: datetime.datetime

    class Config:
        from_attributes = True


class InstagramPost5sSettingsOut(BaseModel):
    audio_profile: Optional[str] = None
    audio_status: Optional[str] = None
    audio_error: Optional[str] = None
    audio_refreshed_at: Optional[datetime.datetime] = None
    overlay_path: Optional[str] = None
    cta_text: Optional[str] = None
    image_prompt: Optional[str] = None
    audio_tracks: list[InstagramPost5sAudioTrackOut] = []

class InstagramPost5sProjectSettingsUpdate(BaseModel):
    cta_text: Optional[str] = None
    image_prompt: Optional[str] = None

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
    heygen_video_api_version: str = "v2"
    heygen_avatar_engine: str = "avatar_iv"
    elevenlabs_voice_id: Optional[str] = None
    elevenlabs_voice_speeds: Optional[dict] = None
    thumbnail_face_path: Optional[str] = None
    vertical_thumbnail_face_path: Optional[str] = None
    avatar_script_duration_minutes: int
    avatar_vertical_duration_seconds: int = 0
    avatar_insert_start_percent: int
    avatar_insert_end_percent: int
    avatar_insert_clips_count: int
    avatar_overlay_x_percent: int = 70
    avatar_overlay_y_percent: int = 100
    avatar_overlay_size_percent: int = 61
    avatar_overlay_opacity_percent: int = 100
    reels_broll_yandex_dir: str
    reels_broll_start_percent: int
    reels_broll_end_percent: int
    reels_broll_clips_count: int
    reels_broll_coverage_percent: int
    youtube_description_template: Optional[str] = None
    instagram_post_5s_audio_profile: Optional[str] = None
    instagram_post_5s_audio_status: Optional[str] = None
    instagram_post_5s_audio_error: Optional[str] = None
    instagram_post_5s_audio_refreshed_at: Optional[datetime.datetime] = None
    instagram_post_5s_overlay_path: Optional[str] = None
    instagram_post_5s_cta_text: Optional[str] = None
    instagram_post_5s_image_prompt: Optional[str] = None

    class Config:
        from_attributes = True
