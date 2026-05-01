import os
from typing import Optional

import httpx


class DeepgramClient:
    BASE_URL = "https://api.deepgram.com/v1/listen"

    def __init__(self, api_key: str):
        self.api_key = (api_key or "").strip()
        self.timeout_seconds = float(os.getenv("DEEPGRAM_TIMEOUT_SECONDS", "180"))
        self.model = (os.getenv("DEEPGRAM_MODEL") or "nova-3").strip()
        self.language = (os.getenv("DEEPGRAM_LANGUAGE") or "ru").strip()

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def transcribe_media_text(self, media_path: str) -> Optional[str]:
        if not self.is_configured:
            return None
        if not media_path or not os.path.isfile(media_path):
            return None

        params = {
            "model": self.model,
            "language": self.language,
            "punctuate": "true",
            "smart_format": "true",
            "paragraphs": "true",
            "utterances": "true",
        }
        headers = {"Authorization": f"Token {self.api_key}"}

        with open(media_path, "rb") as fh:
            payload = fh.read()

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(
                    self.BASE_URL,
                    params=params,
                    headers=headers,
                    content=payload,
                )
                response.raise_for_status()
                data = response.json()
        except Exception:
            return None

        results = (data or {}).get("results") or {}
        utterances = results.get("utterances") or []
        texts: list[str] = []
        for utt in utterances:
            text = (utt.get("transcript") or "").strip()
            if text:
                texts.append(text)
        if texts:
            return " ".join(texts).strip()

        channels = results.get("channels") or []
        alternatives = (channels[0].get("alternatives") if channels else None) or []
        if not alternatives:
            return None
        transcript = (alternatives[0].get("transcript") or "").strip()
        return transcript or None
