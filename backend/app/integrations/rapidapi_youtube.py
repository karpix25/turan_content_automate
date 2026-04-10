import logging
import time
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

import httpx

logger = logging.getLogger(__name__)


class RapidAPIYoutubeClient:
    BASE_URL = "https://youtube-mp4-mp3-downloader.p.rapidapi.com/api/v1"

    def __init__(
        self,
        api_key: str,
        host: str = "youtube-mp4-mp3-downloader.p.rapidapi.com",
        video_format: str = "720",
        audio_quality: str = "128",
        poll_interval_seconds: float = 2.0,
        timeout_seconds: float = 90.0,
    ):
        self.api_key = (api_key or "").strip()
        self.host = (host or "youtube-mp4-mp3-downloader.p.rapidapi.com").strip()
        self.video_format = (video_format or "720").strip()
        self.audio_quality = (audio_quality or "128").strip()
        self.poll_interval_seconds = max(1.0, float(poll_interval_seconds))
        self.timeout_seconds = max(10.0, float(timeout_seconds))

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-rapidapi-key": self.api_key,
            "x-rapidapi-host": self.host,
        }

    def _extract_video_id(self, youtube_url: str) -> Optional[str]:
        try:
            parsed = urlparse((youtube_url or "").strip())
            host = parsed.netloc.lower()
            path_parts = [part for part in parsed.path.split("/") if part]

            if "youtu.be" in host:
                candidate = path_parts[0] if path_parts else ""
                return candidate if len(candidate) == 11 else None

            if "youtube.com" in host:
                if len(path_parts) >= 2 and path_parts[0] == "shorts":
                    candidate = path_parts[1]
                    return candidate if len(candidate) == 11 else None
                if parsed.path == "/watch":
                    candidate = parse_qs(parsed.query).get("v", [""])[0]
                    return candidate if len(candidate) == 11 else None
        except Exception:
            return None
        return None

    def _get_json(self, endpoint: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                response = client.get(
                    f"{self.BASE_URL}{endpoint}",
                    headers=self._headers(),
                    params=params,
                )
                response.raise_for_status()
                data = response.json()
                return data if isinstance(data, dict) else None
        except httpx.HTTPStatusError as e:
            body_preview = (e.response.text or "").strip().replace("\n", " ")[:350]
            logger.error(
                "RapidAPI YouTube request failed: endpoint=%s HTTP %s. Body: %s",
                endpoint,
                e.response.status_code,
                body_preview,
            )
            return None
        except Exception as e:
            logger.error("RapidAPI YouTube request failed: endpoint=%s error=%s", endpoint, e)
            return None

    def _is_direct_media_url(self, value: str) -> bool:
        if not isinstance(value, str):
            return False
        url = value.strip()
        if not url.startswith(("http://", "https://")):
            return False
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        path = parsed.path.lower()
        if "youtube.com" in host and (path.startswith("/watch") or "/shorts/" in path):
            return False
        return True

    def _first_direct_media_url(self, value: Any) -> Optional[str]:
        if isinstance(value, str) and self._is_direct_media_url(value):
            return value
        if isinstance(value, dict):
            for nested in value.values():
                found = self._first_direct_media_url(nested)
                if found:
                    return found
        if isinstance(value, list):
            for item in value:
                found = self._first_direct_media_url(item)
                if found:
                    return found
        return None

    def _extract_progress_id(self, data: Dict[str, Any]) -> Optional[str]:
        keys = ("id", "progressId", "progress_id", "downloadId", "download_id", "jobId", "job_id")
        for key in keys:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        nested = data.get("data")
        if isinstance(nested, dict):
            return self._extract_progress_id(nested)
        return None

    def _extract_status(self, data: Dict[str, Any]) -> str:
        for key in ("status", "state", "message", "progress"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().lower()
        nested = data.get("data")
        if isinstance(nested, dict):
            return self._extract_status(nested)
        return ""

    def _extract_error(self, data: Dict[str, Any]) -> Optional[str]:
        for key in ("error", "message", "detail", "description"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        nested = data.get("data")
        if isinstance(nested, dict):
            return self._extract_error(nested)
        return None

    def _is_terminal_failure(self, status: str, error_text: str | None) -> bool:
        if error_text and "success" not in error_text.lower():
            return True
        return status in {"failed", "error", "cancelled", "canceled", "not_found", "not found"}

    def _is_terminal_success(self, status: str, download_url: str | None) -> bool:
        if download_url:
            return True
        return status in {"success", "completed", "complete", "done", "finished", "ready"}

    def get_youtube_details(self, youtube_url: str) -> Dict[str, Any]:
        if not self.is_configured():
            return {"download_url": None, "error": "RAPIDAPI_KEY is not configured"}

        video_id = self._extract_video_id(youtube_url)
        if not video_id:
            return {"download_url": None, "error": "Invalid YouTube URL (cannot extract video id)"}

        start_data = self._get_json(
            "/download",
            {
                "format": self.video_format,
                "id": video_id,
                "audioQuality": self.audio_quality,
                "addInfo": "false",
            },
        )
        if not start_data:
            return {"download_url": None, "error": "RapidAPI download request failed"}

        initial_url = self._first_direct_media_url(start_data)
        if initial_url:
            return {
                "download_url": initial_url,
                "video_id": video_id,
                "status": "ready",
                "error": None,
                "raw": start_data,
            }

        progress_id = self._extract_progress_id(start_data)
        if not progress_id:
            return {
                "download_url": None,
                "video_id": video_id,
                "error": self._extract_error(start_data) or "RapidAPI did not return progress id",
                "raw": start_data,
            }

        deadline = time.monotonic() + self.timeout_seconds
        last_status = ""
        last_error = None
        last_payload: Dict[str, Any] = start_data

        while time.monotonic() < deadline:
            progress_data = self._get_json("/progress", {"id": progress_id})
            if progress_data:
                last_payload = progress_data
                download_url = self._first_direct_media_url(progress_data)
                status = self._extract_status(progress_data)
                error_text = self._extract_error(progress_data)
                last_status = status or last_status
                last_error = error_text or last_error

                if self._is_terminal_success(status, download_url):
                    return {
                        "download_url": download_url,
                        "video_id": video_id,
                        "progress_id": progress_id,
                        "status": status or "ready",
                        "error": None if download_url else "RapidAPI status is ready but no direct URL returned",
                        "raw": progress_data,
                    }

                if self._is_terminal_failure(status, error_text):
                    return {
                        "download_url": None,
                        "video_id": video_id,
                        "progress_id": progress_id,
                        "status": status,
                        "error": error_text or f"RapidAPI reported terminal status: {status}",
                        "raw": progress_data,
                    }

            time.sleep(self.poll_interval_seconds)

        return {
            "download_url": None,
            "video_id": video_id,
            "progress_id": progress_id,
            "status": last_status or "timeout",
            "error": last_error or "RapidAPI progress polling timed out",
            "raw": last_payload,
        }
