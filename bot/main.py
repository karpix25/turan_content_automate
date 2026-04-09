import os
import logging
import httpx
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

@dp.message_handler(regexp=r'(https?://)?(www\.)?(youtube\.com|youtu\.be|instagram\.com)/.+')
async def handle_link(message: types.Message):
    url = message.text
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
