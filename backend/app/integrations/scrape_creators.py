import httpx
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class ScrapeCreatorsClient:
    BASE_URL = "https://api.scrapecreators.com/v1"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json"
        }

    def _get_json(self, path: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        url = f"{self.BASE_URL}/{path.lstrip('/')}"
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(url, headers=self.headers, params=params)
                response.raise_for_status()
                data = response.json()
                return data if isinstance(data, dict) else None
        except Exception as e:
            logger.error(f"ScrapeCreators request failed for {path}: {e}")
            return None

    def get_instagram_details(self, reel_url: str) -> Optional[Dict]:
        """
        Extracts Instagram Reel metadata and download link.
        """
        data = self._get_json("instagram/post", {"url": reel_url})
        if not data:
            return None
        return {
            "download_url": data.get("video_url") or data.get("download_url"),
            "caption": data.get("caption"),
            "view_count": data.get("viewCountInt"),
            "creator": (data.get("owner") or {}).get("username"),
        }

    def get_youtube_details(self, video_url: str) -> Optional[Dict]:
        """
        Extracts YouTube metadata and best available downloadable URL.
        """
        data = self._get_json("youtube/video", {"url": video_url})
        if not data:
            return None

        # Different API plans/versions may expose different field names.
        download_url = (
            data.get("download_url")
            or data.get("video_url")
            or data.get("url")
            or data.get("source")
        )

        if not download_url:
            files = data.get("files")
            if isinstance(files, list):
                for item in files:
                    if isinstance(item, dict):
                        candidate = item.get("url") or item.get("download_url")
                        if candidate:
                            download_url = candidate
                            break

        return {
            "download_url": download_url,
            "original_url": data.get("videoUrl") or video_url,
            "title": data.get("title"),
            "transcript": data.get("transcript"),
            "caption_tracks": data.get("captionTracks", []),
            "view_count": data.get("viewCountInt"),
            "raw": data,
        }
