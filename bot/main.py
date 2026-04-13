import os
import logging
import re
import httpx
import json
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
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

SUPPORTED_URL_RE = re.compile(r"(https?://[^\s]+|(?:www\.)?(?:youtube\.com|youtu\.be|instagram\.com|vizard\.ai)/[^\s]+)", re.IGNORECASE)

def extract_vizard_project_id(url: str) -> str | None:
    raw = (url or "").strip()
    # Handle forms like vizard.ai/project/12345 or vizard.ai/dashboard/editor/12345
    match = re.search(r"vizard\.ai/(?:project|dashboard/editor)/(\d+)", raw, re.IGNORECASE)
    if match:
        return match.group(1)
    if raw.isdigit():
        return raw
    return None


def extract_youtube_video_id(url: str) -> str | None:
    raw = (url or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", raw):
        return raw

    parsed = urlparse(raw)
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
    if not video_id:
        return url

    raw = (url or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", raw):
        return f"https://www.youtube.com/watch?v={video_id}"

    parsed = urlparse(raw)
    host = parsed.netloc.lower()
    path_parts = [part for part in parsed.path.split("/") if part]

    if "youtube.com" in host and len(path_parts) >= 2 and path_parts[0] == "shorts":
        return f"https://www.youtube.com/shorts/{video_id}"

    return f"https://www.youtube.com/watch?v={video_id}"


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
    elif "vizard.ai" in url:
        v_id = extract_vizard_project_id(url)
        if v_id:
            url = v_id
    return url



def is_valid_youtube_url(url: str) -> bool:
    return extract_youtube_video_id(url) is not None


def detect_task_type(url: str) -> str:
    task_type = "youtube"
    if "instagram.com" in url:
        return "instagram"
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    if "vizard.ai" in url or (url.isdigit() and len(url) > 5):
        return "vizard"
    return task_type



def is_youtube_shorts_url(url: str) -> bool:
    raw = (url or "").strip()
    if not raw or re.fullmatch(r"[A-Za-z0-9_-]{11}", raw):
        return False

    parsed = urlparse(raw)
    host = parsed.netloc.lower()
    path_parts = [part for part in parsed.path.split("/") if part]
    return "youtube.com" in host and len(path_parts) >= 2 and path_parts[0] == "shorts"


async def create_task_in_backend(user_id: str, url: str, task_type: str, status_message: types.Message):
    """
    Helper to trigger task creation in backend and update status message.
    """
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{BACKEND_API_URL}/tasks/{user_id}",
                json={
                    "source_url": url,
                    "type": task_type,
                    "telegram_chat_id": str(status_message.chat.id),
                    "telegram_status_message_id": str(status_message.message_id),
                },
            )
        response.raise_for_status()
        payload = response.json()
        task_id = payload.get("task_id")

        await status_message.edit_text(
            "\n".join(
                [
                    f"⏳ Видео #{task_id}" if task_id else "⏳ Видео",
                    "Этап: задача создана",
                    "Видео добавлено в очередь обработки.",
                ]
            ),
            disable_web_page_preview=True,
        )
    except Exception as e:
        logging.error(f"Error creating task: {e}")
        try:
            await status_message.edit_text(
                "❌ Ошибка\nЭтап: создание задачи\nНе удалось поставить видео в обработку.",
                disable_web_page_preview=True,
            )
        except Exception:
            await status_message.answer("❌ Sorry, something went wrong while creating the task.")


def build_webapp_url_for_user(base_url: str, telegram_user_id: int) -> str:
    raw = (base_url or "").strip()
    if not raw:
        return raw
    parsed = urlparse(raw)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["tg_id"] = [str(telegram_user_id)]
    encoded_query = urlencode(query, doseq=True)
    return urlunparse(parsed._replace(query=encoded_query))


@dp.message_handler(commands=['start', 'help'])
async def send_welcome(message: types.Message):
    """
    Welcomes user and provides the Settings button.
    """
    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton(
            "⚙️ Settings (Mini App)",
            web_app=types.WebAppInfo(url=build_webapp_url_for_user(WEBAPP_URL, message.from_user.id)),
        )
    )
    
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

@dp.message_handler(regexp=r'(https?://)?(www\.)?(youtube\.com|youtu\.be|instagram\.com|vizard\.ai)/.+')
async def handle_link(message: types.Message):
    raw_text = message.text or ""
    task_type = detect_task_type(raw_text)
    url = normalize_source_url(raw_text)
    if not url:
        await message.reply("❌ Не удалось распознать ссылку. Отправь прямую ссылку на YouTube/Instagram.")
        return

    if task_type == "youtube" and not is_valid_youtube_url(url):
        await message.reply("❌ Похоже, ссылка на YouTube/Shorts битая (некорректный ID видео).")
        return

    user_id = str(message.from_user.id)
    is_youtube = "youtube.com" in url or "youtu.be" in url
    is_shorts = is_youtube and is_youtube_shorts_url(url)

    # For long YouTube videos, ask the user for choice.
    if is_youtube and not is_shorts:
        # ... (unchanged long video logic)
        video_id = extract_youtube_video_id(url)
        kb = {
            "inline_keyboard": [
                [
                    {
                        "text": "🎬 Отправить в VIZARD",
                        "callback_data": f"vizard:yt:{video_id}",
                        "style": "primary"
                    }
                ],
                [
                    {
                        "text": "👤 Создать ролик с аватаром",
                        "callback_data": f"avatar:yt:{video_id}",
                        "style": "success"
                    }
                ]
            ]
        }
        await message.reply(
            "📹 Это длинное видео. Что вы хотите сделать?",
            reply_markup=json.dumps(kb)
        )
        return

    # Automatically process Instagram, YouTube Shorts, and Vizard project links.
    status_message = await message.reply("⏳ Получил ссылку\nЭтап: создаю задачу.")
    await create_task_in_backend(user_id, url, task_type, status_message)



@dp.callback_query_handler(lambda c: c.data and c.data.startswith(('vizard:', 'avatar:')))
async def process_choice(callback_query: types.CallbackQuery):
    data = callback_query.data
    parts = data.split(":")
    if len(parts) < 3:
        return
    
    service, platform, identifier = parts[0], parts[1], parts[2]
    
    if service == "avatar":
        await callback_query.answer("👤 Эта функция находится в разработке и будет доступна позже.", show_alert=True)
        return
    
    # Process Vizard choice
    url = f"https://www.youtube.com/watch?v={identifier}" if platform == "yt" else identifier
    
    await callback_query.answer("Запускаю Vizard...")
    
    # We create a new status message to show progress
    status_message = await bot.send_message(
        callback_query.message.chat.id,
        "⏳ Выбран Vizard\nЭтап: создаю задачу."
    )
    
    await create_task_in_backend(str(callback_query.from_user.id), url, "youtube", status_message)
    
    # Optionally remove the selection keyboard
    try:
        await callback_query.message.delete()
    except Exception:
        pass

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
