from pydantic import BaseModel
from typing import Optional

class UserSettingsUpdate(BaseModel):
    font_name: Optional[str] = None
    font_size: Optional[int] = None
    font_color: Optional[str] = None
    selected_plate_id: Optional[int] = None

class VideoTaskCreate(BaseModel):
    source_url: str
    type: str  # 'vizard', 'instagram', 'youtube'

class UserSettings(BaseModel):
    id: int
    telegram_id: str
    font_name: str
    font_size: int
    font_color: str
    selected_plate_id: Optional[int]

    class Config:
        from_attributes = True
