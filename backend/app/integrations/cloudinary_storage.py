import hashlib
import logging
import os
import time
from typing import Any

import httpx


logger = logging.getLogger(__name__)


class CloudinaryStorage:
    """Small adapter for the already configured Cloudinary account."""

    def __init__(self, *, timeout_seconds: float = 240, folder: str = "turan/assets") -> None:
        self.cloud_name = (os.getenv("CLOUDINARY_CLOUD_NAME") or "").strip()
        self.api_key = (os.getenv("CLOUDINARY_API_KEY") or "").strip()
        self.api_secret = (os.getenv("CLOUDINARY_API_SECRET") or "").strip()
        self.upload_preset = (os.getenv("CLOUDINARY_UPLOAD_PRESET") or "").strip()
        self.timeout_seconds = timeout_seconds
        self.folder = (folder or "turan/assets").strip().strip("/")

    @property
    def configured(self) -> bool:
        return bool(self.cloud_name and ((self.api_key and self.api_secret) or self.upload_preset))

    def _endpoint(self) -> str | None:
        if not self.cloud_name:
            return None
        return f"https://api.cloudinary.com/v1_1/{self.cloud_name}/image/upload"

    def _signature(self, params: dict[str, Any]) -> str:
        payload = "&".join(
            f"{key}={value}" for key, value in sorted(params.items()) if value is not None and value != ""
        )
        return hashlib.sha1(f"{payload}{self.api_secret}".encode("utf-8")).hexdigest()

    def upload_file(self, file_path: str, *, prefix: str) -> str | None:
        endpoint = self._endpoint()
        if not endpoint:
            logger.error("CLOUDINARY_CLOUD_NAME is not configured.")
            return None
        if not os.path.isfile(file_path):
            logger.error("Cloudinary upload source does not exist: %s", file_path)
            return None
        if not self.configured:
            logger.error(
                "Cloudinary is not fully configured. Set CLOUDINARY_UPLOAD_PRESET or "
                "CLOUDINARY_API_KEY/CLOUDINARY_API_SECRET."
            )
            return None

        timestamp = int(time.time())
        public_id = f"{prefix}_{timestamp}_{os.urandom(4).hex()}"
        upload_params: dict[str, Any] = {"folder": self.folder, "public_id": public_id}
        data: dict[str, Any] = dict(upload_params)
        if self.upload_preset:
            data["upload_preset"] = self.upload_preset
        else:
            data["timestamp"] = timestamp
            data["api_key"] = self.api_key
            data["signature"] = self._signature({**upload_params, "timestamp": timestamp})

        try:
            with open(file_path, "rb") as source:
                files = {"file": (os.path.basename(file_path), source, "application/octet-stream")}
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.post(endpoint, data=data, files=files)
                    response.raise_for_status()
                    payload = response.json()
        except Exception as exc:
            logger.error("Cloudinary upload failed for %s: %s", file_path, exc)
            return None

        secure_url = (payload or {}).get("secure_url")
        if isinstance(secure_url, str) and secure_url.strip():
            return secure_url.strip()
        logger.error("Cloudinary upload response has no secure_url: %s", payload)
        return None
