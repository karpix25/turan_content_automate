import logging
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone

import httpx

from .utils.task_format_labels import get_task_format_label
from .utils.publication_errors import get_publication_error


logger = logging.getLogger(__name__)
MAX_TELEGRAM_TEXT_LEN = 3900
TELEGRAM_UPLOAD_MAX_BYTES = 49 * 1024 * 1024


def build_status_message(task, stage: str, detail: str | None = None, ok: bool = False, failed: bool = False) -> str:
    if failed:
        icon = "❌"
    elif ok:
        icon = "✅"
    else:
        icon = "⏳"

    format_label = get_task_format_label(task)
    lines = [
        f"{icon} {format_label}",
        f"Этап: {stage}",
    ]
    if detail:
        lines.append(detail.strip())
    return "\n".join(lines)


def _short_text(value: str | None, limit: int = 120) -> str:
    text = re.sub(r"\s+", " ", (value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def build_task_context_lines(task) -> list[str]:
    task_id = getattr(task, "id", "-")
    task_type = (getattr(task, "type", None) or "").strip()
    platform = (getattr(task, "target_platform", None) or "").strip()
    account_id = getattr(task, "target_account_id", None)
    source_title = _short_text(getattr(task, "source_title", None), 100)
    source_url = _short_text(getattr(task, "source_url", None), 100)

    lines = [f"Видео #{task_id}"]
    if task_type:
        lines.append(f"Тип: {task_type}")
    destination_parts = []
    if platform:
        destination_parts.append(platform)
    if account_id:
        destination_parts.append(f"аккаунт {account_id}")
    if destination_parts:
        lines.append("Куда: " + ", ".join(destination_parts))
    if source_title:
        lines.append(f"Title: {source_title}")
    elif source_url:
        lines.append(f"Источник: {source_url}")
    return lines


def build_task_context_text(task) -> str:
    return "\n".join(build_task_context_lines(task))


def update_task_status_message(db, task, stage: str, detail: str | None = None, *, ok: bool = False, failed: bool = False) -> None:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (getattr(task, "telegram_chat_id", None) or "").strip()
    message_id = (getattr(task, "telegram_status_message_id", None) or "").strip()
    if not token or not chat_id or not message_id:
        return

    text = build_status_message(task, stage=stage, detail=detail, ok=ok, failed=failed)
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
        try:
            db.rollback()
        except Exception:
            pass
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


def _reply_message_id(task) -> str | None:
    value = (getattr(task, "telegram_reply_message_id", None) or "").strip()
    return value or None


def _send_telegram_message(token: str, chat_id: str, text: str, reply_to_message_id: str | None = None) -> bool:
    try:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if reply_to_message_id:
            payload["reply_to_message_id"] = int(reply_to_message_id)
            payload["allow_sending_without_reply"] = True
        with httpx.Client(timeout=httpx.Timeout(20.0, connect=5.0)) as client:
            response = client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json=payload,
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


def _format_publish_time(value) -> str | None:
    if not value:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value = value.astimezone(timezone.utc)
        return value.strftime("%d.%m %H:%M UTC")
    text = str(value).strip()
    return text or None


def _format_publish_date(value) -> str | None:
    if not value:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value = value.astimezone(timezone.utc)
        return value.strftime("%d.%m.%Y")
    text = str(value).strip()
    return text[:10] if text else None


def _extract_clip_key(task) -> str:
    source_url = getattr(task, "source_url", None) or ""
    match = re.search(r"\[clip\s+(\d+)\]", source_url)
    if match:
        return f"clip:{match.group(1)}"
    base_source = re.sub(r"\s+\[(slot|account|variant)\s+[^\]]+\]", "", source_url).strip()
    if base_source:
        return f"source:{base_source}"
    return f"task:{getattr(task, 'id', '-')}"


def _date_sort_key(value: str):
    try:
        return datetime.strptime(value, "%d.%m.%Y")
    except ValueError:
        return datetime.max


def _publication_task_done(task) -> bool:
    publishing_status = (getattr(task, "publishing_status", None) or "").strip()
    if publishing_status in {"scheduled", "in_progress", "published", "failed"}:
        return True
    return bool(getattr(task, "postmypost_id", None))


def send_publication_batch_report_message(tasks: list, batch_meta: dict | None = None) -> bool:
    batch_meta = dict(batch_meta or {})
    first_task = next((item for item in tasks if getattr(item, "telegram_chat_id", None)), None)
    if not first_task:
        return False

    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (getattr(first_task, "telegram_chat_id", None) or "").strip()
    if not token or not chat_id:
        return False

    expected_clips = int(batch_meta.get("expected_clips") or 0)
    expected_publications = int(batch_meta.get("expected_publications") or 0)
    source_label = _short_text(batch_meta.get("source_label") or getattr(first_task, "source_url", None), 120)

    done_tasks = [task for task in tasks if _publication_task_done(task)]
    failed_tasks = [
        task for task in done_tasks
        if (getattr(task, "publishing_status", None) or "").strip() == "failed"
    ]
    scheduled_tasks = [
        task for task in done_tasks
        if (getattr(task, "publishing_status", None) or "").strip() in {"scheduled", "in_progress", "published"}
    ]

    clip_keys = {_extract_clip_key(task) for task in done_tasks}
    account_ids = {
        getattr(task, "target_account_id", None)
        for task in done_tasks
        if getattr(task, "target_account_id", None)
    }

    by_date: dict[str, dict[str, set | int]] = {}
    for task in scheduled_tasks:
        date_label = _format_publish_date(getattr(task, "publish_at", None)) or "Без даты"
        bucket = by_date.setdefault(date_label, {"clips": set(), "publications": 0})
        bucket["clips"].add(_extract_clip_key(task))
        bucket["publications"] = int(bucket["publications"]) + 1

    lines = ["Все, Turan 🫶🏻"]
    if failed_tasks:
        lines.append("Задача частично выполнена.")
    else:
        lines.append("Задача выполнена.")
    lines.append("")
    if source_label:
        lines.append(f"Источник: {source_label}")
    clips_count = expected_clips or len(clip_keys)
    lines.append(f"Видео: {len(clip_keys)}/{clips_count}")
    publications_count = len(scheduled_tasks)
    total_publications = expected_publications or len(done_tasks)
    lines.append(f"Запланировано в PostMyPost: {publications_count}/{total_publications}")
    if account_ids:
        lines.append(f"Аккаунтов/платформ: {len(account_ids)}")

    if by_date:
        lines.append("")
        lines.append("План:")
        for date_label in sorted(by_date, key=_date_sort_key):
            bucket = by_date[date_label]
            lines.append(
                f"{date_label}: {len(bucket['clips'])} видео, {int(bucket['publications'])} публикаций"
            )

    lines.append("")
    if failed_tasks:
        lines.append(f"Ошибки: {len(failed_tasks)} публикаций")
        for task in failed_tasks[:5]:
            error_text = get_publication_error(task) or "публикация не синхронизировалась"
            lines.append(f"#{getattr(task, 'id', '-')}: {error_text}")
        if len(failed_tasks) > 5:
            lines.append(f"Еще ошибок: {len(failed_tasks) - 5}")
    else:
        lines.append("Ошибки: нет")

    return _send_telegram_message(
        token,
        chat_id,
        "\n".join(lines),
        reply_to_message_id=_reply_message_id(first_task),
    )


def send_postmypost_ready_message(task, *, publication_id: str | None, post_at=None, status: str | None = None) -> bool:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (getattr(task, "telegram_chat_id", None) or "").strip()
    if not token or not chat_id:
        return False

    status_value = (status or getattr(task, "publishing_status", "") or "").strip()
    is_scheduled = status_value == "scheduled"
    stage = "Запланировано" if is_scheduled else "Готово к публикации"

    context_lines = build_task_context_lines(task)
    lines = [
        f"✅ {context_lines[0]}",
        f"PostMyPost: {stage}",
    ]

    if publication_id:
        lines.append(f"ID публикации: {publication_id}")

    lines.extend(context_lines[1:])

    time_label = _format_publish_time(post_at or getattr(task, "publish_at", None))
    if time_label:
        if is_scheduled:
            lines.append(f"Время публикации: {time_label}")
        else:
            lines.append(f"Передано: {time_label}")

    return _send_telegram_message(token, chat_id, "\n".join(lines), reply_to_message_id=_reply_message_id(task))


def send_thumbnail_prompt_review_to_telegram(task, prompt: str) -> bool:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (getattr(task, "telegram_chat_id", None) or "").strip()
    if not token or not chat_id or not prompt:
        return False

    context = build_task_context_text(task)
    chunks = _split_message_chunks(
        f"🖼 Prompt обложки\n{context}\n\n{prompt}",
        max_len=MAX_TELEGRAM_TEXT_LEN,
    )
    ok = True
    for chunk in chunks:
        ok = _send_telegram_message(token, chat_id, chunk, reply_to_message_id=_reply_message_id(task)) and ok

    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Approve", "callback_data": f"thumbprompt:approve:{getattr(task, 'id', '-')}"}
            ],
            [
                {"text": "✏️ Edit", "callback_data": f"thumbprompt:edit:{getattr(task, 'id', '-')}"},
                {"text": "🚫 Reject", "callback_data": f"thumbprompt:reject:{getattr(task, 'id', '-')}"},
            ],
        ]
    }
    try:
        with httpx.Client(timeout=httpx.Timeout(20.0, connect=5.0)) as client:
            payload = {
                "chat_id": chat_id,
                "text": (
                    "Проверь prompt обложки.\n"
                    f"{context}\n\n"
                    "Можно подтвердить, отклонить или нажать Edit и отправить новый prompt следующим сообщением."
                ),
                "reply_markup": keyboard,
                "disable_web_page_preview": True,
            }
            if _reply_message_id(task):
                payload["reply_to_message_id"] = int(_reply_message_id(task))
                payload["allow_sending_without_reply"] = True
            response = client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json=payload,
            )
        payload = response.json()
        if response.status_code >= 400 or not payload.get("ok", False):
            description = payload.get("description") if isinstance(payload, dict) else response.text[:300]
            logger.warning(
                "Failed to send Telegram thumbnail prompt review keyboard: status=%s description=%s",
                response.status_code,
                description,
            )
            return False
        return ok
    except Exception as exc:
        logger.warning("Failed to send Telegram thumbnail prompt review keyboard: %s", exc)
        return False


def _send_telegram_document(
    token: str,
    chat_id: str,
    file_path: str,
    caption: str,
    reply_to_message_id: str | None = None,
) -> tuple[bool, str]:
    try:
        data = {"chat_id": chat_id, "caption": caption}
        if reply_to_message_id:
            data["reply_to_message_id"] = str(reply_to_message_id)
            data["allow_sending_without_reply"] = "true"
        with httpx.Client(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
            with open(file_path, "rb") as f:
                response = client.post(
                    f"https://api.telegram.org/bot{token}/sendDocument",
                    data=data,
                    files={"document": (os.path.basename(file_path), f, "video/mp4")},
                )
        payload = response.json()
        if response.status_code >= 400 or not payload.get("ok", False):
            description = payload.get("description") if isinstance(payload, dict) else response.text[:300]
            logger.warning(
                "Failed to send Telegram document: status=%s description=%s",
                response.status_code,
                description,
            )
            return False, f"{response.status_code} {description}"
        return True, ""
    except Exception as exc:
        logger.warning("Failed to send Telegram document: %s", exc)
        return False, str(exc)


def _probe_duration_seconds(file_path: str) -> float | None:
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            file_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        value = float((result.stdout or "").strip())
        if value > 0:
            return value
    except Exception as exc:
        logger.warning("Failed to probe video duration for Telegram fallback: %s", exc)
    return None


def _build_transcoded_copy_for_telegram(src_path: str, max_bytes: int = TELEGRAM_UPLOAD_MAX_BYTES) -> str | None:
    duration = _probe_duration_seconds(src_path)
    if not duration:
        duration = 90.0

    audio_bitrate = 96_000
    target_total_bitrate = int((max_bytes * 8 * 0.93) / max(duration, 1.0))
    video_bitrate = max(320_000, target_total_bitrate - audio_bitrate)

    tmp = tempfile.NamedTemporaryFile(prefix="tg_fit_", suffix=".mp4", delete=False)
    tmp_path = tmp.name
    tmp.close()

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        src_path,
        "-vf",
        "scale='min(1280,iw)':-2",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-b:v",
        str(video_bitrate),
        "-maxrate",
        str(video_bitrate),
        "-bufsize",
        str(video_bitrate * 2),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        "-ac",
        "2",
        tmp_path,
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        if os.path.isfile(tmp_path) and os.path.getsize(tmp_path) <= max_bytes:
            return tmp_path

        # Fallback: more aggressive pass for very long ролики.
        cmd_fallback = [
            "ffmpeg",
            "-y",
            "-i",
            src_path,
            "-vf",
            "scale='min(960,iw)':-2",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "33",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            "-ac",
            "1",
            tmp_path,
        ]
        subprocess.run(cmd_fallback, check=True, capture_output=True, text=True)
        if os.path.isfile(tmp_path) and os.path.getsize(tmp_path) <= max_bytes:
            return tmp_path
    except Exception as exc:
        logger.warning("Failed to build Telegram-compatible copy: %s", exc)
    return None


def send_avatar_audio_to_telegram(task, audio_path: str, estimated_minutes: float | None = None) -> None:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (getattr(task, "telegram_chat_id", None) or "").strip()
    if not token or not chat_id:
        return

    if not audio_path or not os.path.exists(audio_path):
        logger.error(f"Audio path {audio_path} does not exist.")
        return

    duration_line = ""
    if isinstance(estimated_minutes, (int, float)) and estimated_minutes > 0:
        duration_line = f"\nОценка длительности: ~{estimated_minutes:.1f} мин."

    caption = (
        f"✅ Аудио для ИИ-аватара готово."
        f"{duration_line}\n"
        f"{build_task_context_text(task)}"
    )
    
    try:
        data = {"chat_id": chat_id, "caption": caption}
        if _reply_message_id(task):
            data["reply_to_message_id"] = _reply_message_id(task)
            data["allow_sending_without_reply"] = "true"
        with httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
            with open(audio_path, "rb") as f:
                response = client.post(
                    f"https://api.telegram.org/bot{token}/sendAudio",
                    data=data,
                    files={"audio": f}
                )
            payload = response.json()
            if response.status_code >= 400 or not payload.get("ok", False):
                description = payload.get("description") if isinstance(payload, dict) else response.text[:300]
                logger.warning(
                    "Failed to send Telegram audio: status=%s description=%s",
                    response.status_code,
                    description,
                )
    except Exception as exc:
        logger.warning(f"Failed to send Telegram audio: {exc}")

def send_avatar_video_to_telegram(task, video_path: str, caption: str | None = None) -> None:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (getattr(task, "telegram_chat_id", None) or "").strip()
    if not token or not chat_id:
        return

    if not video_path or not os.path.exists(video_path):
        logger.error(f"Video path {video_path} does not exist.")
        return

    if not caption:
        caption = f"✅ Файл с видео готов.\n{build_task_context_text(task)}"
    
    ok, error_text = _send_telegram_document(token, chat_id, video_path, caption, reply_to_message_id=_reply_message_id(task))
    if ok:
        return

    is_too_large = "413" in error_text or "too large" in error_text.lower()
    if not is_too_large:
        return

    file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
    logger.info(
        "Telegram rejected file as too large (%.1f MB). Trying compressed fallback copy.",
        file_size_mb,
    )
    fitted_path = _build_transcoded_copy_for_telegram(video_path)
    if not fitted_path:
        _send_telegram_message(
            token,
            chat_id,
            f"⚠️ Видео #{getattr(task, 'id', '-')}: файл слишком большой для Telegram Bot API ({file_size_mb:.1f} MB) и не удалось автоматически сжать его для отправки.",
            reply_to_message_id=_reply_message_id(task),
        )
        return

    try:
        ok_retry, error_retry = _send_telegram_document(token, chat_id, fitted_path, caption, reply_to_message_id=_reply_message_id(task))
        if ok_retry:
            _send_telegram_message(
                token,
                chat_id,
                f"ℹ️ Видео #{getattr(task, 'id', '-')}: исходный файл был слишком большим для Telegram, отправлена сжатая копия.",
                reply_to_message_id=_reply_message_id(task),
            )
            return
        logger.warning("Failed to send compressed Telegram document: %s", error_retry)
        _send_telegram_message(
            token,
            chat_id,
            f"⚠️ Видео #{getattr(task, 'id', '-')}: даже сжатая копия не отправилась в Telegram ({error_retry[:200]}).",
            reply_to_message_id=_reply_message_id(task),
        )
    finally:
        try:
            if os.path.isfile(fitted_path):
                os.remove(fitted_path)
        except OSError:
            pass


def send_thumbnail_to_telegram(task, image_path: str, caption: str | None = None) -> None:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (getattr(task, "telegram_chat_id", None) or "").strip()
    if not token or not chat_id:
        return
    if not image_path or not os.path.isfile(image_path):
        logger.warning("Thumbnail file for Telegram is missing: %s", image_path)
        return

    if not caption:
        caption = f"🖼 Готова обложка.\n{build_task_context_text(task)}"

    try:
        data = {"chat_id": chat_id, "caption": caption}
        if _reply_message_id(task):
            data["reply_to_message_id"] = _reply_message_id(task)
            data["allow_sending_without_reply"] = "true"
        with httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
            with open(image_path, "rb") as f:
                response = client.post(
                    f"https://api.telegram.org/bot{token}/sendPhoto",
                    data=data,
                    files={"photo": (os.path.basename(image_path), f, "image/png")},
                )
        payload = response.json()
        if response.status_code >= 400 or not payload.get("ok", False):
            description = payload.get("description") if isinstance(payload, dict) else response.text[:300]
            logger.warning(
                "Failed to send Telegram thumbnail: status=%s description=%s",
                response.status_code,
                description,
            )
    except Exception as exc:
        logger.warning("Failed to send Telegram thumbnail: %s", exc)


def send_yandex_disk_links_to_telegram(task, uploads: list[dict]) -> None:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (getattr(task, "telegram_chat_id", None) or "").strip()
    if not token or not chat_id:
        return
    if not uploads:
        return

    format_label = get_task_format_label(task)

    lines = [
        "Все, Turan 🫶🏻",
        "Задача выполнена.",
        "",
        f"Формат: {format_label}",
        "Видео: 1/1",
        "Файл сохранен в Яндекс.Диск.",
        "",
        "Ссылки:",
    ]
    for idx, item in enumerate(uploads, start=1):
        file_name = os.path.basename((item.get("remote_path") or "").strip()) or f"Файл {idx}"
        public_url = (item.get("public_url") or "").strip()
        if public_url:
            lines.append(f"{idx}. {file_name}: {public_url}")
        else:
            remote_path = (item.get("remote_path") or "").strip()
            lines.append(f"{idx}. {file_name}: {remote_path}")

    lines.extend(["", "Ошибки: нет"])

    text = "\n".join(lines)
    for chunk in _split_message_chunks(text):
        _send_telegram_message(token, chat_id, chunk, reply_to_message_id=_reply_message_id(task))
