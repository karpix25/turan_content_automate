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

class VideoTaskCreate(BaseModel):
    source_url: str
    type: str  # 'vizard', 'instagram', 'youtube'
    publish_at: Optional[datetime.datetime] = None

class VideoTaskScheduleUpdate(BaseModel):
    publish_at: Optional[datetime.datetime] = None

class VideoTaskOut(BaseModel):
    id: int
    user_id: int
    source_url: str
    type: str
    status: str
    output_path: Optional[str]
    target_account_id: Optional[int]
    publish_at: Optional[datetime.datetime]
    publishing_status: str
    postmypost_id: Optional[str]
    created_at: datetime.datetime
    updated_at: datetime.datetime

    class Config:
        from_attributes = True

class ChannelPreferenceUpdate(BaseModel):
    account_ids: list[int]

class PostMyPostAccountOut(BaseModel):
    account_id: int
    account_name: str
    account_login: Optional[str]
    channel_id: Optional[int]
    channel_code: Optional[str]
    channel_name: Optional[str]
    enabled: bool


class EndingClipOut(BaseModel):
    id: int
    user_id: int
    file_path: str
    label: Optional[str]
    platform: str

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

    class Config:
        from_attributes = True
