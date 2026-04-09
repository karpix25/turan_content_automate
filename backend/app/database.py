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
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS target_account_id INTEGER"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE cta_clips ADD COLUMN IF NOT EXISTS platform VARCHAR(32) DEFAULT 'universal'"
            )
        )
        conn.execute(
            text("UPDATE cta_clips SET platform = 'universal' WHERE platform IS NULL")
        )
