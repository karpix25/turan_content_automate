from pydantic import BaseModel
from typing import Optional
import datetime

class UserSettingsUpdate(BaseModel):
    font_name: Optional[str] = None
    font_size: Optional[int] = None
    font_color: Optional[str] = None
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

class UserSettings(BaseModel):
    id: int
    telegram_id: str
    font_name: str
    font_size: int
    font_color: str
    selected_plate_id: Optional[int]

    class Config:
        from_attributes = True
