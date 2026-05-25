import httpx
import logging
import asyncio
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

class VizardClient:
    BASE_URL = "https://elb-api.vizard.ai/hvizard-server-front/open-api/v1"

    def __init__(self, api_key: str):
        self.api_key = (api_key or "").strip()
        self.headers = {
            "VIZARDAI_API_KEY": self.api_key,
            "Content-Type": "application/json"
        }

    async def create_project(
        self,
        video_url: str,
        template_id: Optional[str] = None,
        *,
        video_type: Optional[int] = None,
        prefer_length: Optional[List[int]] = None,
        lang: Optional[str] = None,
        ratio_of_clip: Optional[int] = None,
        get_clips: Optional[int] = None,
        highlight_switch: Optional[int] = None,
        subtitle_switch: Optional[int] = None,
        auto_broll_switch: Optional[int] = None,
        headline_switch: Optional[int] = None,
        remove_silence_switch: Optional[int] = None,
        project_name: Optional[str] = None,
    ) -> Optional[int]:
        """
        Submits a video URL to Vizard for clipping.
        Returns the projectId.
        """
        url = f"{self.BASE_URL}/project/create"
        payload = {"videoUrl": video_url}
        if template_id:
            payload["templateId"] = template_id
        if video_type is not None:
            payload["videoType"] = video_type
        if prefer_length is not None:
            # Vizard API requires an array of integers for preferLength
            payload["preferLength"] = prefer_length if isinstance(prefer_length, list) else [prefer_length]
        if lang:
            payload["lang"] = lang
        if ratio_of_clip is not None:
            payload["ratioOfClip"] = ratio_of_clip
        if get_clips is not None:
            payload["getClips"] = get_clips
        if highlight_switch is not None:
            payload["highlightSwitch"] = highlight_switch
        if subtitle_switch is not None:
            payload["subtitleSwitch"] = subtitle_switch
        if auto_broll_switch is not None:
            payload["autoBrollSwitch"] = auto_broll_switch
        if headline_switch is not None:
            payload["headlineSwitch"] = headline_switch
        if remove_silence_switch is not None:
            payload["removeSilenceSwitch"] = remove_silence_switch
        if project_name:
            payload["projectName"] = project_name

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
            if data:
                code = data.get("code")
                if code == 2000:
                    videos = data.get("videos")
                    if videos:
                        return videos
                    logger.info(f"Vizard project {project_id} still processing... (Attempt {attempt+1})")
                elif code == 1000:
                    logger.info(f"Vizard project {project_id} still processing... (Attempt {attempt+1})")
                else:
                    message = data.get("errMsg") or data.get("msg") or data.get("message") or data.get("error") or data
                    logger.error("Vizard project %s failed while polling: %s", project_id, message)
                    return None
            
            await asyncio.sleep(interval)
        
        logger.error(f"Vizard polling timed out for project {project_id}")
        return None
