import os
import logging
import re
import httpx
from urllib.parse import urlparse, parse_qs
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

load_dotenv()

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL")
BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://api:8000")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

SUPPORTED_URL_RE = re.compile(r"(https?://[^\s]+|(?:www\.)?(?:youtube\.com|youtu\.be|instagram\.com)/[^\s]+)", re.IGNORECASE)

def extract_youtube_video_id(url: str) -> str | None:
    parsed = urlparse((url or "").strip())
    host = parsed.netloc.lower()
    path_parts = [part for part in parsed.path.split("/") if part]

    if "youtu.be" in host:
        candidate = path_parts[0] if path_parts else ""
        return candidate if len(candidate) == 11 else None

    if "youtube.com" in host:
        if len(path_parts) >= 2 and path_parts[0] == "shorts":
            candidate = path_parts[1]
            return candidate if len(candidate) == 11 else None
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [""])[0]
            return candidate if len(candidate) == 11 else None

    return None


def normalize_youtube_url(url: str) -> str:
    video_id = extract_youtube_video_id(url)
    return f"https://www.youtube.com/watch?v={video_id}" if video_id else url


def normalize_source_url(text: str) -> str | None:
    if not text:
        return None
    match = SUPPORTED_URL_RE.search(text)
    if not match:
        return None
    url = match.group(0).strip().strip("<>()[]{}\"'.,;")
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    if "youtube.com" in url or "youtu.be" in url:
        url = normalize_youtube_url(url)
    return url


def is_valid_youtube_url(url: str) -> bool:
    return extract_youtube_video_id(url) is not None


def detect_task_type(url: str) -> str:
    task_type = "youtube"
    if "instagram.com" in url:
        return "instagram"
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    return task_type

@dp.message_handler(commands=['start', 'help'])
async def send_welcome(message: types.Message):
    """
    Welcomes user and provides the Settings button.
    """
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("⚙️ Settings (Mini App)", web_app=types.WebAppInfo(url=WEBAPP_URL)))
    
    await message.reply(
        "Welcome to the Content Processor Bot!\n\n"
        "1. Open Settings to upload your logo and choose subtitle styles.\n"
        "2. Send me a link to a YouTube video or Instagram Reel.\n"
        "3. I will process it and send you the result!",
        reply_markup=kb
    )

@dp.message_handler(commands=['id'])
async def send_user_id(message: types.Message):
    await message.reply(f"Ваш Telegram ID: `{message.from_user.id}`", parse_mode="Markdown")

@dp.message_handler(regexp=r'(https?://)?(www\.)?(youtube\.com|youtu\.be|instagram\.com)/.+')
async def handle_link(message: types.Message):
    raw_text = message.text or ""
    url = normalize_source_url(raw_text)
    if not url:
        await message.reply("❌ Не удалось распознать ссылку. Отправь прямую ссылку на YouTube/Instagram.")
        return

    if ("youtube.com" in url or "youtu.be" in url) and not is_valid_youtube_url(url):
        await message.reply("❌ Похоже, ссылка на YouTube/Shorts битая (некорректный ID видео).")
        return

    user_id = str(message.from_user.id)
    task_type = detect_task_type(url)

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{BACKEND_API_URL}/tasks/{user_id}",
                json={"source_url": url, "type": task_type},
            )
        response.raise_for_status()

        await message.reply(f"🚀 Task received! Type: {task_type.upper()}. I'll notify you when it's ready.")

    except Exception as e:
        logging.error(f"Error handling link: {e}")
        await message.reply("❌ Sorry, something went wrong while creating the task.")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
