import os
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.orm import Session
from backend.app.database import SessionLocal
from backend.app import models
from backend.app.worker import process_content_task
from dotenv import load_dotenv

load_dotenv()

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

def get_db():
    db = SessionLocal()
    try:
        return db
    finally:
        db.close()

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
    
    db = SessionLocal()
    try:
        # Get or create user
        user = db.query(models.User).filter(models.User.telegram_id == user_id).first()
        if not user:
            user = models.User(telegram_id=user_id)
            db.add(user)
            db.commit()
            db.refresh(user)

        # Detect type
        task_type = "youtube"
        if "instagram.com" in url:
            task_type = "instagram"
        elif "youtube.com" in url or "youtu.be" in url:
            # Check if it's long or short (simplified)
            if "/shorts/" in url:
                task_type = "youtube"
            else:
                task_type = "vizard"

        # Create Task
        new_task = models.VideoTask(
            user_id=user.id,
            source_url=url,
            type=task_type,
            status="pending"
        )
        db.add(new_task)
        db.commit()
        db.refresh(new_task)

        # Trigger Celery
        process_content_task.delay(new_task.id)

        await message.reply(f"🚀 Task received! Type: {task_type.upper()}. I'll notify you when it's ready.")

    except Exception as e:
        logging.error(f"Error handling link: {e}")
        await message.reply("❌ Sorry, something went wrong while creating the task.")
    finally:
        db.close()

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
