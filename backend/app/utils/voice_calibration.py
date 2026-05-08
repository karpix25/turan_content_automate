import logging
import os
import tempfile
from typing import Any

import ffmpeg

from .. import models
from ..integrations.elevenlabs_client import ElevenLabsClient

logger = logging.getLogger(__name__)

VOICE_CALIBRATION_TEXT = (
    "В этом коротком фрагменте мы проверяем естественную скорость диктора. "
    "Текст специально написан обычными русскими предложениями: без скороговорок, "
    "без сложных чисел и без резких пауз. Он помогает понять, сколько символов "
    "этот голос успевает произнести за одну секунду, чтобы длинные YouTube-сценарии "
    "получались ближе к заданной длительности."
)


def count_script_chars(text: str | None) -> int:
    return len((text or "").strip())


def get_audio_duration_seconds(path: str) -> float | None:
    try:
        probe = ffmpeg.probe(path)
        duration_raw = (probe.get("format") or {}).get("duration")
        duration = float(duration_raw or 0)
        return duration if duration > 0 else None
    except Exception as e:
        logger.warning("Failed to probe voice calibration audio %s: %s", path, e)
        return None


def _voice_speed_cache(user: models.User) -> dict[str, Any]:
    raw = getattr(user, "elevenlabs_voice_speeds", None)
    return dict(raw) if isinstance(raw, dict) else {}


def get_cached_voice_speed(user: models.User, voice_id: str | None) -> dict[str, Any] | None:
    voice_key = (voice_id or "").strip()
    if not voice_key:
        return None
    item = _voice_speed_cache(user).get(voice_key)
    return dict(item) if isinstance(item, dict) else None


def get_or_calibrate_voice_speed(
    *,
    db,
    user: models.User,
    voice_id: str,
    elevenlabs_client: ElevenLabsClient,
) -> dict[str, Any] | None:
    voice_key = (voice_id or "").strip()
    if not voice_key:
        return None

    cached = get_cached_voice_speed(user, voice_key)
    if cached and cached.get("chars_per_second"):
        return cached

    if not elevenlabs_client.api_key:
        return None

    fd, output_path = tempfile.mkstemp(prefix=f"voice_calibration_{user.id}_", suffix=".mp3")
    os.close(fd)
    try:
        generated = elevenlabs_client.generate_audio(
            text=VOICE_CALIBRATION_TEXT,
            voice_id=voice_key,
            output_path=output_path,
        )
        if not generated:
            return None

        duration_seconds = get_audio_duration_seconds(output_path)
        char_count = count_script_chars(VOICE_CALIBRATION_TEXT)
        if not duration_seconds or char_count < 1:
            return None

        chars_per_second = round(char_count / duration_seconds, 3)
        item = {
            "chars_per_second": chars_per_second,
            "demo_char_count": char_count,
            "demo_duration_seconds": round(duration_seconds, 3),
        }
        cache = _voice_speed_cache(user)
        cache[voice_key] = item
        user.elevenlabs_voice_speeds = cache
        db.commit()
        db.refresh(user)
        return item
    except Exception as e:
        logger.warning("Failed to calibrate ElevenLabs voice %s for user %s: %s", voice_key, user.id, e)
        db.rollback()
        return None
    finally:
        try:
            os.remove(output_path)
        except OSError:
            pass

