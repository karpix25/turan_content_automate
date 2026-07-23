import json
import logging
import time
import uuid
from typing import Awaitable, Callable

import httpx


PendingTask = dict[str, object]
CreateTaskFn = Callable[..., Awaitable[None]]

_PENDING_PROJECT_TASKS: dict[str, PendingTask] = {}


def prune_pending_project_tasks(max_age_seconds: int = 1800) -> None:
    now = time.time()
    expired_tokens = [
        token
        for token, payload in _PENDING_PROJECT_TASKS.items()
        if now - float(payload.get("created_at", 0)) > max_age_seconds
    ]
    for token in expired_tokens:
        _PENDING_PROJECT_TASKS.pop(token, None)


def pop_pending_project_task(token: str, user_id: str) -> PendingTask | None:
    pending = _PENDING_PROJECT_TASKS.pop(token, None)
    if not pending or str(pending.get("user_id")) != str(user_id):
        return None
    return pending


def build_project_choice_keyboard(projects: list[dict], token: str, selected_project_id: int | None) -> dict:
    rows = []
    for project in projects[:20]:
        project_id = project.get("id")
        if project_id is None:
            continue
        name = str(project.get("name") or f"Project {project_id}").strip()
        prefix = "✅ " if selected_project_id is not None and int(project_id) == int(selected_project_id) else ""
        rows.append([
            {
                "text": f"{prefix}{name[:44]}",
                "callback_data": f"pmp:{token}:{int(project_id)}",
                "style": "primary",
            }
        ])
    return {"inline_keyboard": rows}


async def prompt_postmypost_project_choice(
    *,
    bot,
    backend_api_url: str,
    create_task_in_backend: CreateTaskFn,
    strip_keyboard_styles: Callable[[dict], dict],
    user_id: str,
    chat_id: int | str,
    url: str,
    task_type: str,
    intro_text: str,
    reply_message_id: int | str | None = None,
    source_title: str | None = None,
) -> None:
    prune_pending_project_tasks()
    token = uuid.uuid4().hex[:10]
    _PENDING_PROJECT_TASKS[token] = {
        "user_id": user_id,
        "url": url,
        "task_type": task_type,
        "source_title": source_title,
        "reply_message_id": reply_message_id,
        "created_at": time.time(),
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(f"{backend_api_url}/postmypost/projects/{user_id}")
        response.raise_for_status()
        payload = response.json()
        projects = payload.get("projects") or []
        selected_project_id = payload.get("selected_project_id")
    except Exception as exc:
        logging.error("Failed to load PostMyPost projects for Telegram choice: %s", exc)
        status_message = await bot.send_message(
            chat_id,
            f"{intro_text}\nЭтап: создаю задачу с текущим контейнером.",
            reply_to_message_id=reply_message_id,
            allow_sending_without_reply=True,
        )
        _PENDING_PROJECT_TASKS.pop(token, None)
        await create_task_in_backend(
            user_id,
            url,
            task_type,
            status_message,
            source_title=source_title,
            reply_message_id=reply_message_id,
        )
        return

    if not projects:
        await bot.send_message(
            chat_id,
            "❌ В PostMyPost нет доступных контейнеров. Проверьте подключение проекта в Mini App.",
            reply_to_message_id=reply_message_id,
            allow_sending_without_reply=True,
        )
        _PENDING_PROJECT_TASKS.pop(token, None)
        return

    keyboard = build_project_choice_keyboard(projects, token, selected_project_id)
    text = f"{intro_text}\nЭтап: выберите контейнер PostMyPost."
    try:
        await bot.send_message(
            chat_id,
            text,
            reply_markup=json.dumps(keyboard),
            reply_to_message_id=reply_message_id,
            allow_sending_without_reply=True,
        )
    except Exception:
        logging.exception("Failed to send PostMyPost project keyboard, retrying without styles")
        await bot.send_message(
            chat_id,
            text,
            reply_markup=json.dumps(strip_keyboard_styles(keyboard)),
            reply_to_message_id=reply_message_id,
            allow_sending_without_reply=True,
        )
