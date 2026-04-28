import os
from celery import Celery
from dotenv import load_dotenv
from ..integrations.postmypost import PostMyPostClient
from ..integrations.scrape_creators import ScrapeCreatorsClient
from ..integrations.llm import LLMClient

load_dotenv()

# Celery Client
celery_client = Celery("api_client", broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"))

# Integration Clients
pmp_client = PostMyPostClient(api_key=os.getenv("POSTMYPOST_API_KEY", ""))
scraper = ScrapeCreatorsClient(api_key=os.getenv("SCRAPE_CREATORS_API_KEY", ""))
llm = LLMClient(api_key=os.getenv("OPENROUTER_API_KEY", ""))

# Project config
POSTMYPOST_PROJECT_ID = os.getenv("POSTMYPOST_PROJECT_ID", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
HEYGEN_API_KEY = os.getenv("HEYGEN_API_KEY", "")
TELEGRAM_ADMIN_IDS = os.getenv("TELEGRAM_ADMIN_IDS", "")
CORS_ALLOWED_ORIGINS = os.getenv("CORS_ALLOWED_ORIGINS", "")
