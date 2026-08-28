import logging
import os
from collections.abc import Iterable

import httpx

from ..api.utils import _parse_csv_env, get_telegram_admin_ids
from ..utils.telegram_formatting import escape_markdown_v2, markdown_v2_code_block


logger = logging.getLogger(__name__)


def resolve_telegram_chat_id(value: str | None) -> str:
    chat_id = (value or "").strip()
    if chat_id.isdigit():
        return chat_id
    configured = get_telegram_admin_ids()
    primary = (os.getenv("TELEGRAM_PRIMARY_ADMIN_ID") or "").strip()
    if primary.isdigit() and primary in configured:
        return primary
    ordered = [item for item in _parse_csv_env(os.getenv("TELEGRAM_ADMIN_IDS")) if item.isdigit()]
    return ordered[0] if ordered else ""


def send_carousel_text_review_to_telegram(draft) -> bool:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = resolve_telegram_chat_id(getattr(draft, "telegram_chat_id", None))
    text = (getattr(draft, "master_text", None) or "").strip()
    if not token or not chat_id or not text:
        return False
    keyboard = {"inline_keyboard": [[
        {"text": "✅ Одобрить", "callback_data": f"carouseltext:approve:{draft.id}"},
        {"text": "✏️ Изменить", "callback_data": f"carouseltext:edit:{draft.id}"},
        {"text": "🚫 Отклонить", "callback_data": f"carouseltext:reject:{draft.id}"},
    ]]}
    message = (
        f"{escape_markdown_v2(f'🖼 Текст карусели #{draft.id}')}\n\n"
        f"{markdown_v2_code_block(text)}\n\n"
        f"{escape_markdown_v2('Это единый текст для всех платформ. После одобрения CTA добавится автоматически на финальном слайде каждой сети.')}"
    )
    try:
        with httpx.Client(timeout=httpx.Timeout(20.0, connect=5.0)) as client:
            response = client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": message, "parse_mode": "MarkdownV2", "reply_markup": keyboard},
            )
        return response.status_code < 400 and bool(response.json().get("ok"))
    except Exception as exc:
        logger.warning("Failed to send carousel review: %s", exc)
        return False


def send_carousel_ready_to_telegram(draft) -> bool:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = resolve_telegram_chat_id(getattr(draft, "telegram_chat_id", None))
    slides = getattr(draft, "slides", None) or {}
    story_slides = getattr(draft, "story_slides", None) or {}
    if not token or not chat_id or (not slides and not story_slides):
        return False
    ok = True
    for label, package in (("Карусель", slides), ("Stories", story_slides)):
        sent_paths: set[str] = set()
        for platform, paths in package.items():
            for index, path in enumerate(paths or [], start=1):
                if path in sent_paths:
                    continue
                sent_paths.add(path)
                suffix = "общий слайд" if "-shared-" in os.path.basename(path) else f"{platform}, CTA"
                sent, _ = _send_telegram_photo(
                    token, chat_id, path, f"{label} #{draft.id}: {suffix}, слайд {index}"
                )
                ok = sent and ok
    return ok


def send_carousel_scheduled_to_telegram(draft, publications: Iterable) -> bool:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = resolve_telegram_chat_id(getattr(draft, "telegram_chat_id", None))
    rows = list(publications or [])
    if not token or not chat_id or not rows:
        return False

    labels = {"instagram": "Instagram", "tiktok": "TikTok", "vk": "ВКонтакте", "telegram": "Telegram"}
    lines = [f"🗓 Запланированы публикации карусели #{getattr(draft, 'id', '')}", ""]
    for media_format in ("carousel", "story"):
        matching = [row for row in rows if getattr(row, "media_format", "") == media_format]
        if not matching:
            continue
        title = "Карусель" if media_format == "carousel" else "Stories"
        lines.append(f"{title}:")
        for row in matching:
            platform = labels.get(str(getattr(row, "platform", "")).lower(), getattr(row, "platform", ""))
            post_at = getattr(row, "post_at", None)
            date_text = post_at.strftime("%d.%m.%Y %H:%M UTC") if post_at else "время не указано"
            lines.append(f"• {platform}, аккаунт {row.account_id} — {date_text}")
        lines.append("")

    message = "\n".join(lines).strip()
    try:
        with httpx.Client(timeout=httpx.Timeout(20.0, connect=5.0)) as client:
            response = client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": message},
            )
        payload = response.json()
        return response.status_code < 400 and bool(payload.get("ok"))
    except Exception as exc:
        logger.warning("Failed to send carousel scheduling confirmation: %s", exc)
        return False


def _send_telegram_photo(token: str, chat_id: str, file_path: str, caption: str) -> tuple[bool, str]:
    try:
        with httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
            with open(file_path, "rb") as photo:
                response = client.post(
                    f"https://api.telegram.org/bot{token}/sendPhoto",
                    data={"chat_id": chat_id, "caption": caption},
                    files={"photo": (os.path.basename(file_path), photo, "image/png")},
                )
        payload = response.json()
        if response.status_code >= 400 or not payload.get("ok", False):
            description = payload.get("description") if isinstance(payload, dict) else response.text[:300]
            logger.warning("Failed to send Telegram photo: status=%s description=%s", response.status_code, description)
            return False, f"{response.status_code} {description}"
        return True, ""
    except Exception as exc:
        logger.warning("Failed to send Telegram photo: %s", exc)
        return False, str(exc)
