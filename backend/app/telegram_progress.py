import logging
import os

import httpx


logger = logging.getLogger(__name__)


def build_status_message(task_id: int, stage: str, detail: str | None = None, ok: bool = False, failed: bool = False) -> str:
    if failed:
        icon = "❌"
    elif ok:
        icon = "✅"
    else:
        icon = "⏳"

    lines = [
        f"{icon} Видео #{task_id}",
        f"Этап: {stage}",
    ]
    if detail:
        lines.append(detail.strip())
    return "\n".join(lines)


def update_task_status_message(db, task, stage: str, detail: str | None = None, *, ok: bool = False, failed: bool = False) -> None:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (getattr(task, "telegram_chat_id", None) or "").strip()
    message_id = (getattr(task, "telegram_status_message_id", None) or "").strip()
    if not token or not chat_id or not message_id:
        return

    text = build_status_message(task.id, stage=stage, detail=detail, ok=ok, failed=failed)
    if getattr(task, "telegram_status_text", None) == text:
        return

    try:
        with httpx.Client(timeout=httpx.Timeout(10.0, connect=4.0)) as client:
            response = client.post(
                f"https://api.telegram.org/bot{token}/editMessageText",
                json={
                    "chat_id": chat_id,
                    "message_id": int(message_id),
                    "text": text,
                    "disable_web_page_preview": True,
                },
            )
        payload = response.json()
        if response.status_code >= 400 or not payload.get("ok", False):
            description = payload.get("description") if isinstance(payload, dict) else response.text[:300]
            if "message is not modified" in str(description).lower():
                task.telegram_status_text = text
                db.commit()
                return
            logger.warning(
                "Failed to edit Telegram status message for task %s: status=%s description=%s",
                task.id,
                response.status_code,
                description,
            )
            return
        task.telegram_status_text = text
        db.commit()
    except Exception as exc:
        logger.warning("Failed to update Telegram status message for task %s: %s", task.id, exc)
