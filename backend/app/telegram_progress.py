import logging
import os
import re

import httpx


logger = logging.getLogger(__name__)
MAX_TELEGRAM_TEXT_LEN = 3900


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


def _split_message_chunks(text: str, max_len: int = MAX_TELEGRAM_TEXT_LEN) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    if len(raw) <= max_len:
        return [raw]

    parts: list[str] = []
    remaining = raw
    while remaining:
        if len(remaining) <= max_len:
            parts.append(remaining)
            break

        split_at = remaining.rfind("\n\n", 0, max_len + 1)
        if split_at < max_len // 2:
            split_at = remaining.rfind("\n", 0, max_len + 1)
        if split_at < max_len // 2:
            split_at = remaining.rfind(" ", 0, max_len + 1)
        if split_at < max_len // 2:
            split_at = max_len

        chunk = remaining[:split_at].strip()
        if chunk:
            parts.append(chunk)
        remaining = remaining[split_at:].lstrip()
    return parts


def _send_telegram_message(token: str, chat_id: str, text: str) -> bool:
    try:
        with httpx.Client(timeout=httpx.Timeout(20.0, connect=5.0)) as client:
            response = client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "disable_web_page_preview": True,
                },
            )
        payload = response.json()
        if response.status_code >= 400 or not payload.get("ok", False):
            description = payload.get("description") if isinstance(payload, dict) else response.text[:300]
            logger.warning(
                "Failed to send Telegram message: status=%s description=%s",
                response.status_code,
                description,
            )
            return False
        return True
    except Exception as exc:
        logger.warning("Failed to send Telegram message: %s", exc)
        return False


def send_avatar_script_to_telegram(task, script_text: str, estimated_minutes: float | None = None) -> None:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (getattr(task, "telegram_chat_id", None) or "").strip()
    if not token or not chat_id:
        return

    script = re.sub(r"\r\n?", "\n", (script_text or "").strip())
    if not script:
        return

    duration_line = ""
    if isinstance(estimated_minutes, (int, float)) and estimated_minutes > 0:
        duration_line = f"\nОценка длительности: ~{estimated_minutes:.1f} мин."

    intro = (
        f"✅ Сценарий для ИИ-аватара готов."
        f"{duration_line}\n"
        f"Видео #{getattr(task, 'id', '-')}\n\n"
        f"Ниже готовый текст:"
    )
    _send_telegram_message(token, chat_id, intro)

    chunks = _split_message_chunks(script)
    total = len(chunks)
    for idx, chunk in enumerate(chunks, start=1):
        prefix = f"Часть {idx}/{total}\n\n" if total > 1 else ""
        _send_telegram_message(token, chat_id, f"{prefix}{chunk}")
