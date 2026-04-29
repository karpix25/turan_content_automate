import base64
import logging
import mimetypes
import os
from typing import Any

import httpx


logger = logging.getLogger(__name__)


class ThumbnailGeneratorClient:
    def __init__(self) -> None:
        self.api_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
        self.base_url = (os.getenv("THUMBNAIL_IMAGE_BASE_URL") or "https://openrouter.ai/api/v1").rstrip("/")
        self.model_id = (os.getenv("THUMBNAIL_IMAGE_MODEL") or "openai/gpt-image-1").strip()
        self.webhook_url = (os.getenv("THUMBNAIL_GENERATOR_WEBHOOK_URL") or "").strip()
        self.timeout_seconds = float(os.getenv("THUMBNAIL_GENERATOR_TIMEOUT_SECONDS", "180"))

    def _file_to_data_url(self, file_path: str) -> str | None:
        if not file_path or not os.path.isfile(file_path):
            return None
        mime, _ = mimetypes.guess_type(file_path)
        if not mime:
            mime = "image/png"
        try:
            with open(file_path, "rb") as fh:
                encoded = base64.b64encode(fh.read()).decode("ascii")
            return f"data:{mime};base64,{encoded}"
        except OSError as exc:
            logger.warning("Failed to read thumbnail asset %s: %s", file_path, exc)
            return None

    def _decode_to_file(self, b64_image: str, output_path: str) -> str | None:
        try:
            raw = base64.b64decode(b64_image)
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, "wb") as out:
                out.write(raw)
            return output_path
        except Exception as exc:
            logger.warning("Failed to decode generated thumbnail image: %s", exc)
            return None

    def _download_to_file(self, image_url: str, output_path: str) -> str | None:
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.get(image_url)
                response.raise_for_status()
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, "wb") as out:
                out.write(response.content)
            return output_path
        except Exception as exc:
            logger.warning("Failed to download generated thumbnail from %s: %s", image_url, exc)
            return None

    def _request_webhook(self, payload: dict[str, Any], output_path: str) -> str | None:
        if not self.webhook_url:
            return None
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(self.webhook_url, json=payload)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            logger.error("Thumbnail webhook generation failed: %s", exc)
            return None

        image_b64 = (data or {}).get("image_base64")
        if isinstance(image_b64, str) and image_b64.strip():
            return self._decode_to_file(image_b64.strip(), output_path)

        image_url = (data or {}).get("image_url")
        if isinstance(image_url, str) and image_url.strip():
            return self._download_to_file(image_url.strip(), output_path)
        return None

    def _request_openrouter(self, prompt: str, output_path: str) -> str | None:
        if not self.api_key:
            logger.warning("OPENROUTER_API_KEY is empty; thumbnail generation skipped.")
            return None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model_id,
            "prompt": prompt,
            "size": os.getenv("THUMBNAIL_IMAGE_SIZE", "1280x720"),
            "response_format": "b64_json",
        }
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(f"{self.base_url}/images/generations", headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            logger.error("OpenRouter thumbnail generation failed: %s", exc)
            return None

        data_items = (data or {}).get("data") or []
        if not data_items:
            return None

        item = data_items[0] or {}
        image_b64 = item.get("b64_json")
        if isinstance(image_b64, str) and image_b64.strip():
            return self._decode_to_file(image_b64.strip(), output_path)

        image_url = item.get("url")
        if isinstance(image_url, str) and image_url.strip():
            return self._download_to_file(image_url.strip(), output_path)
        return None

    def generate_thumbnail(
        self,
        *,
        prompt: str,
        face_path: str | None,
        reference_paths: list[str],
        output_path: str,
    ) -> str | None:
        clean_prompt = (prompt or "").strip()
        if not clean_prompt:
            return None

        refs = [p for p in reference_paths if p and os.path.isfile(p)]
        face_data_url = self._file_to_data_url(face_path or "") if face_path else None
        ref_data_urls = [url for path in refs[:5] if (url := self._file_to_data_url(path))]

        augmented_prompt = clean_prompt
        if face_data_url:
            augmented_prompt += "\nСохрани узнаваемость лица автора (из предоставленного face reference)."
        if ref_data_urls:
            augmented_prompt += "\nУчитывай стиль/композицию из референсов, но не копируй один-в-один."

        payload = {
            "prompt": augmented_prompt,
            "face_image_data_url": face_data_url,
            "reference_images_data_url": ref_data_urls,
            "output_path": output_path,
        }

        # Prefer explicit webhook integration if configured.
        generated_path = self._request_webhook(payload, output_path)
        if generated_path:
            return generated_path

        # Fallback: default OpenRouter image generation (prompt-based).
        return self._request_openrouter(augmented_prompt, output_path)
