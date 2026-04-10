import logging
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

import httpx

logger = logging.getLogger(__name__)


class RapidAPIYoutubeClient:
    BASE_URL = "https://youtube-media-downloader.p.rapidapi.com"
    PREFERRED_WIDTH = 1080
    PREFERRED_HEIGHT = 1920

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

    def _as_int(self, value: Any) -> Optional[int]:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            digits = "".join(ch for ch in value if ch.isdigit())
            if digits:
                try:
                    return int(digits)
                except ValueError:
                    return None
        return None

    def _extract_candidate_url(self, item: Dict[str, Any]) -> Optional[str]:
        url = (
            item.get("url")
            or item.get("download_url")
            or item.get("downloadUrl")
            or item.get("video_url")
            or item.get("videoUrl")
        )
        if isinstance(url, str) and self._is_direct_media_url(url):
            return url
        return None

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
            score += 20
        if "video/mp4" in mime:
            score += 60
        elif "video/" in mime:
            score += 30
        if urlparse(url).path.lower().endswith(".mp4"):
            score += 40

        width = self._as_int(item.get("width"))
        height = self._as_int(item.get("height"))
        if width and height:
            if height >= width:
                score += 2000
            if width == self.PREFERRED_WIDTH and height == self.PREFERRED_HEIGHT:
                score += 10000
            else:
                score += max(0, 5000 - abs(width - self.PREFERRED_WIDTH) - abs(height - self.PREFERRED_HEIGHT))
            score += min(width, self.PREFERRED_WIDTH)
            score += min(height, self.PREFERRED_HEIGHT)

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

    def _score_progressive_candidate(self, item: Dict[str, Any], url: str) -> int:
        score = self._score_candidate(item, url)
        if item.get("hasAudio") is True:
            score += 5000
        else:
            score -= 5000
        return score

    def _score_audio_candidate(self, item: Dict[str, Any], url: str) -> int:
        score = 0

        mime = str(
            item.get("mimeType")
            or item.get("mime_type")
            or item.get("contentType")
            or item.get("type")
            or ""
        ).lower()
        xtags = str(item.get("xtags") or "").lower()
        extension = str(item.get("extension") or "").lower()

        if "audio/mp4" in mime:
            score += 4000
        elif "audio/" in mime:
            score += 2000

        if extension in {"m4a", "mp4"}:
            score += 600
        elif extension in {"weba", "webm"}:
            score += 200

        if "acont=original" in xtags:
            score += 2000
        if "lang=ru" in xtags:
            score += 1000
        if item.get("isDrc") is False:
            score += 300
        if item.get("isDrc") is True or "drc=1" in xtags:
            score -= 500

        size = self._as_int(item.get("size"))
        if size:
            score += min(size // 1000, 1500)

        if str(item.get("itag") or "") == "140":
            score += 500

        return score

    def _pick_best_stream_item(self, items: Any, score_fn) -> Optional[Dict[str, Any]]:
        if not isinstance(items, list):
            return None

        best_item = None
        best_score = -1
        for item in items:
            if not isinstance(item, dict):
                continue
            url = self._extract_candidate_url(item)
            if not url:
                continue
            score = score_fn(item, url)
            if score > best_score:
                best_score = score
                best_item = item
        return best_item

    def _extract_stream_info(self, item: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not isinstance(item, dict):
            return None

        url = self._extract_candidate_url(item)
        if not url:
            return None

        return {
            "url": url,
            "itag": item.get("itag"),
            "mime_type": item.get("mimeType") or item.get("mime_type") or item.get("contentType"),
            "extension": item.get("extension"),
            "quality": item.get("quality") or item.get("qualityLabel"),
            "width": item.get("width"),
            "height": item.get("height"),
            "has_audio": item.get("hasAudio"),
            "is_drc": item.get("isDrc"),
            "xtags": item.get("xtags"),
            "size": item.get("size"),
            "size_text": item.get("sizeText"),
        }

    def _extract_download_url(self, data: Dict[str, Any]) -> Optional[str]:
        videos = data.get("videos")
        if isinstance(videos, dict):
            items = videos.get("items")
            if isinstance(items, list):
                best_url = None
                best_score = -1
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    url = self._extract_candidate_url(item)
                    if not url:
                        continue
                    score = self._score_candidate(item, url)
                    if score > best_score:
                        best_score = score
                        best_url = url
                if best_url:
                    return best_url

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
            url = self._extract_candidate_url(item)
            if not url:
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

        videos = data.get("videos") if isinstance(data.get("videos"), dict) else {}
        audios = data.get("audios") if isinstance(data.get("audios"), dict) else {}

        best_video_item = self._pick_best_stream_item(videos.get("items"), self._score_candidate)
        best_audio_item = self._pick_best_stream_item(audios.get("items"), self._score_audio_candidate)
        best_progressive_item = self._pick_best_stream_item(videos.get("items"), self._score_progressive_candidate)

        best_video = self._extract_stream_info(best_video_item)
        best_audio = self._extract_stream_info(best_audio_item)
        best_progressive = self._extract_stream_info(best_progressive_item)
        download_url = (
            (best_progressive or {}).get("url")
            or self._extract_download_url(data)
        )

        return {
            "download_url": download_url,
            "video_download_url": (best_video or {}).get("url"),
            "audio_download_url": (best_audio or {}).get("url"),
            "progressive_download_url": (best_progressive or {}).get("url"),
            "video_stream": best_video,
            "audio_stream": best_audio,
            "progressive_stream": best_progressive,
            "video_id": data.get("id") or video_id,
            "title": data.get("title"),
            "error": None if (best_video or best_progressive) else "No direct media URL found in RapidAPI response",
            "raw": data,
        }
