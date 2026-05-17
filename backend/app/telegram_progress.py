import logging
import os
import re
import subprocess
import tempfile

import httpx


logger = logging.getLogger(__name__)
MAX_TELEGRAM_TEXT_LEN = 3900
TELEGRAM_UPLOAD_MAX_BYTES = 49 * 1024 * 1024


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


def send_thumbnail_prompt_review_to_telegram(task, prompt: str) -> bool:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (getattr(task, "telegram_chat_id", None) or "").strip()
    if not token or not chat_id or not prompt:
        return False

    chunks = _split_message_chunks(
        f"🖼 Prompt обложки для видео #{getattr(task, 'id', '-')}:\n\n{prompt}",
        max_len=MAX_TELEGRAM_TEXT_LEN,
    )
    ok = True
    for chunk in chunks:
        ok = _send_telegram_message(token, chat_id, chunk) and ok

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
            response = client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": "Проверь prompt обложки. Можно подтвердить, отклонить или нажать Edit и отправить новый prompt следующим сообщением.",
                    "reply_markup": keyboard,
                    "disable_web_page_preview": True,
                },
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


def _send_telegram_document(token: str, chat_id: str, file_path: str, caption: str) -> tuple[bool, str]:
    try:
        with httpx.Client(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
            with open(file_path, "rb") as f:
                response = client.post(
                    f"https://api.telegram.org/bot{token}/sendDocument",
                    data={"chat_id": chat_id, "caption": caption},
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
        f"Видео #{getattr(task, 'id', '-')}"
    )
    
    try:
        with httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
            with open(audio_path, "rb") as f:
                response = client.post(
                    f"https://api.telegram.org/bot{token}/sendAudio",
                    data={"chat_id": chat_id, "caption": caption},
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
        caption = f"✅ Файл с видео готов.\nВидео #{getattr(task, 'id', '-')}"
    
    ok, error_text = _send_telegram_document(token, chat_id, video_path, caption)
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
        )
        return

    try:
        ok_retry, error_retry = _send_telegram_document(token, chat_id, fitted_path, caption)
        if ok_retry:
            _send_telegram_message(
                token,
                chat_id,
                f"ℹ️ Видео #{getattr(task, 'id', '-')}: исходный файл был слишком большим для Telegram, отправлена сжатая копия.",
            )
            return
        logger.warning("Failed to send compressed Telegram document: %s", error_retry)
        _send_telegram_message(
            token,
            chat_id,
            f"⚠️ Видео #{getattr(task, 'id', '-')}: даже сжатая копия не отправилась в Telegram ({error_retry[:200]}).",
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
        title = (getattr(task, "source_title", None) or "").strip()
        title_line = f"\nTitle: {title}" if title else ""
        caption = f"🖼 Готова обложка для видео #{getattr(task, 'id', '-')}.{title_line}"

    try:
        with httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
            with open(image_path, "rb") as f:
                response = client.post(
                    f"https://api.telegram.org/bot{token}/sendPhoto",
                    data={"chat_id": chat_id, "caption": caption},
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

    lines = [f"✅ Видео #{getattr(task, 'id', '-')}: файл сохранен в Яндекс.Диск."]
    for idx, item in enumerate(uploads, start=1):
        file_name = os.path.basename((item.get("remote_path") or "").strip()) or f"Файл {idx}"
        public_url = (item.get("public_url") or "").strip()
        if public_url:
            lines.append(f"{idx}. {file_name}: {public_url}")
        else:
            remote_path = (item.get("remote_path") or "").strip()
            lines.append(f"{idx}. {file_name}: {remote_path}")

    text = "\n".join(lines)
    for chunk in _split_message_chunks(text):
        _send_telegram_message(token, chat_id, chunk)
