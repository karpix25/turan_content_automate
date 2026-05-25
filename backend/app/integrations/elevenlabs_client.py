import httpx
import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

class ElevenLabsClient:
    def __init__(self, api_key: str):
        self.api_key = api_key.strip()
        self.base_url = "https://api.elevenlabs.io/v1"

    def generate_audio(self, text: str, voice_id: str, output_path: str) -> Optional[str]:
        if not self.api_key:
            logger.error("ElevenLabs API key is missing")
            return None

        url = f"{self.base_url}/text-to-speech/{voice_id}"
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": self.api_key
        }
        
        data = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 1.0,
                "similarity_boost": 1.0,
                "speed": 1.0
            }
        }

        max_attempts = max(1, int(os.getenv("ELEVENLABS_TTS_MAX_RETRIES", "3")))
        backoff_seconds = max(0.0, float(os.getenv("ELEVENLABS_TTS_RETRY_BACKOFF_SECONDS", "2")))
        retryable_statuses = {408, 429, 500, 502, 503, 504}
        retryable_errors = (
            httpx.ConnectError,
            httpx.ReadError,
            httpx.RemoteProtocolError,
            httpx.TimeoutException,
            httpx.TransportError,
        )

        for attempt in range(1, max_attempts + 1):
            try:
                if attempt > 1 and os.path.exists(output_path):
                    os.remove(output_path)
                with httpx.Client(timeout=600.0) as client:
                    with client.stream("POST", url, json=data, headers=headers) as response:
                        if response.status_code >= 400:
                            error_body = response.read().decode("utf-8", errors="ignore")
                            if response.status_code in retryable_statuses and attempt < max_attempts:
                                logger.warning(
                                    "ElevenLabs request failed with retryable status=%s attempt=%s/%s body=%s",
                                    response.status_code,
                                    attempt,
                                    max_attempts,
                                    error_body[:1000],
                                )
                                time.sleep(backoff_seconds * attempt)
                                continue
                            logger.error(
                                "ElevenLabs request failed: status=%s attempt=%s/%s body=%s",
                                response.status_code,
                                attempt,
                                max_attempts,
                                error_body[:1000],
                            )
                            return None
                        with open(output_path, "wb") as f:
                            for chunk in response.iter_bytes(chunk_size=8192):
                                f.write(chunk)
                    return output_path
            except retryable_errors as e:
                if attempt < max_attempts:
                    logger.warning(
                        "ElevenLabs request hit retryable network error attempt=%s/%s: %s",
                        attempt,
                        max_attempts,
                        e,
                    )
                    time.sleep(backoff_seconds * attempt)
                    continue
                logger.error("ElevenLabs request failed after %s attempts: %s", max_attempts, e)
                return None
            except Exception as e:
                logger.error(f"ElevenLabs request failed: {e}")
                return None
        return None
