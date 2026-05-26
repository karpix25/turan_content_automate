import httpx
import logging
import re
from typing import Optional, Dict, Any
from urllib.parse import urlparse

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
        image_urls: list[str] = []

        def add_image_url(value: Any) -> None:
            if isinstance(value, str) and value.startswith(("http://", "https://")) and value not in image_urls:
                image_urls.append(value)

        def collect_media_images(node: Any) -> None:
            if not isinstance(node, dict):
                return
            add_image_url(node.get("display_url"))
            add_image_url(node.get("thumbnail_src"))
            add_image_url(node.get("image_url"))
            add_image_url(node.get("imageUrl"))
            for resource in node.get("display_resources") or []:
                if isinstance(resource, dict):
                    add_image_url(resource.get("src"))
            sidecar_edges = ((node.get("edge_sidecar_to_children") or {}).get("edges") or [])
            for edge in sidecar_edges:
                collect_media_images((edge or {}).get("node"))

        collect_media_images(media)
        add_image_url(data.get("image_url"))
        add_image_url(data.get("imageUrl"))
        add_image_url(data.get("thumbnail_url"))
        add_image_url(data.get("thumbnailUrl"))

        return {
            "download_url": (
                data.get("video_url")
                or data.get("download_url")
                or media.get("video_url")
            ),
            "image_urls": image_urls,
            "caption": data.get("caption") or caption_text,
            "view_count": data.get("viewCountInt") or media.get("video_view_count"),
            "creator": (data.get("owner") or {}).get("username") or owner.get("username"),
            "error": None,
            "raw": data,
        }

    def get_youtube_transcript(self, video_url: str) -> Optional[Dict]:
        """
        Extracts YouTube transcript directly using the specific transcript endpoint.
        """
        return self._get_json("youtube/video/transcript", {"url": video_url})

    def _extract_channel_lookup_from_input(self, channel_url_or_handle: str) -> Optional[Dict[str, str]]:
        raw = (channel_url_or_handle or "").strip()
        if not raw:
            return None

        if raw.startswith("@"):
            handle = raw[1:].strip()
            return {"handle": handle} if handle else None

        if re.fullmatch(r"UC[A-Za-z0-9_-]{20,}", raw):
            return {"channelId": raw}

        parse_target = raw
        lowered = raw.lower()
        if "://" not in parse_target and ("youtube.com" in lowered or "youtu.be" in lowered):
            parse_target = f"https://{parse_target}"

        parsed = urlparse(parse_target)
        host = parsed.netloc.lower()
        parts = [part for part in parsed.path.split("/") if part]

        if "youtube.com" in host:
            if not parts:
                return None
            first = parts[0]
            if first.startswith("@"):
                handle = first[1:].strip()
                return {"handle": handle} if handle else None
            if first == "channel" and len(parts) >= 2:
                channel_id = parts[1].strip()
                return {"channelId": channel_id} if channel_id else None
            if first in {"c", "user"} and len(parts) >= 2:
                handle = parts[1].lstrip("@").strip()
                return {"handle": handle} if handle else None
            return None

        # Plain text fallback (no slashes/spaces) -> treat as handle.
        if "/" not in raw and " " not in raw and not re.fullmatch(r"[A-Za-z0-9_-]{11}", raw):
            handle = raw.lstrip("@").strip()
            return {"handle": handle} if handle else None
        return None

    def _looks_like_youtube_video(self, value: str) -> bool:
        raw = (value or "").strip()
        if not raw:
            return False
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", raw):
            return True

        parse_target = raw
        lowered = raw.lower()
        if "://" not in parse_target and ("youtube.com" in lowered or "youtu.be" in lowered):
            parse_target = f"https://{parse_target}"

        parsed = urlparse(parse_target)
        host = parsed.netloc.lower()
        parts = [part for part in parsed.path.split("/") if part]

        if "youtu.be" in host and len(parts) >= 1 and len(parts[0]) == 11:
            return True
        if "youtube.com" in host:
            if parsed.path == "/watch":
                return True
            if len(parts) >= 2 and parts[0] == "shorts":
                return True
        return False

    def _extract_channel_lookup_from_video_payload(self, payload: Dict[str, Any]) -> Optional[Dict[str, str]]:
        if not isinstance(payload, dict):
            return None

        def _pick_channel_id(container: Dict[str, Any]) -> Optional[str]:
            for key in (
                "channelId",
                "channel_id",
                "ownerChannelId",
                "owner_channel_id",
                "authorChannelId",
                "author_channel_id",
            ):
                value = container.get(key)
                if isinstance(value, str):
                    candidate = value.strip()
                    if candidate.startswith("UC") and len(candidate) >= 22:
                        return candidate
            return None

        def _pick_handle(container: Dict[str, Any]) -> Optional[str]:
            for key in ("channelHandle", "channel_handle", "handle", "username", "author"):
                value = container.get(key)
                if isinstance(value, str):
                    candidate = value.strip().lstrip("@")
                    if candidate and " " not in candidate and "/" not in candidate:
                        return candidate
            return None

        for key in ("channelUrl", "channel_url", "authorUrl", "author_url", "url"):
            value = payload.get(key)
            if isinstance(value, str):
                parsed = self._extract_channel_lookup_from_input(value)
                if parsed:
                    return parsed

        containers: list[Dict[str, Any]] = [payload]
        for key in ("data", "channel", "owner", "author"):
            value = payload.get(key)
            if isinstance(value, dict):
                containers.append(value)

        for container in containers:
            channel_id = _pick_channel_id(container)
            if channel_id:
                return {"channelId": channel_id}

        for container in containers:
            handle = _pick_handle(container)
            if handle:
                return {"handle": handle}

        return None

    def _resolve_channel_lookup_from_video_url(self, video_url: str) -> Optional[Dict[str, str]]:
        candidate_url = (video_url or "").strip()
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate_url):
            candidate_url = f"https://www.youtube.com/watch?v={candidate_url}"
        elif "://" not in candidate_url and ("youtube.com" in candidate_url.lower() or "youtu.be" in candidate_url.lower()):
            candidate_url = f"https://{candidate_url}"

        payload = self._get_json("youtube/video", {"url": candidate_url})
        if not payload:
            return None
        return self._extract_channel_lookup_from_video_payload(payload)

    def get_channel_videos(self, channel_url_or_handle: str, sort: str = "latest") -> Optional[Dict]:
        """
        Retrieves a list of videos from a YouTube channel.
        Accepts handle/channelId/channel URL and also a YouTube video URL
        (resolved to channelId/handle via the video endpoint).
        """
        params = {"sort": sort}
        lookup = self._extract_channel_lookup_from_input(channel_url_or_handle)
        if not lookup and self._looks_like_youtube_video(channel_url_or_handle):
            lookup = self._resolve_channel_lookup_from_video_url(channel_url_or_handle)

        if not lookup:
            logger.error(
                "Could not resolve YouTube channel identifier from input: %s",
                (channel_url_or_handle or "").strip(),
            )
            return None

        params.update(lookup)
        return self._get_json("youtube/channel-videos", params)

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
