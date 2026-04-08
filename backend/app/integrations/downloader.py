import yt_dlp
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class Downloader:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

    def download_video(self, url: str, filename: str) -> Optional[str]:
        """
        Downloads a video (YouTube/Shorts) using yt-dlp.
        Returns the absolute path to the downloaded file.
        """
        output_path = os.path.join(self.output_dir, f"{filename}.%(ext)s")
        
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': output_path,
            'quiet': True,
            'no_warnings': True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                downloaded_file = ydl.prepare_filename(info)
                logger.info(f"Downloaded video to {downloaded_file}")
                return downloaded_file
        except Exception as e:
            logger.error(f"Failed to download video with yt-dlp: {e}")
            return None
