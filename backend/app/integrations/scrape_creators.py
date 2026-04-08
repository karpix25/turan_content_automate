import httpx
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)

class ScrapeCreatorsClient:
    BASE_URL = "https://api.scrapecreators.com/v1"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json"
        }

    async def get_instagram_details(self, reel_url: str) -> Optional[Dict]:
        """
        Extracts Instagram Reel metadata and download link.
        """
        url = f"{self.BASE_URL}/instagram/post"
        params = {"url": reel_url}
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=self.headers, params=params, timeout=30.0)
                response.raise_for_status()
                data = response.json()
                # Return standardized format
                return {
                    "download_url": data.get("video_url"),
                    "caption": data.get("caption"),
                    "view_count": data.get("viewCountInt"),
                    "creator": data.get("owner", {}).get("username")
                }
            except Exception as e:
                logger.error(f"Failed to fetch Instagram details from Scrape Creators: {e}")
                return None

    async def get_youtube_details(self, video_url: str) -> Optional[Dict]:
        """
        Extracts YouTube Video/Shorts metadata and transcript.
        """
        url = f"{self.BASE_URL}/youtube/video"
        params = {"url": video_url}
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=self.headers, params=params, timeout=30.0)
                response.raise_for_status()
                data = response.json()
                # Return standardized format
                return {
                    "original_url": data.get("videoUrl"),
                    "title": data.get("title"),
                    "transcript": data.get("transcript"),
                    "caption_tracks": data.get("captionTracks", []),
                    "view_count": data.get("viewCountInt")
                }
            except Exception as e:
                logger.error(f"Failed to fetch YouTube details from Scrape Creators: {e}")
                return None
