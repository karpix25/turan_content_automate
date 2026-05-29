import os
import logging
from typing import Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

class Downloader:
    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    )

    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

    def _pick_extension(self, resolved_url: str, content_type: str) -> str:
        content_type_main = (content_type or "").split(";", 1)[0].strip().lower()
        by_type = {
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "video/mp4": ".mp4",
            "video/quicktime": ".mov",
            "video/webm": ".webm",
            "video/x-matroska": ".mkv",
            "video/mpeg": ".mpeg",
            "audio/mp4": ".m4a",
            "audio/webm": ".weba",
            "audio/mpeg": ".mp3",
        }
        if content_type_main in by_type:
            return by_type[content_type_main]

        parsed = urlparse(resolved_url)
        ext = os.path.splitext(parsed.path)[1].lower()
        if ext in {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".webm", ".mkv", ".mpeg", ".m4v", ".m4a", ".weba", ".mp3"}:
            return ext
        return ".mp4"

    def _build_headers(self, source_url: str, extra_headers: Optional[dict[str, str]] = None) -> dict[str, str]:
        headers = {
            "User-Agent": self.DEFAULT_USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
        }
        host = urlparse(source_url).netloc.lower()
        if "googlevideo.com" in host or "youtube.com" in host:
            headers.update(
                {
                    "Origin": "https://www.youtube.com",
                    "Referer": "https://www.youtube.com/",
                }
            )
        if extra_headers:
            headers.update({key: value for key, value in extra_headers.items() if value})
        return headers

    def download_media(self, url: str, filename: str, headers: Optional[dict[str, str]] = None) -> Optional[str]:
        """
        Downloads media from a direct URL (HTTP/HTTPS) and
        returns the absolute path to the downloaded file.
        """
        source_url = (url or "").strip()
        if not source_url.startswith(("http://", "https://")):
            logger.error("Unsupported download URL: %s", source_url)
            return None

        temp_path = os.path.join(self.output_dir, f"{filename}.part")
        final_path = None
        host = urlparse(source_url).netloc.lower()

        for attempt in range(2):
            request_headers = self._build_headers(source_url, headers)
            if attempt == 1 and "googlevideo.com" in host:
                request_headers["Range"] = "bytes=0-"

            try:
                timeout = httpx.Timeout(connect=15.0, read=120.0, write=30.0, pool=30.0)
                with httpx.Client(timeout=timeout, follow_redirects=True, headers=request_headers) as client:
                    with client.stream("GET", source_url) as response:
                        response.raise_for_status()
                        content_type = response.headers.get("content-type", "")
                        resolved_url = str(response.url)
                        extension = self._pick_extension(resolved_url, content_type)
                        final_path = os.path.join(self.output_dir, f"{filename}{extension}")

                        bytes_written = 0
                        with open(temp_path, "wb") as output_file:
                            for chunk in response.iter_bytes(chunk_size=1024 * 512):
                                if not chunk:
                                    continue
                                output_file.write(chunk)
                                bytes_written += len(chunk)

                        if bytes_written == 0:
                            raise ValueError("Downloaded file is empty")

                os.replace(temp_path, final_path)
                logger.info("Downloaded media to %s", final_path)
                return final_path
            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                if attempt == 0 and status_code in {403, 429, 500, 502, 503, 504}:
                    logger.warning(
                        "Retrying media download after HTTP %s for %s",
                        status_code,
                        source_url,
                    )
                    continue
                logger.error(
                    "Failed to download video: HTTP %s for %s",
                    status_code,
                    source_url,
                )
                return None
            except Exception as e:
                logger.error("Failed to download video from %s: %s", source_url, e)
                return None
            finally:
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass

        return None

    def download_video(self, url: str, filename: str, headers: Optional[dict[str, str]] = None) -> Optional[str]:
        return self.download_media(url=url, filename=filename, headers=headers)
