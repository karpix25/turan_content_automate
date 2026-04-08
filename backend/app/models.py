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
    selected_plate_id = Column(Integer, nullable=True)

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
    file_path = Column(String)
    label = Column(String)

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
    publish_at = Column(DateTime, nullable=True)
    publishing_status = Column(String, default="not_published")  # 'not_published', 'scheduled', 'in_progress', 'published', 'failed'
    postmypost_id = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

class UserPublishChannel(Base):
    __tablename__ = "user_publish_channels"
    __table_args__ = (UniqueConstraint("user_id", "account_id", name="uq_user_account_channel"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    account_id = Column(Integer, index=True, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
