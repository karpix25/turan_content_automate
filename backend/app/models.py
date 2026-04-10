from sqlalchemy import Column, Integer, String, Boolean, DateTime, JSON, ForeignKey, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(String, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    # User settings
    font_name = Column(String, default="Montserrat")
    font_size = Column(Integer, default=60)
    font_color = Column(String, default="FFFFFF")  # Hex
    subtitles_enabled = Column(Boolean, default=True, nullable=False)
    auto_schedule_enabled = Column(Boolean, default=False, nullable=False)
    publish_limit_per_day = Column(Integer, default=3, nullable=False)
    publish_window_start_msk = Column(String, default="10:00:00", nullable=False)
    publish_window_end_msk = Column(String, default="22:00:00", nullable=False)
    selected_plate_id = Column(Integer, nullable=True)
    plate_start_percent = Column(Integer, default=0, nullable=False)

class Plate(Base):
    __tablename__ = "plates"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    file_path = Column(String)
    is_active = Column(Boolean, default=True)

class CTAClip(Base):
    __tablename__ = "cta_clips"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    account_id = Column(Integer, nullable=True, index=True)
    file_path = Column(String)
    label = Column(String)
    platform = Column(String, default="universal", nullable=False)  # 'instagram', 'youtube', 'universal'

class VideoTask(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    source_url = Column(String)
    type = Column(String)  # 'vizard', 'instagram', 'youtube'
    status = Column(String, default="pending")  # 'pending', 'processing', 'completed', 'failed'
    
    # Vizard specific
    vizard_project_id = Column(Integer, nullable=True)
    
    # Result
    output_path = Column(String, nullable=True)
    
    # Publication
    target_account_id = Column(Integer, nullable=True)
    publish_at = Column(DateTime, nullable=True)
    publishing_status = Column(String, default="not_published")  # 'not_published', 'scheduled', 'in_progress', 'published', 'failed'
    postmypost_id = Column(String, nullable=True)
    postmypost_file_id = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

class UserPublishChannel(Base):
    __tablename__ = "user_publish_channels"
    __table_args__ = (UniqueConstraint("user_id", "account_id", name="uq_user_account_channel"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    account_id = Column(Integer, index=True, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    publication_description = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
