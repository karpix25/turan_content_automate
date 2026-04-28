import re
from urllib.parse import urlparse, parse_qs

def _extract_youtube_video_id(url: str) -> str | None:
    raw = (url or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", raw):
        return raw

    parsed = urlparse(raw)
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

    return None

def _normalize_external_url(value: str) -> str:
    url = (value or "").strip().strip("<>()[]{}\"'.,;")
    if not url:
        return url
    if _extract_youtube_video_id(url):
        return url
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    return url

def _is_youtube_shorts_url(url: str) -> bool:
    raw = (url or "").strip()
    if not raw or re.fullmatch(r"[A-Za-z0-9_-]{11}", raw):
        return False

    parsed = urlparse(raw)
    host = parsed.netloc.lower()
    path_parts = [part for part in parsed.path.split("/") if part]
    return "youtube.com" in host and len(path_parts) >= 2 and path_parts[0] == "shorts"


def _validate_youtube_url_or_raise(url: str) -> None:
    if _extract_youtube_video_id(url) is None:
        raise Exception("Invalid YouTube URL (expected 11-char video id)")


def _build_youtube_watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _build_youtube_download_headers(watch_url: str) -> dict[str, str]:
    return {
        "Origin": "https://www.youtube.com",
        "Referer": watch_url,
    }
