import os
import logging
from typing import Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

class Downloader:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

    def _pick_extension(self, resolved_url: str, content_type: str) -> str:
        content_type_main = (content_type or "").split(";", 1)[0].strip().lower()
        by_type = {
            "video/mp4": ".mp4",
            "video/quicktime": ".mov",
            "video/webm": ".webm",
            "video/x-matroska": ".mkv",
            "video/mpeg": ".mpeg",
        }
        if content_type_main in by_type:
            return by_type[content_type_main]

        parsed = urlparse(resolved_url)
        ext = os.path.splitext(parsed.path)[1].lower()
        if ext in {".mp4", ".mov", ".webm", ".mkv", ".mpeg", ".m4v"}:
            return ext
        return ".mp4"

    def download_video(self, url: str, filename: str) -> Optional[str]:
        """
        Downloads a video from a direct media URL (HTTP/HTTPS) and
        returns the absolute path to the downloaded file.
        """
        source_url = (url or "").strip()
        if not source_url.startswith(("http://", "https://")):
            logger.error("Unsupported download URL: %s", source_url)
            return None

        temp_path = os.path.join(self.output_dir, f"{filename}.part")
        final_path = None

        try:
            timeout = httpx.Timeout(connect=15.0, read=120.0, write=30.0, pool=30.0)
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
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
            logger.info("Downloaded video to %s", final_path)
            return final_path
        except httpx.HTTPStatusError as e:
            logger.error(
                "Failed to download video: HTTP %s for %s",
                e.response.status_code,
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
