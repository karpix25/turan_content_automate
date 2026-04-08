from sqlalchemy import create_all, create_engine
from sqlalchemy.orm import sessionmaker
from .models import Base
import os
from dotenv import load_dotenv

load_dotenv()

# engine = create_engine(os.getenv("DATABASE_URL", "sqlite:///./database.db"))
engine = create_engine(os.getenv("DATABASE_URL", "postgresql://user:password@db:5432/postgres"))
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
