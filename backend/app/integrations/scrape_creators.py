import httpx
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class ScrapeCreatorsClient:
    BASE_URL = "https://api.scrapecreators.com/v1"

    def __init__(self, api_key: str):
        self.api_key = (api_key or "").strip()
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
        except httpx.HTTPStatusError as e:
            body_preview = (e.response.text or "").strip().replace("\n", " ")[:300]
            logger.error(
                "ScrapeCreators request failed for %s: HTTP %s. Body: %s",
                path,
                e.response.status_code,
                body_preview,
            )
            return None
        except Exception as e:
            logger.error(f"ScrapeCreators request failed for {path}: {e}")
            return None

    def get_instagram_details(self, reel_url: str) -> Optional[Dict]:
        """
        Extracts Instagram Reel metadata and download link.
        """
        data = self._get_json("instagram/post", {"url": reel_url})
        if not data:
            return {"download_url": None, "error": "ScrapeCreators request failed"}
        if data.get("success") is False:
            return {
                "download_url": None,
                "error": data.get("message") or "ScrapeCreators returned success=false",
            }

        media = ((data.get("data") or {}).get("xdt_shortcode_media") or {})
        caption_edges = ((media.get("edge_media_to_caption") or {}).get("edges") or [])
        caption_text = None
        if caption_edges and isinstance(caption_edges[0], dict):
            caption_text = ((caption_edges[0].get("node") or {}).get("text"))

        owner = media.get("owner") or {}

        return {
            "download_url": (
                data.get("video_url")
                or data.get("download_url")
                or media.get("video_url")
            ),
            "caption": data.get("caption") or caption_text,
            "view_count": data.get("viewCountInt") or media.get("video_view_count"),
            "creator": (data.get("owner") or {}).get("username") or owner.get("username"),
            "error": None,
        }

    def get_youtube_details(self, video_url: str) -> Optional[Dict]:
        """
        Extracts YouTube metadata and best available downloadable URL from ScrapeCreators.
        """
        data = self._get_json("youtube/video", {"url": video_url})
        if not data:
            return {"download_url": None, "error": "ScrapeCreators request failed"}
        if data.get("success") is False:
            return {
                "download_url": None,
                "error": data.get("message") or "ScrapeCreators returned success=false",
                "raw": data,
            }

        # Different API plans/versions may expose different field names.
        download_url = (
            data.get("download_url")
            or data.get("video_url")
        )

        if not download_url:
            for key in ("files", "formats", "sources", "videos"):
                items = data.get(key)
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    candidate = item.get("download_url") or item.get("video_url") or item.get("url")
                    if candidate:
                        download_url = candidate
                        break
                if download_url:
                    break

        return {
            "download_url": download_url,
            "original_url": data.get("url") or data.get("videoUrl") or video_url,
            "title": data.get("title"),
            "transcript": data.get("transcript"),
            "transcript_only_text": data.get("transcript_only_text"),
            "caption_tracks": data.get("captionTracks", []),
            "view_count": data.get("viewCountInt"),
            "credits_remaining": data.get("credits_remaining"),
            "error": None,
            "raw": data,
        }
