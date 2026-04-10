import glob
import logging
import os
from typing import Optional

from yt_dlp import YoutubeDL

logger = logging.getLogger(__name__)


class YtDlpDownloader:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        self.cookies_file = (os.getenv("YTDLP_COOKIES_FILE", "") or "").strip()
        self.player_clients = [
            item.strip()
            for item in (os.getenv("YTDLP_PLAYER_CLIENTS", "android,web") or "").split(",")
            if item.strip()
        ]

    def _find_downloaded_file(self, prefix: str) -> Optional[str]:
        candidates = [
            path for path in glob.glob(os.path.join(self.output_dir, f"{prefix}.*"))
            if os.path.isfile(path) and not path.endswith((".part", ".ytdl"))
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda path: os.path.getmtime(path), reverse=True)
        return candidates[0]

    def download_youtube(self, source_url: str, filename_prefix: str) -> Optional[str]:
        output_template = os.path.join(self.output_dir, f"{filename_prefix}.%(ext)s")
        options = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "outtmpl": output_template,
            "merge_output_format": "mp4",
            "format": (
                "bestvideo[ext=mp4][vcodec*=avc1]+bestaudio[ext=m4a]/"
                "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
                "bestvideo+bestaudio/"
                "best[ext=mp4]/best"
            ),
            "extractor_args": {
                "youtube": {
                    "player_client": self.player_clients or ["android", "web"],
                }
            },
        }
        if self.cookies_file:
            if os.path.isfile(self.cookies_file):
                options["cookiefile"] = self.cookies_file
                logger.info("yt-dlp will use cookies file %s", self.cookies_file)
            else:
                logger.warning("YTDLP_COOKIES_FILE is set but file is missing: %s", self.cookies_file)
        try:
            with YoutubeDL(options) as ydl:
                ydl.extract_info(source_url, download=True)
            downloaded = self._find_downloaded_file(filename_prefix)
            if downloaded:
                logger.info("Downloaded YouTube media via yt-dlp to %s", downloaded)
                return downloaded
            logger.error("yt-dlp finished but output file was not found for prefix %s", filename_prefix)
            return None
        except Exception as e:
            logger.error("yt-dlp failed for %s: %s", source_url, e)
            return None
