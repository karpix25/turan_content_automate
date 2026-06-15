from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from .models import Base
import os
from dotenv import load_dotenv

load_dotenv()

# engine = create_engine(os.getenv("DATABASE_URL", "sqlite:///./database.db"))
engine = create_engine(
    os.getenv("DATABASE_URL", "postgresql://user:password@db:5432/postgres"),
    pool_pre_ping=True,
    pool_recycle=int(os.getenv("DATABASE_POOL_RECYCLE_SECONDS", "300")),
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_database() -> None:
    Base.metadata.create_all(bind=engine)
    # Lightweight runtime migration for existing deployments.
    with engine.begin() as conn:
        def column_exists(table_name: str, column_name: str) -> bool:
            return bool(
                conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_schema = current_schema() "
                        "AND table_name = :table_name "
                        "AND column_name = :column_name"
                    ),
                    {"table_name": table_name, "column_name": column_name},
                ).scalar()
            )

        def table_exists(table_name: str) -> bool:
            return bool(
                conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.tables "
                        "WHERE table_schema = current_schema() "
                        "AND table_name = :table_name"
                    ),
                    {"table_name": table_name},
                ).scalar()
            )

        def add_column_if_missing(table_name: str, column_name: str, definition: str) -> None:
            if not column_exists(table_name, column_name):
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"))

        add_column_if_missing("users", "subtitles_enabled", "BOOLEAN DEFAULT TRUE")
        conn.execute(
            text("UPDATE users SET subtitles_enabled = TRUE WHERE subtitles_enabled IS NULL")
        )
        add_column_if_missing("users", "auto_schedule_enabled", "BOOLEAN DEFAULT FALSE")
        add_column_if_missing("users", "publish_limit_per_day", "INTEGER DEFAULT 3")
        add_column_if_missing("users", "publish_window_start_msk", "VARCHAR(16) DEFAULT '10:00:00'")
        add_column_if_missing("users", "publish_window_end_msk", "VARCHAR(16) DEFAULT '22:00:00'")
        add_column_if_missing("users", "plate_start_percent", "INTEGER DEFAULT 0")
        add_column_if_missing("users", "author_style_profile", "TEXT")
        add_column_if_missing("users", "training_source", "TEXT")
        add_column_if_missing("users", "heygen_avatar_id", "VARCHAR(128)")
        add_column_if_missing("users", "heygen_vertical_avatar_id", "VARCHAR(128)")
        add_column_if_missing("users", "heygen_video_api_version", "VARCHAR(16) DEFAULT 'v2'")
        add_column_if_missing("users", "heygen_avatar_engine", "VARCHAR(32) DEFAULT 'avatar_iv'")
        add_column_if_missing("users", "elevenlabs_voice_id", "VARCHAR(128)")
        add_column_if_missing("users", "elevenlabs_voice_speeds", "JSONB")
        add_column_if_missing("users", "thumbnail_face_path", "TEXT")
        add_column_if_missing("users", "vertical_thumbnail_face_path", "TEXT")
        add_column_if_missing("users", "avatar_script_duration_minutes", "INTEGER DEFAULT 5")
        add_column_if_missing("users", "avatar_vertical_duration_seconds", "INTEGER DEFAULT 0")
        add_column_if_missing("users", "avatar_insert_start_percent", "INTEGER DEFAULT 50")
        add_column_if_missing("users", "avatar_insert_end_percent", "INTEGER DEFAULT 95")
        add_column_if_missing("users", "avatar_insert_clips_count", "INTEGER DEFAULT 2")
        add_column_if_missing("users", "avatar_overlay_x_percent", "INTEGER DEFAULT 70")
        add_column_if_missing("users", "avatar_overlay_y_percent", "INTEGER DEFAULT 100")
        add_column_if_missing("users", "avatar_overlay_size_percent", "INTEGER DEFAULT 61")
        add_column_if_missing("users", "avatar_overlay_opacity_percent", "INTEGER DEFAULT 100")
        add_column_if_missing("users", "reels_broll_yandex_dir", "TEXT DEFAULT 'disk:/Видео для REELS'")
        add_column_if_missing("users", "reels_broll_start_percent", "INTEGER DEFAULT 15")
        add_column_if_missing("users", "reels_broll_end_percent", "INTEGER DEFAULT 85")
        add_column_if_missing("users", "reels_broll_clips_count", "INTEGER DEFAULT 3")
        add_column_if_missing("users", "reels_broll_coverage_percent", "INTEGER DEFAULT 50")
        add_column_if_missing("users", "youtube_description_template", "TEXT")
        add_column_if_missing("users", "instagram_post_5s_audio_profile", "TEXT")
        add_column_if_missing("users", "instagram_post_5s_audio_status", "VARCHAR(32)")
        add_column_if_missing("users", "instagram_post_5s_audio_error", "TEXT")
        add_column_if_missing("users", "instagram_post_5s_audio_refreshed_at", "TIMESTAMP WITHOUT TIME ZONE")
        add_column_if_missing("users", "instagram_post_5s_overlay_path", "TEXT")
        add_column_if_missing("users", "instagram_post_5s_cta_text", "TEXT")
        add_column_if_missing("users", "instagram_post_5s_image_prompt", "TEXT")
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
            text("UPDATE users SET avatar_overlay_x_percent = 70 WHERE avatar_overlay_x_percent IS NULL")
        )
        conn.execute(
            text("UPDATE users SET avatar_overlay_y_percent = 100 WHERE avatar_overlay_y_percent IS NULL")
        )
        conn.execute(
            text("UPDATE users SET avatar_overlay_size_percent = 61 WHERE avatar_overlay_size_percent IS NULL")
        )
        conn.execute(
            text("UPDATE users SET avatar_overlay_opacity_percent = 100 WHERE avatar_overlay_opacity_percent IS NULL")
        )
        conn.execute(
            text(
                "UPDATE users SET reels_broll_yandex_dir = 'disk:/Видео для REELS' "
                "WHERE reels_broll_yandex_dir IS NULL "
                "OR reels_broll_yandex_dir = '' "
                "OR reels_broll_yandex_dir IN ('disk:/', 'disk:/Broll')"
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
            text(
                "UPDATE users SET heygen_avatar_engine = 'avatar_iv' "
                "WHERE heygen_avatar_engine IS NULL "
                "OR heygen_avatar_engine NOT IN ('avatar_iv', 'avatar_v')"
            )
        )
        conn.execute(
            text(
                "UPDATE users SET heygen_video_api_version = 'v2' "
                "WHERE heygen_video_api_version IS NULL "
                "OR heygen_video_api_version NOT IN ('v2', 'v3')"
            )
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
            text("UPDATE users SET avatar_vertical_duration_seconds = 0 WHERE avatar_vertical_duration_seconds IS NULL OR avatar_vertical_duration_seconds < 0")
        )
        conn.execute(
            text("UPDATE users SET avatar_vertical_duration_seconds = 300 WHERE avatar_vertical_duration_seconds > 300")
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
            text("UPDATE users SET avatar_overlay_x_percent = 0 WHERE avatar_overlay_x_percent < 0")
        )
        conn.execute(
            text("UPDATE users SET avatar_overlay_x_percent = 100 WHERE avatar_overlay_x_percent > 100")
        )
        conn.execute(
            text("UPDATE users SET avatar_overlay_y_percent = 0 WHERE avatar_overlay_y_percent < 0")
        )
        conn.execute(
            text("UPDATE users SET avatar_overlay_y_percent = 100 WHERE avatar_overlay_y_percent > 100")
        )
        conn.execute(
            text("UPDATE users SET avatar_overlay_size_percent = 5 WHERE avatar_overlay_size_percent < 5")
        )
        conn.execute(
            text("UPDATE users SET avatar_overlay_size_percent = 100 WHERE avatar_overlay_size_percent > 100")
        )
        conn.execute(
            text("UPDATE users SET avatar_overlay_opacity_percent = 0 WHERE avatar_overlay_opacity_percent < 0")
        )
        conn.execute(
            text("UPDATE users SET avatar_overlay_opacity_percent = 100 WHERE avatar_overlay_opacity_percent > 100")
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
        add_column_if_missing("tasks", "target_account_id", "INTEGER")
        add_column_if_missing("tasks", "postmypost_file_id", "INTEGER")
        add_column_if_missing("tasks", "telegram_chat_id", "VARCHAR(64)")
        add_column_if_missing("tasks", "telegram_status_message_id", "VARCHAR(64)")
        add_column_if_missing("tasks", "telegram_reply_message_id", "VARCHAR(64)")
        add_column_if_missing("tasks", "telegram_status_text", "TEXT")
        add_column_if_missing("tasks", "target_platform", "VARCHAR(32)")
        add_column_if_missing("tasks", "source_title", "TEXT")
        add_column_if_missing("tasks", "preview_url", "TEXT")
        add_column_if_missing("tasks", "factual_outline", "TEXT")
        add_column_if_missing("tasks", "script_text", "TEXT")
        add_column_if_missing("tasks", "script_meta", "JSONB")
        add_column_if_missing("cta_clips", "platform", "VARCHAR(32) DEFAULT 'universal'")
        add_column_if_missing("cta_clips", "account_id", "INTEGER")
        conn.execute(
            text("UPDATE cta_clips SET platform = 'universal' WHERE platform IS NULL")
        )
        add_column_if_missing("user_publish_channels", "publication_description", "TEXT")
        add_column_if_missing("user_publish_channels", "publish_limit_per_day", "INTEGER DEFAULT 3")
        conn.execute(
            text(
                "UPDATE user_publish_channels SET publish_limit_per_day = 3 "
                "WHERE publish_limit_per_day IS NULL OR publish_limit_per_day < 2"
            )
        )
        if not table_exists("avatar_insert_clips"):
            conn.execute(
                text(
                    "CREATE TABLE avatar_insert_clips ("
                    "id SERIAL PRIMARY KEY, "
                    "user_id INTEGER NOT NULL REFERENCES users(id), "
                    "file_path TEXT NOT NULL, "
                    "created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()"
                    ")"
                )
            )
        if not table_exists("instagram_post_5s_audio_tracks"):
            conn.execute(
                text(
                    "CREATE TABLE instagram_post_5s_audio_tracks ("
                    "id SERIAL PRIMARY KEY, "
                    "user_id INTEGER NOT NULL REFERENCES users(id), "
                    "source_profile TEXT, "
                    "source_url TEXT, "
                    "source_code TEXT, "
                    "file_path TEXT NOT NULL, "
                    "created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()"
                    ")"
                )
            )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_instagram_post_5s_audio_tracks_user_id "
                "ON instagram_post_5s_audio_tracks(user_id)"
            )
        )
        add_column_if_missing("thumbnail_references", "kind", "VARCHAR(32) DEFAULT 'horizontal'")
        conn.execute(
            text("UPDATE thumbnail_references SET kind = 'horizontal' WHERE kind IS NULL OR kind = ''")
        )
        if not table_exists("thumbnail_face_references"):
            conn.execute(
                text(
                    "CREATE TABLE thumbnail_face_references ("
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
        add_column_if_missing("user_publish_channels", "selected_plate_id", "INTEGER")
        add_column_if_missing("user_publish_channels", "selected_plate_ids", "JSONB")
        add_column_if_missing("user_publish_channels", "plate_start_percent", "INTEGER")
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
