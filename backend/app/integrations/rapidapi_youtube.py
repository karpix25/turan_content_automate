import logging
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

import httpx

logger = logging.getLogger(__name__)


class RapidAPIYoutubeClient:
    BASE_URL = "https://youtube-media-downloader.p.rapidapi.com"

    def __init__(self, api_key: str, host: str = "youtube-media-downloader.p.rapidapi.com"):
        self.api_key = (api_key or "").strip()
        self.host = (host or "youtube-media-downloader.p.rapidapi.com").strip()

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/json",
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

    def _get_json(self, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        endpoint = f"{self.BASE_URL}/v2/video/details"
        try:
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                response = client.get(endpoint, headers=self._headers(), params=params)
                response.raise_for_status()
                data = response.json()
                return data if isinstance(data, dict) else None
        except httpx.HTTPStatusError as e:
            body_preview = (e.response.text or "").strip().replace("\n", " ")[:350]
            logger.error(
                "RapidAPI YouTube request failed: HTTP %s. Body: %s",
                e.response.status_code,
                body_preview,
            )
            return None
        except Exception as e:
            logger.error("RapidAPI YouTube request failed: %s", e)
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

    def _iter_dicts(self, value: Any):
        if isinstance(value, dict):
            yield value
            for nested in value.values():
                yield from self._iter_dicts(nested)
            return
        if isinstance(value, list):
            for item in value:
                yield from self._iter_dicts(item)

    def _score_candidate(self, item: Dict[str, Any], url: str) -> int:
        score = 0

        mime = str(
            item.get("mimeType")
            or item.get("mime_type")
            or item.get("contentType")
            or item.get("type")
            or ""
        ).lower()

        if item.get("hasVideo") is True:
            score += 120
        if item.get("hasAudio") is True:
            score += 80
        if "video/mp4" in mime:
            score += 60
        elif "video/" in mime:
            score += 30
        if urlparse(url).path.lower().endswith(".mp4"):
            score += 40

        quality = str(item.get("qualityLabel") or item.get("quality") or "")
        quality_digits = "".join(ch for ch in quality if ch.isdigit())
        if quality_digits:
            try:
                score += min(int(quality_digits), 2160)
            except ValueError:
                pass

        bitrate = item.get("bitrate") or item.get("audioBitrate")
        if isinstance(bitrate, int) and bitrate > 0:
            score += min(bitrate // 10000, 100)

        return score

    def _extract_download_url(self, data: Dict[str, Any]) -> Optional[str]:
        direct_fields = (
            data.get("download_url"),
            data.get("downloadUrl"),
            data.get("video_url"),
            data.get("videoUrl"),
        )
        for value in direct_fields:
            if isinstance(value, str) and self._is_direct_media_url(value):
                return value

        best_url = None
        best_score = -1
        for item in self._iter_dicts(data):
            url = (
                item.get("url")
                or item.get("download_url")
                or item.get("downloadUrl")
                or item.get("video_url")
                or item.get("videoUrl")
            )
            if not isinstance(url, str) or not self._is_direct_media_url(url):
                continue
            score = self._score_candidate(item, url)
            if score > best_score:
                best_score = score
                best_url = url

        return best_url

    def get_youtube_details(self, youtube_url: str) -> Dict[str, Any]:
        if not self.is_configured():
            return {"download_url": None, "error": "RAPIDAPI_KEY is not configured"}

        video_id = self._extract_video_id(youtube_url)
        if not video_id:
            return {"download_url": None, "error": "Invalid YouTube URL (cannot extract video id)"}

        # The current endpoint requires `videoId`; keep `url` as an auxiliary hint.
        data = self._get_json({"videoId": video_id, "url": youtube_url})
        if not data:
            return {"download_url": None, "error": "RapidAPI request failed"}

        if data.get("success") is False:
            return {
                "download_url": None,
                "error": data.get("message") or "RapidAPI returned success=false",
                "raw": data,
            }

        download_url = self._extract_download_url(data)
        return {
            "download_url": download_url,
            "video_id": data.get("id") or video_id,
            "title": data.get("title"),
            "error": None if download_url else "No direct media URL found in RapidAPI response",
            "raw": data,
        }
