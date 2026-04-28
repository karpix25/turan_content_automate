import httpx
import logging
import os
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
        
        try:
            with httpx.Client(timeout=300.0) as client:
                response = client.post(url, json=data, headers=headers)
                response.raise_for_status()
                with open(output_path, 'wb') as f:
                    for chunk in response.iter_bytes(chunk_size=8192):
                        f.write(chunk)
                return output_path
        except Exception as e:
            logger.error(f"ElevenLabs request failed: {e}")
            if hasattr(e, "response") and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            return None
