import os
import logging
import re
import httpx
import json
import time
import uuid
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

from postmypost_project_flow import (
    pop_pending_project_task,
    prompt_postmypost_project_choice as prompt_postmypost_project_choice_flow,
)
from carousel_flow import register_carousel_handlers

load_dotenv()

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL")
BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://api:8000")
WEBAPP_CACHE_BUST = (os.getenv("WEBAPP_CACHE_BUST") or str(int(time.time()))).strip()

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)
PENDING_THUMBNAIL_PROMPT_EDITS: dict[str, int] = {}

SUPPORTED_URL_RE = re.compile(r"(https?://[^\s]+|(?:www\.)?(?:youtube\.com|youtu\.be|instagram\.com|tiktok\.com|vm\.tiktok\.com|vizard\.ai)/[^\s]+)", re.IGNORECASE)
PENDING_SOURCE_CHOICES: dict[str, dict[str, object]] = {}


def strip_keyboard_styles(markup):
    if not isinstance(markup, dict):
        return markup
    cleaned = {"inline_keyboard": []}
    for row in markup.get("inline_keyboard", []):
        cleaned_row = []
        for button in row:
            if isinstance(button, dict):
                item = dict(button)
                item.pop("style", None)
                cleaned_row.append(item)
        if cleaned_row:
            cleaned["inline_keyboard"].append(cleaned_row)
    return cleaned


async def reply_with_keyboard(message: types.Message, text: str, kb: dict, **kwargs):
    try:
        return await message.reply(text, reply_markup=json.dumps(kb), **kwargs)
    except Exception:
        logging.exception("Failed to send styled inline keyboard, retrying without button styles")
        return await message.reply(text, reply_markup=json.dumps(strip_keyboard_styles(kb)), **kwargs)


async def remove_inline_keyboard(message: types.Message | None) -> None:
    if not message:
        return
    try:
        await bot.edit_message_reply_markup(
            chat_id=message.chat.id,
            message_id=message.message_id,
            reply_markup=None,
        )
    except Exception:
        pass


register_carousel_handlers(dp, bot, BACKEND_API_URL, remove_inline_keyboard)


def remember_source_choice(url: str) -> str:
    now = time.time()
    for token, pending in list(PENDING_SOURCE_CHOICES.items()):
        if now - float(pending.get("created_at", 0)) > 1800:
            PENDING_SOURCE_CHOICES.pop(token, None)
    token = uuid.uuid4().hex[:10]
    PENDING_SOURCE_CHOICES[token] = {"url": url, "created_at": now}
    return token


def pop_source_choice(token: str) -> str | None:
    pending = PENDING_SOURCE_CHOICES.pop(token, None)
    url = pending.get("url") if pending else None
    return str(url) if isinstance(url, str) else None

def extract_vizard_project_id(url: str) -> str | None:
    raw = (url or "").strip()
    # Remove https:// if it was accidentally prepended to a pure digit ID
    if raw.startswith("https://") and raw[8:].isdigit():
        raw = raw[8:]
    elif raw.startswith("http://") and raw[7:].isdigit():
        raw = raw[7:]
    
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
    
    # Check for Vizard ID first to prevent adding https://
    v_id = extract_vizard_project_id(url)
    if v_id:
        return v_id

    if not url.startswith(("http://", "https://")) and not url.isdigit():
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
    if "tiktok.com" in url:
        return "tiktok"
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    if "vizard.ai" in url or (url.isdigit() and len(url) > 5):
        return "vizard"
    return task_type


def extract_heygen_video_id(value: str) -> str | None:
    raw = (value or "").strip()
    if raw.lower().startswith("heygen:"):
        raw = raw.split(":", 1)[1].strip()
    if re.fullmatch(r"[0-9a-fA-F]{32}", raw):
        return raw
    return None



def is_youtube_shorts_url(url: str) -> bool:
    raw = (url or "").strip()
    if not raw or re.fullmatch(r"[A-Za-z0-9_-]{11}", raw):
        return False

    parsed = urlparse(raw)
    host = parsed.netloc.lower()
    path_parts = [part for part in parsed.path.split("/") if part]
    return "youtube.com" in host and len(path_parts) >= 2 and path_parts[0] == "shorts"


def extract_instagram_shortcode(url: str) -> tuple[str, str] | None:
    raw = (url or "").strip()
    if not raw:
        return None
    if not raw.startswith(("http://", "https://")):
        raw = f"https://{raw}"

    parsed = urlparse(raw)
    host = parsed.netloc.lower()
    path_parts = [part for part in parsed.path.split("/") if part]
    if "instagram.com" not in host or len(path_parts) < 2:
        return None
    kind = path_parts[0].lower()
    if kind not in {"reel", "reels", "p"}:
        return None
    shortcode = path_parts[1].strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", shortcode):
        return None
    return ("post" if kind == "p" else "reel", shortcode)


async def create_task_in_backend(
    user_id: str,
    url: str,
    task_type: str,
    status_message: types.Message,
    source_title: str | None = None,
    reply_message_id: int | str | None = None,
    postmypost_project_id: int | None = None,
):
    """
    Helper to trigger task creation in backend and update status message.
    """
    try:
        payload = await create_task_in_backend_payload(
            user_id,
            url,
            task_type,
            chat_id=status_message.chat.id,
            status_message_id=status_message.message_id,
            source_title=source_title,
            reply_message_id=reply_message_id,
            postmypost_project_id=postmypost_project_id,
        )
        task_id = payload.get("task_id")
        queue_position = payload.get("queue_position")
        queue_total = payload.get("queue_total")
        queue_line = None
        if queue_position and queue_total:
            queue_line = f"Очередь: #{queue_position} из {queue_total}."

        lines = [
            f"⏳ Видео #{task_id}" if task_id else "⏳ Видео",
            "Этап: задача создана",
            "Видео добавлено в очередь обработки.",
        ]
        if queue_line:
            lines.append(queue_line)

        await status_message.edit_text("\n".join(lines), disable_web_page_preview=True)
    except Exception as e:
        logging.error(f"Error creating task: {e}")
        try:
            await status_message.edit_text(
                "❌ Ошибка\nЭтап: создание задачи\nНе удалось поставить видео в обработку.",
                disable_web_page_preview=True,
            )
        except Exception:
            await status_message.answer("❌ Sorry, something went wrong while creating the task.")


async def create_task_in_backend_payload(
    user_id: str,
    url: str,
    task_type: str,
    *,
    chat_id: int | str,
    status_message_id: int | str,
    source_title: str | None = None,
    reply_message_id: int | str | None = None,
    postmypost_project_id: int | None = None,
) -> dict:
    task_payload = {
        "source_url": url,
        "type": task_type,
        "source_title": (source_title or "").strip() or None,
        "telegram_chat_id": str(chat_id),
        "telegram_status_message_id": str(status_message_id),
        "telegram_reply_message_id": str(reply_message_id or ""),
    }
    if postmypost_project_id is not None:
        task_payload["postmypost_project_id"] = int(postmypost_project_id)

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            f"{BACKEND_API_URL}/tasks/{user_id}",
            json=task_payload,
        )
    response.raise_for_status()
    return response.json()


async def prompt_postmypost_project_choice(
    user_id: str,
    chat_id: int | str,
    url: str,
    task_type: str,
    intro_text: str,
    reply_message_id: int | str | None = None,
    source_title: str | None = None,
) -> None:
    await prompt_postmypost_project_choice_flow(
        bot=bot,
        backend_api_url=BACKEND_API_URL,
        create_task_in_backend=create_task_in_backend,
        strip_keyboard_styles=strip_keyboard_styles,
        user_id=user_id,
        chat_id=chat_id,
        url=url,
        task_type=task_type,
        intro_text=intro_text,
        reply_message_id=reply_message_id,
        source_title=source_title,
    )


async def send_thumbnail_prompt_review_to_backend(user_id: str, task_id: int, action: str, prompt: str | None = None) -> bool:
    try:
        payload = {"action": action}
        if prompt is not None:
            payload["prompt"] = prompt
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{BACKEND_API_URL}/tasks/{user_id}/{task_id}/thumbnail-prompt-review",
                json=payload,
            )
        response.raise_for_status()
        return True
    except Exception as e:
        logging.error("Failed to update thumbnail prompt review: %s", e)
        return False


async def fetch_task_from_backend(user_id: str, task_id: int) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(f"{BACKEND_API_URL}/tasks/{user_id}/{task_id}")
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logging.error("Failed to fetch task %s: %s", task_id, e)
        return None


def extract_thumbnail_review_prompt(task_payload: dict | None) -> str:
    if not isinstance(task_payload, dict):
        return ""
    meta = task_payload.get("script_meta") if isinstance(task_payload.get("script_meta"), dict) else {}
    review = meta.get("thumbnail_prompt_review") if isinstance(meta.get("thumbnail_prompt_review"), dict) else {}
    prompt = (
        review.get("approved_prompt")
        or review.get("prompt")
        or meta.get("thumbnail_prompt")
        or ""
    )
    return str(prompt).strip()


def build_copyable_prompt_message(task_id: int, prompt: str) -> str:
    safe_prompt = (prompt or "").strip()
    if "```" in safe_prompt:
        safe_prompt = safe_prompt.replace("```", "'''")
    return (
        f"✏️ Текущий prompt для обложки видео #{task_id}.\n"
        "Скопируйте текст ниже, измените и отправьте следующим сообщением:\n\n"
        f"```text\n{safe_prompt}\n```"
    )


def build_webapp_url_for_user(base_url: str, telegram_user_id: int) -> str:
    raw = (base_url or "").strip()
    if not raw:
        return raw
    parsed = urlparse(raw)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["tg_id"] = [str(telegram_user_id)]
    if WEBAPP_CACHE_BUST:
        query["v"] = [WEBAPP_CACHE_BUST]
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
        "2. Send me a link to a YouTube video, Instagram Reel, or TikTok.\n"
        "   Or send HeyGen video id: heygen:<video_id> | <тема ролика>.\n"
        "3. I will process it and send you the result!",
        reply_markup=kb
    )

@dp.message_handler(commands=['id'])
async def send_user_id(message: types.Message):
    await message.reply(f"Ваш Telegram ID: `{message.from_user.id}`", parse_mode="Markdown")


@dp.message_handler(lambda message: str(message.from_user.id) in PENDING_THUMBNAIL_PROMPT_EDITS)
async def handle_thumbnail_prompt_edit(message: types.Message):
    user_id = str(message.from_user.id)
    task_id = PENDING_THUMBNAIL_PROMPT_EDITS.pop(user_id, None)
    prompt = (message.text or "").strip()
    if not task_id:
        return
    if not prompt:
        await message.reply("❌ Prompt пустой. Нажмите Edit ещё раз и отправьте новый текст.")
        return
    ok = await send_thumbnail_prompt_review_to_backend(user_id, task_id, "edit", prompt=prompt)
    if ok:
        await message.reply(f"✅ Новый prompt для обложки видео #{task_id} принят. Генерирую обложку.")
    else:
        await message.reply("❌ Не удалось сохранить prompt. Попробуйте ещё раз.")


@dp.message_handler(regexp=r'^(?:heygen:)?[0-9a-fA-F]{32}(?:\s*[\|\-:—]\s*.+)?$')
async def handle_heygen_video_id(message: types.Message):
    raw_text = (message.text or "").strip()
    match = re.match(r'^(?:heygen:)?([0-9a-fA-F]{32})(.*)$', raw_text, flags=re.IGNORECASE)
    heygen_video_id = match.group(1) if match else None
    if not heygen_video_id:
        await message.reply("❌ Некорректный HeyGen video id.")
        return

    source_title = None
    tail = (match.group(2) if match else "").strip()
    if tail:
        source_title = re.sub(r'^[\|\-:—\s]+', '', tail).strip() or None

    user_id = str(message.from_user.id)
    status_message = await message.reply("⏳ Получил HeyGen ID\nЭтап: создаю задачу и определяю формат ролика.")
    await create_task_in_backend(
        user_id,
        f"heygen:{heygen_video_id}",
        "avatar_heygen",
        status_message,
        source_title=source_title,
        reply_message_id=message.message_id,
    )

@dp.message_handler(regexp=r'(https?://)?(www\.)?(youtube\.com|youtu\.be|instagram\.com|tiktok\.com|vm\.tiktok\.com|vizard\.ai)/.+')
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
    instagram_shortcode = extract_instagram_shortcode(url)

    # For long YouTube videos, ask the user for choice.
    if is_youtube and not is_shorts:
        # ... (unchanged long video logic)
        video_id = extract_youtube_video_id(url)
        kb = {
            "inline_keyboard": [
                [
                    {
                        "text": "🎬 Нарезка в VIZARD",
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
                ],
                [
                    {
                        "text": "📌 5 сек. видео",
                        "callback_data": f"info:yt:{video_id}",
                        "style": "primary"
                    }
                ]
            ]
        }
        await reply_with_keyboard(
            message,
            "📹 Это длинное видео. Что вы хотите сделать?",
            kb,
        )
        return

    if task_type == "youtube" and is_shorts:
        video_id = extract_youtube_video_id(url)
        if video_id:
            kb = {
                "inline_keyboard": [
                    [
                        {
                            "text": "👤 ИИ аватар",
                            "callback_data": f"avatar:shorts:{video_id}",
                            "style": "success",
                        }
                    ],
                    [
                        {
                            "text": "📌 5 сек. видео",
                            "callback_data": f"info:shorts:{video_id}",
                            "style": "primary",
                        }
                    ],
                    [
                        {
                            "text": "📌 Чужое видео + плашка",
                            "callback_data": f"publish:shorts:{video_id}",
                            "style": "primary",
                        }
                    ]
                ]
            }
            await reply_with_keyboard(
                message,
                "🎬 Это YouTube Shorts. Что вы хотите сделать?",
                kb,
                disable_web_page_preview=True,
            )
            return

    if task_type == "instagram" and instagram_shortcode:
        instagram_kind, instagram_shortcode_value = instagram_shortcode
        if instagram_kind == "post":
            kb = {
                "inline_keyboard": [
                    [
                        {
                            "text": "Пост в → REELS",
                            "callback_data": f"five:igp:{instagram_shortcode_value}",
                            "style": "danger",
                        }
                    ],
                    [
                        {
                            "text": "📌 5 сек. видео",
                            "callback_data": f"info:igp:{instagram_shortcode_value}",
                            "style": "primary",
                        }
                    ],
                    [
                        {
                            "text": "👤 ИИ аватар",
                            "callback_data": f"avatar:igp:{instagram_shortcode_value}",
                            "style": "success",
                        }
                    ],
                    [
                        {
                            "text": "📌 Чужое видео + плашка",
                            "callback_data": f"publish:igp:{instagram_shortcode_value}",
                            "style": "primary",
                        }
                    ]
                ]
            }
            await reply_with_keyboard(
                message,
                "🖼️ Это Instagram Post/Reels. Что вы хотите сделать?",
                kb,
                disable_web_page_preview=True,
            )
            return

        kb = {
            "inline_keyboard": [
                [
                    {
                        "text": "👤 ИИ аватар",
                        "callback_data": f"avatar:ig:{instagram_shortcode_value}",
                        "style": "success",
                    }
                ],
                [
                    {
                        "text": "📌 5 сек. видео",
                        "callback_data": f"info:ig:{instagram_shortcode_value}",
                        "style": "primary",
                    }
                ],
                [
                    {
                        "text": "📌 Чужое видео + плашка",
                        "callback_data": f"publish:ig:{instagram_shortcode_value}",
                        "style": "primary",
                    }
                ]
            ]
        }
        await reply_with_keyboard(
            message,
            "🎞️ Это Instagram Reels. Что вы хотите сделать?",
            kb,
            disable_web_page_preview=True,
        )
        return

    if task_type == "tiktok":
        choice_token = remember_source_choice(url)
        kb = {
            "inline_keyboard": [
                [{"text": "👤 ИИ аватар", "callback_data": f"avatar:tt:{choice_token}", "style": "success"}],
                [{"text": "📌 5 сек. видео", "callback_data": f"info:tt:{choice_token}", "style": "primary"}],
                [{"text": "📌 Чужое видео + плашка", "callback_data": f"publish:tt:{choice_token}", "style": "primary"}],
            ]
        }
        await reply_with_keyboard(
            message,
            "🎵 Это TikTok-видео. Что вы хотите сделать?",
            kb,
            disable_web_page_preview=True,
        )
        return

    # Automatically process Vizard project links after choosing the PostMyPost container.
    await prompt_postmypost_project_choice(
        user_id,
        message.chat.id,
        url,
        task_type,
        "⏳ Получил ссылку",
        reply_message_id=message.message_id,
    )


async def create_task_in_all_postmypost_projects(
    *,
    user_id: str,
    pending: dict,
    status_message: types.Message,
) -> None:
    projects = [
        project
        for project in (pending.get("projects") or [])
        if isinstance(project, dict) and project.get("id") is not None
    ]
    if not projects:
        await status_message.edit_text(
            "❌ Не нашёл список проектов. Отправьте ссылку ещё раз.",
            disable_web_page_preview=True,
        )
        return

    created: list[str] = []
    failed: list[str] = []
    total = len(projects)
    for index, project in enumerate(projects, start=1):
        project_id = int(project["id"])
        project_name = str(project.get("name") or f"Project {project_id}").strip()
        try:
            await status_message.edit_text(
                (
                    "⏳ Опубликовать везде\n"
                    f"Этап: создаю задачи {index}/{total}\n"
                    f"Сейчас: {project_name}"
                ),
                disable_web_page_preview=True,
            )
        except Exception:
            pass

        try:
            project_status_message = await bot.send_message(
                status_message.chat.id,
                f"⏳ {project_name}\nЭтап: задача создаётся.",
                reply_to_message_id=pending.get("reply_message_id"),
                allow_sending_without_reply=True,
            )
            payload = await create_task_in_backend_payload(
                user_id,
                pending["url"],
                pending["task_type"],
                chat_id=project_status_message.chat.id,
                status_message_id=project_status_message.message_id,
                source_title=pending.get("source_title"),
                reply_message_id=pending.get("reply_message_id"),
                postmypost_project_id=project_id,
            )
            task_id = payload.get("task_id")
            created.append(f"#{task_id} — {project_name}" if task_id else project_name)
        except Exception as exc:
            logging.error("Failed to create task for PostMyPost project %s: %s", project_id, exc)
            failed.append(project_name)

    lines = [
        "✅ Опубликовать везде",
        f"Создано задач: {len(created)}/{total}",
    ]
    if created:
        lines.append("")
        lines.extend(created[:12])
        if len(created) > 12:
            lines.append(f"Еще задач: {len(created) - 12}")
    if failed:
        lines.append("")
        lines.append(f"Ошибки: {len(failed)}")
        lines.extend(f"— {name}" for name in failed[:5])
        if len(failed) > 5:
            lines.append(f"Еще ошибок: {len(failed) - 5}")

    try:
        await status_message.edit_text("\n".join(lines), disable_web_page_preview=True)
    except Exception:
        await status_message.answer("\n".join(lines), disable_web_page_preview=True)



@dp.callback_query_handler(lambda c: c.data and c.data.startswith('pmp:'))
async def process_postmypost_project_choice(callback_query: types.CallbackQuery):
    parts = (callback_query.data or "").split(":")
    if len(parts) != 3:
        await callback_query.answer("Некорректный выбор контейнера", show_alert=True)
        return

    _, token, project_id_raw = parts
    pending = pop_pending_project_task(token, str(callback_query.from_user.id))
    if not pending:
        await callback_query.answer("Выбор устарел. Отправьте ссылку ещё раз.", show_alert=True)
        return

    publish_everywhere = project_id_raw == "all"
    if publish_everywhere:
        project_id = None
    else:
        try:
            project_id = int(project_id_raw)
        except ValueError:
            await callback_query.answer("Некорректный контейнер", show_alert=True)
            return

    await callback_query.answer("Создаю задачи..." if publish_everywhere else "Контейнер выбран. Создаю задачу...")
    status_message = callback_query.message
    status_text = (
        "⏳ Опубликовать везде\nЭтап: создаю задачи."
        if publish_everywhere
        else "⏳ Контейнер PostMyPost выбран\nЭтап: создаю задачу."
    )
    try:
        await status_message.edit_text(
            status_text,
            disable_web_page_preview=True,
        )
    except Exception:
        status_message = await bot.send_message(
            callback_query.message.chat.id,
            status_text,
            reply_to_message_id=pending.get("reply_message_id"),
            allow_sending_without_reply=True,
        )

    if publish_everywhere:
        await create_task_in_all_postmypost_projects(
            user_id=str(callback_query.from_user.id),
            pending=pending,
            status_message=status_message,
        )
        return

    await create_task_in_backend(
        str(callback_query.from_user.id),
        pending["url"],
        pending["task_type"],
        status_message,
        source_title=pending.get("source_title"),
        reply_message_id=pending.get("reply_message_id"),
        postmypost_project_id=project_id,
    )


@dp.callback_query_handler(lambda c: c.data and c.data.startswith(('vizard:', 'avatar:', 'publish:', 'five:', 'info:')))
async def process_choice(callback_query: types.CallbackQuery):
    data = callback_query.data
    parts = data.split(":")
    if len(parts) < 3:
        return

    service, platform, identifier = parts[0], parts[1], parts[2]
    original_message_id = (
        callback_query.message.reply_to_message.message_id
        if callback_query.message and callback_query.message.reply_to_message
        else None
    )

    if service == "info":
        if platform == "igp":
            url = f"https://www.instagram.com/p/{identifier}/"
        elif platform == "ig":
            url = f"https://www.instagram.com/reel/{identifier}/"
        elif platform == "shorts":
            url = f"https://www.youtube.com/shorts/{identifier}"
        elif platform == "yt":
            url = f"https://www.youtube.com/watch?v={identifier}"
        elif platform == "tt":
            url = pop_source_choice(identifier)
            if not url:
                await callback_query.answer("Выбор устарел. Отправьте ссылку ещё раз.", show_alert=True)
                return
        else:
            return
        await callback_query.answer("Выберите контейнер PostMyPost...")
        await prompt_postmypost_project_choice(
            str(callback_query.from_user.id),
            callback_query.message.chat.id,
            url,
            "infographic_reels",
            "⏳ Выбрана инфографика → REELS",
            reply_message_id=original_message_id,
        )
        try:
            await callback_query.message.delete()
        except Exception:
            pass
        return

    if service == "five":
        if platform != "igp":
            return
        url = f"https://www.instagram.com/p/{identifier}/"
        await callback_query.answer("Выберите контейнер PostMyPost...")
        await prompt_postmypost_project_choice(
            str(callback_query.from_user.id),
            callback_query.message.chat.id,
            url,
            "avatar_instagram_post_5s",
            "⏳ Выбран вариант 5 секунд",
            reply_message_id=original_message_id,
        )
        try:
            await callback_query.message.delete()
        except Exception:
            pass
        return
    
    if service == "avatar":
        if platform in {"ig", "igp"}:
            url = (
                f"https://www.instagram.com/p/{identifier}/"
                if platform == "igp"
                else f"https://www.instagram.com/reel/{identifier}/"
            )
            task_type = "avatar_instagram"
            answer_text = "👤 Запускаю Instagram Аватар..."
        elif platform == "shorts":
            url = f"https://www.youtube.com/shorts/{identifier}"
            task_type = "avatar_shorts"
            answer_text = "👤 Запускаю Shorts Аватар..."
        elif platform == "tt":
            url = pop_source_choice(identifier)
            if not url:
                await callback_query.answer("Выбор устарел. Отправьте ссылку ещё раз.", show_alert=True)
                return
            task_type = "avatar_tiktok"
            answer_text = "👤 Запускаю TikTok Аватар..."
        else:
            url = f"https://www.youtube.com/watch?v={identifier}" if platform == "yt" else identifier
            task_type = "avatar_horizontal"
            answer_text = "👤 Запускаю создание сценария с аватаром..."
        await callback_query.answer("Выберите контейнер PostMyPost...")
        await prompt_postmypost_project_choice(
            str(callback_query.from_user.id),
            callback_query.message.chat.id,
            url,
            task_type,
            "⏳ Выбран Аватар",
            reply_message_id=original_message_id,
        )
        
        try:
            await callback_query.message.delete()
        except Exception:
            pass
        return

    if service == "publish":
        if platform in {"ig", "igp"}:
            url = (
                f"https://www.instagram.com/p/{identifier}/"
                if platform == "igp"
                else f"https://www.instagram.com/reel/{identifier}/"
            )
            task_type = "instagram"
            answer_text = "📌 Запускаю чужое видео + плашка для Instagram..."
            selected_text = "⏳ Выбрано чужое видео + плашка\nЭтап: создаю задачу."
        elif platform == "shorts":
            url = f"https://www.youtube.com/shorts/{identifier}"
            task_type = "youtube"
            answer_text = "📌 Запускаю чужое видео + плашка для Shorts..."
            selected_text = "⏳ Выбрано чужое видео + плашка\nЭтап: создаю задачу."
        elif platform == "tt":
            url = pop_source_choice(identifier)
            if not url:
                await callback_query.answer("Выбор устарел. Отправьте ссылку ещё раз.", show_alert=True)
                return
            task_type = "tiktok"
            answer_text = "📌 Запускаю TikTok-видео + плашка..."
            selected_text = "⏳ Выбрано TikTok-видео + плашка\nЭтап: создаю задачу."
        else:
            return

        await callback_query.answer("Выберите контейнер PostMyPost...")
        await prompt_postmypost_project_choice(
            str(callback_query.from_user.id),
            callback_query.message.chat.id,
            url,
            task_type,
            selected_text.replace("\nЭтап: создаю задачу.", ""),
            reply_message_id=original_message_id,
        )

        try:
            await callback_query.message.delete()
        except Exception:
            pass
        return
    
    # Process Vizard choice
    url = f"https://www.youtube.com/watch?v={identifier}" if platform == "yt" else identifier
    
    await callback_query.answer("Выберите контейнер PostMyPost...")
    await prompt_postmypost_project_choice(
        str(callback_query.from_user.id),
        callback_query.message.chat.id,
        url,
        "youtube",
        "⏳ Выбран Vizard",
        reply_message_id=original_message_id,
    )
    
    # Optionally remove the selection keyboard
    try:
        await callback_query.message.delete()
    except Exception:
        pass


@dp.callback_query_handler(lambda c: c.data and c.data.startswith('thumbprompt:'))
async def process_thumbnail_prompt_review(callback_query: types.CallbackQuery):
    parts = (callback_query.data or "").split(":")
    if len(parts) != 3:
        await callback_query.answer("Некорректная команда", show_alert=True)
        return

    _, action, task_id_raw = parts
    try:
        task_id = int(task_id_raw)
    except ValueError:
        await callback_query.answer("Некорректный ID задачи", show_alert=True)
        return

    user_id = str(callback_query.from_user.id)
    if action == "edit":
        PENDING_THUMBNAIL_PROMPT_EDITS[user_id] = task_id
        ok = await send_thumbnail_prompt_review_to_backend(user_id, task_id, "edit")
        if ok:
            await remove_inline_keyboard(callback_query.message)
            task_payload = await fetch_task_from_backend(user_id, task_id)
            current_prompt = extract_thumbnail_review_prompt(task_payload)
            await callback_query.answer("Отправьте новый prompt следующим сообщением")
            if current_prompt:
                await bot.send_message(
                    callback_query.message.chat.id,
                    build_copyable_prompt_message(task_id, current_prompt),
                    parse_mode="Markdown",
                    disable_web_page_preview=True,
                )
            else:
                await bot.send_message(
                    callback_query.message.chat.id,
                    f"✏️ Отправьте новый prompt для обложки видео #{task_id} одним сообщением."
                )
        else:
            await callback_query.answer("Не удалось включить режим редактирования", show_alert=True)
        return

    if action not in {"approve", "reject"}:
        await callback_query.answer("Некорректное действие", show_alert=True)
        return

    ok = await send_thumbnail_prompt_review_to_backend(user_id, task_id, action)
    if not ok:
        await callback_query.answer("Не удалось отправить решение", show_alert=True)
        return

    await remove_inline_keyboard(callback_query.message)
    if action == "approve":
        await callback_query.answer("Prompt approved")
        await bot.send_message(callback_query.message.chat.id, f"✅ Prompt обложки видео #{task_id} подтвержден.")
    else:
            await callback_query.answer("Prompt rejected")
            await bot.send_message(callback_query.message.chat.id, f"🚫 Обложка для видео #{task_id} отклонена и будет пропущена.")


if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
