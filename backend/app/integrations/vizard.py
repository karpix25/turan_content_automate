import httpx
import logging
import asyncio
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

class VizardClient:
    BASE_URL = "https://elb-api.vizard.ai/hvizard-server-front/open-api/v1"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json"
        }

    async def create_project(self, video_url: str, template_id: Optional[str] = None) -> Optional[int]:
        """
        Submits a video URL to Vizard for clipping.
        Returns the projectId.
        """
        url = f"{self.BASE_URL}/project/create"
        payload = {
            "videoUrl": video_url
        }
        if template_id:
            payload["templateId"] = template_id

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, headers=self.headers, json=payload, timeout=30.0)
                response.raise_for_status()
                data = response.json()
                if data.get("code") == 2000:
                    return data.get("projectId")
                else:
                    logger.error(f"Vizard error: {data}")
                    return None
            except Exception as e:
                logger.error(f"Failed to create Vizard project: {e}")
                return None

    async def query_project(self, project_id: int) -> Optional[Dict]:
        """
        Polls for project status and results.
        """
        url = f"{self.BASE_URL}/project/query/{project_id}"
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=self.headers, timeout=30.0)
                response.raise_for_status()
                return response.json()
            except Exception as e:
                logger.error(f"Failed to query Vizard project {project_id}: {e}")
                return None

    async def poll_until_complete(self, project_id: int, interval: int = 30, max_attempts: int = 60) -> Optional[List[Dict]]:
        """
        High-level helper to poll until results are ready.
        """
        for attempt in range(max_attempts):
            data = await self.query_project(project_id)
            if data and data.get("code") == 2000:
                videos = data.get("videos")
                if videos:
                    return videos
                # If code is 2000 but no videos yet, it might still be processing
                logger.info(f"Vizard project {project_id} still processing... (Attempt {attempt+1})")
            
            await asyncio.sleep(interval)
        
        logger.error(f"Vizard polling timed out for project {project_id}")
        return None
