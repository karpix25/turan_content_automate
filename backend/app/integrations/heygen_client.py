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
        api_version: str = "v2",
        engine: str = "avatar_iv",
        title: str | None = None,
    ) -> Optional[str]:
        """
        Submits a video generation task to HeyGen.
        Returns video_id.
        """
        is_vertical = (orientation or "").strip().lower() in {"vertical", "portrait", "9:16"}
        api_version_value = (api_version or "v2").strip().lower()
        if api_version_value == "v3":
            url = f"{self.base_url}/v3/videos"
            engine_type = (engine or "avatar_iv").strip().lower()
            if engine_type not in {"avatar_iv", "avatar_v"}:
                engine_type = "avatar_iv"
            payload = {
                "type": "avatar",
                "avatar_id": avatar_id,
                "audio_asset_id": audio_asset_id,
                "aspect_ratio": "9:16" if is_vertical else "16:9",
                "resolution": "1080p",
                "output_format": "mp4",
                "engine": {"type": engine_type},
            }
            if title:
                payload["title"] = title[:120]
        else:
            url = f"{self.base_url}/v2/video/generate"
            payload = {
                "video_inputs": [
                    {
                        "character": {
                            "type": "avatar",
                            "avatar_id": avatar_id,
                            "avatar_style": "normal",
                        },
                        "voice": {
                            "type": "audio",
                            "audio_asset_id": audio_asset_id,
                        },
                    }
                ],
                "dimension": {
                    "width": 1080 if is_vertical else 1920,
                    "height": 1920 if is_vertical else 1080,
                },
            }

        logger.info(
            "HeyGen generation request: api_version=%s endpoint=%s orientation=%s dimension=%s resolution=%s engine=%s",
            api_version_value,
            url,
            "vertical" if is_vertical else "horizontal",
            payload.get("dimension"),
            payload.get("resolution"),
            payload.get("engine"),
        )
        
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
        v3_url = f"{self.base_url}/v3/videos/{video_id}"
        legacy_url = f"{self.base_url}/v1/video_status.get"
        legacy_params = {"video_id": video_id}
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(v3_url, headers=self.headers)
                    if response.status_code in {404, 405}:
                        response = await client.get(legacy_url, headers=self.headers, params=legacy_params)
                    elif response.status_code != 200 and response.status_code < 500:
                        legacy_response = await client.get(legacy_url, headers=self.headers, params=legacy_params)
                        if legacy_response.status_code == 200:
                            response = legacy_response
                    
                    if response.status_code != 200:
                        logger.error(f"HeyGen status check failed: {response.status_code} {response.text}")
                        return None

                    data = response.json()
                    payload = data.get("data", {}) if isinstance(data, dict) else {}
                    status = payload.get("status")
                    
                    if status == "completed":
                        return payload.get("video_url") or payload.get("url")
                    elif status == "failed":
                        logger.error(
                            "HeyGen video generation failed: %s",
                            payload.get("failure_message") or payload.get("error"),
                        )
                        return None
                    
                    logger.info(f"HeyGen video {video_id} status: {status}")
            except Exception as e:
                logger.error(f"Error polling HeyGen status: {e}")
            
            await asyncio.sleep(interval)
            
        logger.error(f"HeyGen video {video_id} timed out")
        return None
