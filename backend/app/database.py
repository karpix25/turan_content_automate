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

DATABASE_INIT_LOCK_KEY = 760145167


def init_database() -> None:
    if engine.url.get_backend_name().startswith("postgresql"):
        with engine.connect() as conn:
            conn.execute(text("SELECT pg_advisory_lock(:lock_key)"), {"lock_key": DATABASE_INIT_LOCK_KEY})
            try:
                _init_database_unlocked()
            finally:
                conn.execute(text("SELECT pg_advisory_unlock(:lock_key)"), {"lock_key": DATABASE_INIT_LOCK_KEY})
                conn.commit()
        return
    _init_database_unlocked()


def _init_database_unlocked() -> None:
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
        add_column_if_missing("users", "postmypost_project_id", "INTEGER")
        add_column_if_missing("users", "author_style_profile", "TEXT")
        add_column_if_missing("users", "training_source", "TEXT")
        add_column_if_missing("users", "style_training_status", "VARCHAR(32)")
        add_column_if_missing("users", "style_training_error", "TEXT")
        add_column_if_missing("users", "style_training_updated_at", "TIMESTAMP WITHOUT TIME ZONE")
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
        add_column_if_missing("tasks", "postmypost_project_id", "INTEGER")
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
        add_column_if_missing("cta_clips", "postmypost_project_id", "INTEGER")
        add_column_if_missing("cta_clips", "account_id", "INTEGER")
        conn.execute(
            text("UPDATE cta_clips SET platform = 'universal' WHERE platform IS NULL")
        )
        add_column_if_missing("user_publish_channels", "publication_description", "TEXT")
        add_column_if_missing("user_publish_channels", "postmypost_project_id", "INTEGER")
        add_column_if_missing("user_publish_channels", "publish_limit_per_day", "INTEGER DEFAULT 3")
        vizard_limit_added = not column_exists("user_publish_channels", "vizard_limit_per_day")
        other_formats_limit_added = not column_exists("user_publish_channels", "other_formats_limit_per_day")
        add_column_if_missing("user_publish_channels", "vizard_limit_per_day", "INTEGER DEFAULT 1")
        add_column_if_missing("user_publish_channels", "other_formats_limit_per_day", "INTEGER DEFAULT 3")
        conn.execute(
            text(
                "UPDATE user_publish_channels SET publish_limit_per_day = 3 "
                "WHERE publish_limit_per_day IS NULL OR publish_limit_per_day < 2"
            )
        )
        if vizard_limit_added:
            conn.execute(
                text(
                    "UPDATE user_publish_channels SET vizard_limit_per_day = GREATEST(1, publish_limit_per_day / 2)"
                )
            )
        else:
            conn.execute(
                text(
                    "UPDATE user_publish_channels SET vizard_limit_per_day = GREATEST(1, LEAST(publish_limit_per_day, vizard_limit_per_day)) "
                    "WHERE vizard_limit_per_day IS NULL OR vizard_limit_per_day < 1 OR vizard_limit_per_day > publish_limit_per_day"
                )
            )
        if other_formats_limit_added:
            conn.execute(
                text(
                    "UPDATE user_publish_channels SET other_formats_limit_per_day = publish_limit_per_day"
                )
            )
        else:
            conn.execute(
                text(
                    "UPDATE user_publish_channels SET other_formats_limit_per_day = GREATEST(1, LEAST(publish_limit_per_day, other_formats_limit_per_day)) "
                    "WHERE other_formats_limit_per_day IS NULL OR other_formats_limit_per_day < 1 OR other_formats_limit_per_day > publish_limit_per_day"
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
        if not table_exists("broll_assets"):
            conn.execute(
                text(
                    "CREATE TABLE broll_assets ("
                    "id SERIAL PRIMARY KEY, "
                    "user_id INTEGER NOT NULL REFERENCES users(id), "
                    "postmypost_project_id INTEGER NOT NULL, "
                    "file_path TEXT NOT NULL, "
                    "original_filename TEXT NOT NULL, "
                    "is_active BOOLEAN NOT NULL DEFAULT TRUE, "
                    "created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()"
                    ")"
                )
            )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_broll_assets_user_project "
                "ON broll_assets(user_id, postmypost_project_id)"
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
        add_column_if_missing("plates", "postmypost_project_id", "INTEGER")
        add_column_if_missing("plates", "account_id", "INTEGER")
        if not table_exists("postmypost_project_settings"):
            conn.execute(
                text(
                    "CREATE TABLE postmypost_project_settings ("
                    "id SERIAL PRIMARY KEY, "
                    "user_id INTEGER NOT NULL REFERENCES users(id), "
                    "project_id INTEGER NOT NULL, "
                    "uniqueization_mode VARCHAR(32) NOT NULL DEFAULT 'auto', "
                    "created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(), "
                    "updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()"
                    ")"
                )
            )
        add_column_if_missing("postmypost_project_settings", "uniqueization_mode", "VARCHAR(32) DEFAULT 'auto'")
        project_limit_added = not column_exists("postmypost_project_settings", "publish_limit_per_day")
        project_vizard_limit_added = not column_exists("postmypost_project_settings", "vizard_limit_per_day")
        project_other_limit_added = not column_exists("postmypost_project_settings", "other_formats_limit_per_day")
        add_column_if_missing("postmypost_project_settings", "publish_limit_per_day", "INTEGER DEFAULT 3")
        add_column_if_missing("postmypost_project_settings", "vizard_limit_per_day", "INTEGER DEFAULT 1")
        add_column_if_missing("postmypost_project_settings", "other_formats_limit_per_day", "INTEGER DEFAULT 3")
        add_column_if_missing("postmypost_project_settings", "instagram_post_5s_cta_text", "TEXT")
        add_column_if_missing("postmypost_project_settings", "instagram_post_5s_image_prompt", "TEXT")
        add_column_if_missing("postmypost_project_settings", "carousel_ctas", "JSONB")
        add_column_if_missing("postmypost_project_settings", "story_ctas", "JSONB")
        add_column_if_missing("carousel_drafts", "source_post_ids", "JSONB")
        add_column_if_missing("carousel_drafts", "story_slide_count", "INTEGER DEFAULT 1")
        add_column_if_missing("carousel_drafts", "story_reference_paths", "JSONB")
        add_column_if_missing("carousel_drafts", "story_ctas", "JSONB")
        add_column_if_missing("carousel_drafts", "story_slides", "JSONB")
        conn.execute(
            text(
                "UPDATE carousel_drafts SET story_slide_count = COALESCE(story_slide_count, slide_count, 1) "
                "WHERE story_slide_count IS NULL"
            )
        )
        conn.execute(
            text(
                "UPDATE postmypost_project_settings pps "
                "SET instagram_post_5s_cta_text = users.instagram_post_5s_cta_text "
                "FROM users "
                "WHERE pps.user_id = users.id "
                "AND pps.instagram_post_5s_cta_text IS NULL "
                "AND users.instagram_post_5s_cta_text IS NOT NULL"
            )
        )
        conn.execute(
            text(
                "UPDATE postmypost_project_settings pps "
                "SET instagram_post_5s_image_prompt = users.instagram_post_5s_image_prompt "
                "FROM users "
                "WHERE pps.user_id = users.id "
                "AND pps.instagram_post_5s_image_prompt IS NULL "
                "AND users.instagram_post_5s_image_prompt IS NOT NULL"
            )
        )
        conn.execute(
            text(
                "UPDATE postmypost_project_settings "
                "SET uniqueization_mode = 'auto' "
                "WHERE uniqueization_mode IS NULL "
                "OR uniqueization_mode NOT IN ('auto', 'light', 'standard', 'aggressive', 'off')"
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_postmypost_project_setting_idx "
                "ON postmypost_project_settings(user_id, project_id)"
            )
        )
        conn.execute(
            text(
                "UPDATE user_publish_channels upc "
                "SET postmypost_project_id = users.postmypost_project_id "
                "FROM users "
                "WHERE upc.user_id = users.id "
                "AND upc.postmypost_project_id IS NULL "
                "AND NOT EXISTS ("
                "SELECT 1 FROM user_publish_channels existing "
                "WHERE existing.user_id = upc.user_id "
                "AND existing.account_id = upc.account_id "
                "AND existing.postmypost_project_id = users.postmypost_project_id"
                ")"
            )
        )
        conn.execute(
            text(
                "INSERT INTO postmypost_project_settings "
                "(user_id, project_id, publish_limit_per_day, vizard_limit_per_day, other_formats_limit_per_day) "
                "SELECT upc.user_id, upc.postmypost_project_id, "
                "GREATEST(2, LEAST(96, MIN(COALESCE(upc.publish_limit_per_day, 3)))), "
                "GREATEST(1, MIN(COALESCE(upc.vizard_limit_per_day, 1))), "
                "GREATEST(1, MIN(COALESCE(upc.other_formats_limit_per_day, 3))) "
                "FROM user_publish_channels upc "
                "WHERE upc.postmypost_project_id IS NOT NULL "
                "AND NOT EXISTS ("
                "SELECT 1 FROM postmypost_project_settings existing "
                "WHERE existing.user_id = upc.user_id "
                "AND existing.project_id = upc.postmypost_project_id"
                ") "
                "GROUP BY upc.user_id, upc.postmypost_project_id"
            )
        )
        if project_limit_added:
            conn.execute(
                text(
                    "UPDATE postmypost_project_settings pps SET publish_limit_per_day = COALESCE(("
                    "SELECT MIN(COALESCE(upc.publish_limit_per_day, 3)) FROM user_publish_channels upc "
                    "WHERE upc.user_id = pps.user_id AND upc.postmypost_project_id = pps.project_id AND upc.enabled = TRUE"
                    "), pps.publish_limit_per_day)"
                )
            )
        if project_vizard_limit_added:
            conn.execute(
                text(
                    "UPDATE postmypost_project_settings pps SET vizard_limit_per_day = COALESCE(("
                    "SELECT MIN(COALESCE(upc.vizard_limit_per_day, 1)) FROM user_publish_channels upc "
                    "WHERE upc.user_id = pps.user_id AND upc.postmypost_project_id = pps.project_id AND upc.enabled = TRUE"
                    "), pps.vizard_limit_per_day)"
                )
            )
        if project_other_limit_added:
            conn.execute(
                text(
                    "UPDATE postmypost_project_settings pps SET other_formats_limit_per_day = COALESCE(("
                    "SELECT MIN(COALESCE(upc.other_formats_limit_per_day, 3)) FROM user_publish_channels upc "
                    "WHERE upc.user_id = pps.user_id AND upc.postmypost_project_id = pps.project_id AND upc.enabled = TRUE"
                    "), pps.other_formats_limit_per_day)"
                )
            )
        conn.execute(
            text(
                "UPDATE postmypost_project_settings pps SET "
                "publish_limit_per_day = GREATEST(2, LEAST(96, COALESCE(pps.publish_limit_per_day, 3))), "
                "vizard_limit_per_day = GREATEST(1, LEAST(COALESCE(pps.publish_limit_per_day, 3), COALESCE(pps.vizard_limit_per_day, 1))), "
                "other_formats_limit_per_day = GREATEST(1, LEAST(COALESCE(pps.publish_limit_per_day, 3), COALESCE(pps.other_formats_limit_per_day, 3)))"
            )
        )
        conn.execute(
            text(
                "UPDATE tasks "
                "SET postmypost_project_id = users.postmypost_project_id "
                "FROM users "
                "WHERE tasks.user_id = users.id AND tasks.postmypost_project_id IS NULL"
            )
        )
        conn.execute(
            text(
                "UPDATE cta_clips "
                "SET postmypost_project_id = users.postmypost_project_id "
                "FROM users "
                "WHERE cta_clips.user_id = users.id AND cta_clips.postmypost_project_id IS NULL"
            )
        )
        conn.execute(
            text(
                "UPDATE plates "
                "SET postmypost_project_id = users.postmypost_project_id "
                "FROM users "
                "WHERE plates.user_id = users.id AND plates.postmypost_project_id IS NULL"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE user_publish_channels DROP CONSTRAINT IF EXISTS uq_user_account_channel"
            )
        )
        conn.execute(
            text("DROP INDEX IF EXISTS uq_user_project_account_channel_idx")
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_project_account_channel_idx "
                "ON user_publish_channels(user_id, COALESCE(postmypost_project_id, 0), account_id)"
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
