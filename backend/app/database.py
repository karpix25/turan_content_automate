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
