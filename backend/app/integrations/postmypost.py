import httpx
import logging
import os
from typing import Optional, List, Dict
import datetime

logger = logging.getLogger(__name__)

class PostMyPostClient:
    BASE_URL = "https://api.postmypost.io/v1"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json"
        }

    async def upload_file(self, file_path: str) -> Optional[str]:
        """
        Uploads a video file to PostMyPost and returns the media ID.
        """
        url = f"{self.BASE_URL}/files/upload"
        
        async with httpx.AsyncClient() as client:
            try:
                with open(file_path, "rb") as f:
                    files = {"file": f}
                    response = await client.post(url, headers=self.headers, files=files, timeout=300.0)
                    response.raise_for_status()
                    data = response.json()
                    # Expecting {'id': '...'} or similar in the response
                    return data.get("id")
            except Exception as e:
                logger.error(f"Failed to upload file to PostMyPost: {e}")
                return None

    async def create_publication(self, 
                                 text: str, 
                                 media_ids: List[str], 
                                 channels: List[int], 
                                 scheduled_at: Optional[datetime.datetime] = None) -> Optional[Dict]:
        """
        Creates a publication on PostMyPost.
        """
        url = f"{self.BASE_URL}/publications"
        payload = {
            "text": text,
            "media": media_ids,
            "channels": channels,
        }
        
        if scheduled_at:
            payload["scheduledAt"] = scheduled_at.isoformat()

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, headers=self.headers, json=payload, timeout=30.0)
                response.raise_for_status()
                return response.json()
            except Exception as e:
                logger.error(f"Failed to create publication on PostMyPost: {e}")
                return None
