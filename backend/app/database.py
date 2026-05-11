from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from .models import Base
import os
from dotenv import load_dotenv

load_dotenv()

# engine = create_engine(os.getenv("DATABASE_URL", "sqlite:///./database.db"))
engine = create_engine(os.getenv("DATABASE_URL", "postgresql://user:password@db:5432/postgres"))
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_database() -> None:
    Base.metadata.create_all(bind=engine)
    # Lightweight runtime migration for existing deployments.
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS subtitles_enabled BOOLEAN DEFAULT TRUE"
            )
        )
        conn.execute(
            text("UPDATE users SET subtitles_enabled = TRUE WHERE subtitles_enabled IS NULL")
        )
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS auto_schedule_enabled BOOLEAN DEFAULT FALSE"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS publish_limit_per_day INTEGER DEFAULT 3"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS publish_window_start_msk VARCHAR(16) DEFAULT '10:00:00'"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS publish_window_end_msk VARCHAR(16) DEFAULT '22:00:00'"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS plate_start_percent INTEGER DEFAULT 0"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS author_style_profile TEXT"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS training_source TEXT"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS heygen_avatar_id VARCHAR(128)"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS heygen_vertical_avatar_id VARCHAR(128)"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS elevenlabs_voice_id VARCHAR(128)"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS elevenlabs_voice_speeds JSONB"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS thumbnail_face_path TEXT"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS vertical_thumbnail_face_path TEXT"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_script_duration_minutes INTEGER DEFAULT 5"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_insert_start_percent INTEGER DEFAULT 50"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_insert_end_percent INTEGER DEFAULT 95"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_insert_clips_count INTEGER DEFAULT 2"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS reels_broll_yandex_dir TEXT DEFAULT 'disk:/'"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS reels_broll_start_percent INTEGER DEFAULT 15"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS reels_broll_end_percent INTEGER DEFAULT 85"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS reels_broll_clips_count INTEGER DEFAULT 3"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS reels_broll_coverage_percent INTEGER DEFAULT 50"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS youtube_description_template TEXT"
            )
        )
        conn.execute(
            text("UPDATE users SET auto_schedule_enabled = FALSE WHERE auto_schedule_enabled IS NULL")
        )
        conn.execute(
            text("UPDATE users SET publish_limit_per_day = 3 WHERE publish_limit_per_day IS NULL OR publish_limit_per_day < 1")
        )
        conn.execute(
            text("UPDATE users SET publish_window_start_msk = '10:00:00' WHERE publish_window_start_msk IS NULL OR publish_window_start_msk = ''")
        )
        conn.execute(
            text("UPDATE users SET publish_window_end_msk = '22:00:00' WHERE publish_window_end_msk IS NULL OR publish_window_end_msk = ''")
        )
        conn.execute(
            text("UPDATE users SET plate_start_percent = 0 WHERE plate_start_percent IS NULL")
        )
        conn.execute(
            text("UPDATE users SET avatar_insert_start_percent = 50 WHERE avatar_insert_start_percent IS NULL")
        )
        conn.execute(
            text("UPDATE users SET avatar_insert_end_percent = 95 WHERE avatar_insert_end_percent IS NULL")
        )
        conn.execute(
            text("UPDATE users SET avatar_insert_clips_count = 2 WHERE avatar_insert_clips_count IS NULL")
        )
        conn.execute(
            text(
                "UPDATE users SET reels_broll_yandex_dir = 'disk:/' "
                "WHERE reels_broll_yandex_dir IS NULL OR reels_broll_yandex_dir = '' OR reels_broll_yandex_dir = 'disk:/Broll'"
            )
        )
        conn.execute(
            text("UPDATE users SET reels_broll_start_percent = 15 WHERE reels_broll_start_percent IS NULL")
        )
        conn.execute(
            text("UPDATE users SET reels_broll_end_percent = 85 WHERE reels_broll_end_percent IS NULL")
        )
        conn.execute(
            text("UPDATE users SET reels_broll_clips_count = 3 WHERE reels_broll_clips_count IS NULL")
        )
        conn.execute(
            text("UPDATE users SET reels_broll_coverage_percent = 50 WHERE reels_broll_coverage_percent IS NULL")
        )
        conn.execute(
            text("UPDATE users SET elevenlabs_voice_speeds = '{}'::jsonb WHERE elevenlabs_voice_speeds IS NULL")
        )
        conn.execute(
            text("UPDATE users SET avatar_script_duration_minutes = 5 WHERE avatar_script_duration_minutes IS NULL")
        )
        conn.execute(
            text("UPDATE users SET avatar_script_duration_minutes = 1 WHERE avatar_script_duration_minutes < 1")
        )
        conn.execute(
            text("UPDATE users SET avatar_script_duration_minutes = 30 WHERE avatar_script_duration_minutes > 30")
        )
        conn.execute(
            text("UPDATE users SET avatar_insert_start_percent = 0 WHERE avatar_insert_start_percent < 0")
        )
        conn.execute(
            text("UPDATE users SET avatar_insert_start_percent = 99 WHERE avatar_insert_start_percent > 99")
        )
        conn.execute(
            text("UPDATE users SET avatar_insert_end_percent = 1 WHERE avatar_insert_end_percent < 1")
        )
        conn.execute(
            text("UPDATE users SET avatar_insert_end_percent = 100 WHERE avatar_insert_end_percent > 100")
        )
        conn.execute(
            text(
                "UPDATE users SET avatar_insert_end_percent = avatar_insert_start_percent + 1 "
                "WHERE avatar_insert_end_percent <= avatar_insert_start_percent"
            )
        )
        conn.execute(
            text("UPDATE users SET avatar_insert_clips_count = 0 WHERE avatar_insert_clips_count < 0")
        )
        conn.execute(
            text("UPDATE users SET avatar_insert_clips_count = 20 WHERE avatar_insert_clips_count > 20")
        )
        conn.execute(
            text("UPDATE users SET reels_broll_start_percent = 0 WHERE reels_broll_start_percent < 0")
        )
        conn.execute(
            text("UPDATE users SET reels_broll_start_percent = 99 WHERE reels_broll_start_percent > 99")
        )
        conn.execute(
            text("UPDATE users SET reels_broll_end_percent = 1 WHERE reels_broll_end_percent < 1")
        )
        conn.execute(
            text("UPDATE users SET reels_broll_end_percent = 100 WHERE reels_broll_end_percent > 100")
        )
        conn.execute(
            text(
                "UPDATE users SET reels_broll_end_percent = reels_broll_start_percent + 1 "
                "WHERE reels_broll_end_percent <= reels_broll_start_percent"
            )
        )
        conn.execute(
            text("UPDATE users SET reels_broll_clips_count = 0 WHERE reels_broll_clips_count < 0")
        )
        conn.execute(
            text("UPDATE users SET reels_broll_clips_count = 20 WHERE reels_broll_clips_count > 20")
        )
        conn.execute(
            text("UPDATE users SET reels_broll_coverage_percent = 0 WHERE reels_broll_coverage_percent < 0")
        )
        conn.execute(
            text("UPDATE users SET reels_broll_coverage_percent = 100 WHERE reels_broll_coverage_percent > 100")
        )
        conn.execute(
            text("UPDATE users SET plate_start_percent = 0 WHERE plate_start_percent < 0")
        )
        conn.execute(
            text("UPDATE users SET plate_start_percent = 100 WHERE plate_start_percent > 100")
        )
        conn.execute(
            text(
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS target_account_id INTEGER"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS postmypost_file_id INTEGER"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS telegram_chat_id VARCHAR(64)"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS telegram_status_message_id VARCHAR(64)"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS telegram_status_text TEXT"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS target_platform VARCHAR(32)"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS source_title TEXT"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS preview_url TEXT"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS factual_outline TEXT"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS script_text TEXT"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS script_meta JSONB"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE cta_clips ADD COLUMN IF NOT EXISTS platform VARCHAR(32) DEFAULT 'universal'"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE cta_clips ADD COLUMN IF NOT EXISTS account_id INTEGER"
            )
        )
        conn.execute(
            text("UPDATE cta_clips SET platform = 'universal' WHERE platform IS NULL")
        )
        conn.execute(
            text(
                "ALTER TABLE user_publish_channels ADD COLUMN IF NOT EXISTS publication_description TEXT"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS avatar_insert_clips ("
                "id SERIAL PRIMARY KEY, "
                "user_id INTEGER NOT NULL REFERENCES users(id), "
                "file_path TEXT NOT NULL, "
                "created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()"
                ")"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE thumbnail_references ADD COLUMN IF NOT EXISTS kind VARCHAR(32) DEFAULT 'horizontal'"
            )
        )
        conn.execute(
            text("UPDATE thumbnail_references SET kind = 'horizontal' WHERE kind IS NULL OR kind = ''")
        )
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS thumbnail_face_references ("
                "id SERIAL PRIMARY KEY, "
                "user_id INTEGER NOT NULL REFERENCES users(id), "
                "file_path TEXT NOT NULL, "
                "created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_thumbnail_face_references_user_id "
                "ON thumbnail_face_references(user_id)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO thumbnail_face_references (user_id, file_path, created_at) "
                "SELECT users.id, users.thumbnail_face_path, NOW() "
                "FROM users "
                "WHERE users.thumbnail_face_path IS NOT NULL "
                "AND users.thumbnail_face_path != '' "
                "AND NOT EXISTS ("
                "SELECT 1 FROM thumbnail_face_references refs "
                "WHERE refs.user_id = users.id AND refs.file_path = users.thumbnail_face_path"
                ")"
            )
        )
        conn.execute(
            text(
                "INSERT INTO thumbnail_face_references (user_id, file_path, created_at) "
                "SELECT users.id, users.vertical_thumbnail_face_path, NOW() "
                "FROM users "
                "WHERE users.vertical_thumbnail_face_path IS NOT NULL "
                "AND users.vertical_thumbnail_face_path != '' "
                "AND NOT EXISTS ("
                "SELECT 1 FROM thumbnail_face_references refs "
                "WHERE refs.user_id = users.id AND refs.file_path = users.vertical_thumbnail_face_path"
                ")"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE user_publish_channels ADD COLUMN IF NOT EXISTS selected_plate_id INTEGER"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE user_publish_channels ADD COLUMN IF NOT EXISTS selected_plate_ids JSONB"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE user_publish_channels ADD COLUMN IF NOT EXISTS plate_start_percent INTEGER"
            )
        )
        conn.execute(
            text(
                "UPDATE user_publish_channels SET plate_start_percent = 0 WHERE plate_start_percent IS NOT NULL AND plate_start_percent < 0"
            )
        )
        conn.execute(
            text(
                "UPDATE user_publish_channels SET plate_start_percent = 100 WHERE plate_start_percent IS NOT NULL AND plate_start_percent > 100"
            )
        )
        conn.execute(
            text(
                "UPDATE user_publish_channels SET selected_plate_ids = jsonb_build_array(selected_plate_id) "
                "WHERE selected_plate_id IS NOT NULL AND selected_plate_ids IS NULL"
            )
        )
