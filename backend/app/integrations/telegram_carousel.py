import json
import logging
import os
from collections.abc import Iterable

import httpx

from ..api.utils import _parse_csv_env, get_telegram_admin_ids
from ..services.carousel_blocks import deck_to_text
from ..services.carousel_copy import template_package_text
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
    platform_texts = getattr(draft, "platform_texts", None)
    for label, package in (("Карусель", slides), ("Stories", story_slides)):
        media_format = "carousel" if label == "Карусель" else "story"
        content = _ready_publication_content(platform_texts, media_format)
        sent_paths: set[str] = set()
        paths = []
        for platform_paths in package.values():
            for path in platform_paths or []:
                if path not in sent_paths:
                    sent_paths.add(path)
                    paths.append(path)
        for chunk_start in range(0, len(paths), 10):
            group_caption = f"{label} #{draft.id}"
            if chunk_start == 0 and content:
                group_caption = f"{group_caption}\n\n{content}"
                if len(group_caption) > 1024:
                    # Telegram limits photo captions to 1024 characters. Keep
                    # the full publication copy intact in a companion message.
                    sent_text = _send_telegram_text(token, chat_id, content)
                    ok = sent_text and ok
                    group_caption = f"{label} #{draft.id}"
            sent, _ = _send_telegram_media_group(
                token,
                chat_id,
                paths[chunk_start:chunk_start + 10],
                group_caption,
            )
            ok = sent and ok
    return ok


def _ready_publication_content(platform_texts, media_format: str) -> str:
    if not isinstance(platform_texts, dict):
        return ""
    # Prefer Telegram's rendered copy, then another platform's same-format
    # package when Telegram itself is not a publication target.
    variants = []
    telegram_variant = platform_texts.get("telegram")
    if isinstance(telegram_variant, dict):
        variants.append(telegram_variant)
    variants.extend(
        value for key, value in platform_texts.items()
        if key != "telegram" and isinstance(value, dict)
    )
    for variant in variants:
        package = variant.get(media_format)
        if isinstance(package, dict) and "slides" in package:
            if text := deck_to_text(package):
                return text
        if isinstance(package, dict):
            if text := template_package_text(package):
                return text
    return ""


def _send_telegram_text(token: str, chat_id: str, text: str) -> bool:
    # Telegram's sendMessage limit is 4096 characters. Split on paragraph
    # boundaries where possible so long captions are still delivered intact.
    chunks = []
    remaining = text.strip()
    while len(remaining) > 4096:
        split_at = remaining.rfind("\n\n", 0, 4096)
        if split_at < 1:
            split_at = remaining.rfind("\n", 0, 4096)
        if split_at < 1:
            split_at = 4096
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    ok = True
    try:
        with httpx.Client(timeout=httpx.Timeout(20.0, connect=5.0)) as client:
            for chunk in chunks:
                response = client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": chunk},
                )
                ok = response.status_code < 400 and bool(response.json().get("ok")) and ok
        return ok
    except Exception as exc:
        logger.warning("Failed to send carousel publication text: %s", exc)
        return False


def send_carousel_generation_failed_to_telegram(draft, error: str) -> bool:
    """Tell the reviewer when an approved carousel could not be generated."""
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = resolve_telegram_chat_id(getattr(draft, "telegram_chat_id", None))
    if not token or not chat_id:
        return False
    detail = " ".join(str(error or "").split())[:700]
    keyboard = {"inline_keyboard": [[
        {"text": "🔁 Повторить генерацию", "callback_data": f"carouseltext:retry:{draft.id}"},
    ]]}
    message = f"❌ Не удалось собрать слайды для карусели #{draft.id}.\nПричина: {detail}"
    try:
        with httpx.Client(timeout=httpx.Timeout(20.0, connect=5.0)) as client:
            response = client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": message, "reply_markup": keyboard},
            )
        return response.status_code < 400 and bool(response.json().get("ok"))
    except Exception as exc:
        logger.warning("Failed to send carousel generation failure for draft %s: %s", draft.id, exc)
        return False


def send_carousel_openrouter_funding_to_telegram(draft, next_retry_seconds: int) -> bool:
    """Explain a depleted OpenRouter balance and the automatic recovery plan."""
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = resolve_telegram_chat_id(getattr(draft, "telegram_chat_id", None))
    if not token or not chat_id:
        return False
    minutes = max(1, round(next_retry_seconds / 60))
    message = (
        f"💳 Для карусели #{draft.id} OpenRouter отклонил запрос: недостаточно средств на балансе.\n"
        "Пополните баланс OpenRouter или проверьте лимит API-ключа — я автоматически повторю генерацию, "
        f"первый раз примерно через {minutes} мин., затем с увеличивающимися паузами. "
        "Если баланс не восстановится в течение суток, черновик будет помечен как ошибка "
        "и появится обычная кнопка повтора."
    )
    try:
        with httpx.Client(timeout=httpx.Timeout(20.0, connect=5.0)) as client:
            response = client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": message},
            )
        return response.status_code < 400 and bool(response.json().get("ok"))
    except Exception as exc:
        logger.warning("Failed to send OpenRouter funding notice for draft %s: %s", draft.id, exc)
        return False


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


def _send_telegram_media_group(
    token: str, chat_id: str, file_paths: list[str], caption: str
) -> tuple[bool, str]:
    if not file_paths:
        return True, ""
    try:
        media = []
        files = {}
        handles = []
        for index, file_path in enumerate(file_paths):
            field_name = f"file{index}"
            handle = open(file_path, "rb")
            handles.append(handle)
            files[field_name] = (os.path.basename(file_path), handle, "image/png")
            item = {"type": "photo", "media": f"attach://{field_name}"}
            if index == 0:
                item["caption"] = caption
            media.append(item)
        try:
            with httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
                response = client.post(
                    f"https://api.telegram.org/bot{token}/sendMediaGroup",
                    data={"chat_id": chat_id, "media": json.dumps(media, ensure_ascii=False)},
                    files=files,
                )
        finally:
            for handle in handles:
                handle.close()
        payload = response.json()
        if response.status_code >= 400 or not payload.get("ok", False):
            description = payload.get("description") if isinstance(payload, dict) else response.text[:300]
            logger.warning("Failed to send Telegram media group: status=%s description=%s", response.status_code, description)
            return False, f"{response.status_code} {description}"
        return True, ""
    except Exception as exc:
        logger.warning("Failed to send Telegram media group: %s", exc)
        return False, str(exc)
