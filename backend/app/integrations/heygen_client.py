import os
import time
import logging
import httpx
import asyncio
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class HeyGenClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.heygen.com"
        self.headers = {
            "X-Api-Key": self.api_key,
            "Content-Type": "application/json"
        }

    async def upload_asset(self, file_path: str, file_type: str = "audio") -> Optional[str]:
        """
        Uploads a file to HeyGen and returns the asset ID.
        HeyGen v1 asset upload: POST https://upload.heygen.com/v1/asset
        """
        url = "https://upload.heygen.com/v1/asset"
        
        headers = {
            "X-Api-Key": self.api_key,
            "Content-Type": "audio/mpeg" if file_type == "audio" else "application/octet-stream"
        }
        
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                with open(file_path, "rb") as f:
                    content = f.read()
                    
                response = await client.post(url, headers=headers, content=content)
                    
                if response.status_code != 200:
                    logger.error(f"HeyGen upload failed: {response.status_code} {response.text}")
                    return None
                
                data = response.json()
                return data.get("data", {}).get("id")
        except Exception as e:
            logger.exception(f"Error uploading asset to HeyGen: {e}")
            return None

    async def generate_avatar_video(
        self,
        avatar_id: str,
        audio_asset_id: str,
        orientation: str = "horizontal",
    ) -> Optional[str]:
        """
        Submits a video generation task to HeyGen v2.
        Returns video_id.
        """
        url = f"{self.base_url}/v2/video/generate"
        
        is_vertical = (orientation or "").strip().lower() in {"vertical", "portrait", "9:16"}
        payload = {
            "video_inputs": [
                {
                    "character": {
                        "type": "avatar",
                        "avatar_id": avatar_id,
                        "avatar_style": "normal"
                    },
                    "voice": {
                        "type": "audio",
                        "audio_asset_id": audio_asset_id
                    }
                }
            ],
            "dimension": {
                "width": 1080 if is_vertical else 1920,
                "height": 1920 if is_vertical else 1080
            }
        }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers=self.headers, json=payload)
                
                if response.status_code != 200:
                    logger.error(f"HeyGen video generation failed: {response.status_code} {response.text}")
                    return None
                
                data = response.json()
                return data.get("data", {}).get("video_id")
        except Exception as e:
            logger.exception(f"Error submitting video to HeyGen: {e}")
            return None

    async def poll_video_status(self, video_id: str, timeout: int = 1800, interval: int = 10) -> Optional[str]:
        """
        Polls for video completion. Returns download URL.
        """
        url = f"{self.base_url}/v1/video_status.get"
        params = {"video_id": video_id}
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(url, headers=self.headers, params=params)
                    
                    if response.status_code != 200:
                        logger.error(f"HeyGen status check failed: {response.status_code} {response.text}")
                        return None
                    
                    data = response.json()
                    status = data.get("data", {}).get("status")
                    
                    if status == "completed":
                        return data.get("data", {}).get("video_url")
                    elif status == "failed":
                        logger.error(f"HeyGen video generation failed: {data.get('data', {}).get('error')}")
                        return None
                    
                    logger.info(f"HeyGen video {video_id} status: {status}")
            except Exception as e:
                logger.error(f"Error polling HeyGen status: {e}")
            
            await asyncio.sleep(interval)
            
        logger.error(f"HeyGen video {video_id} timed out")
        return None
