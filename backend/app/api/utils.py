import os
import re
import logging
import datetime
from urllib.parse import urlparse, parse_qs
from fastapi import HTTPException

def _parse_csv_env(value: str | None) -> list[str]:
    raw = (value or "").strip()
    if not raw:
        return []
    parts = re.split(r"[,\n; ]+", raw)
    return [item.strip() for item in parts if item.strip()]

def normalize_utc_naive(dt: datetime.datetime | None) -> datetime.datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return dt

def get_allowed_cors_origins() -> list[str]:
    return _parse_csv_env(os.getenv("CORS_ALLOWED_ORIGINS"))

def get_telegram_admin_ids() -> set[str]:
    return {item for item in _parse_csv_env(os.getenv("TELEGRAM_ADMIN_IDS")) if item.isdigit()}

def resolve_output_file_path(output_path: str) -> str | None:
    value = (output_path or "").strip()
    if not value:
        return None

    candidates: list[str] = []
    if os.path.isabs(value):
        candidates.append(value)
    else:
        normalized = value.lstrip("./")
        candidates.extend(
            [
                os.path.abspath(value),
                os.path.join("/app", normalized),
                os.path.join("/app/database/media/output", os.path.basename(normalized)),
            ]
        )

    seen: set[str] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        if os.path.isfile(path):
            return path
    return None

def extract_vizard_project_id(url: str) -> str | None:
    raw = (url or "").strip()
    if raw.startswith("https://") and raw[8:].isdigit():
        raw = raw[8:]
    elif raw.startswith("http://") and raw[7:].isdigit():
        raw = raw[7:]

    match = re.search(r"vizard\.ai/(?:project|dashboard/editor)/(\d+)", raw, re.IGNORECASE)
    if match:
        return match.group(1)
    if raw.isdigit():
        return raw
    return None

def extract_youtube_video_id(url: str) -> str | None:
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

def normalize_youtube_url(url: str) -> str:
    raw = (url or "").strip()
    video_id = extract_youtube_video_id(raw)
    if not video_id:
        return raw

    if re.fullmatch(r"[A-Za-z0-9_-]{11}", raw):
        return f"https://www.youtube.com/watch?v={video_id}"

    parsed = urlparse(raw)
    host = parsed.netloc.lower()
    path_parts = [part for part in parsed.path.split("/") if part]

    if "youtube.com" in host and len(path_parts) >= 2 and path_parts[0] == "shorts":
        return f"https://www.youtube.com/shorts/{video_id}"

    return f"https://www.youtube.com/watch?v={video_id}"

def validate_youtube_url(url: str) -> None:
    if extract_youtube_video_id(url) is None:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

def normalize_source_url(value: str, task_type: str | None = None) -> str:
    url = (value or "").strip().strip("<>()[]{}\"'.,;")
    if not url:
        raise HTTPException(status_code=400, detail="source_url is empty")
    
    t_type = (task_type or "").strip().lower()
    if url.startswith("notebooklm-script://"):
        return url
    if t_type in {"avatar_heygen", "avatar_horizontal", "avatar_vertical", "avatar_youtube"}:
        # Allow reusing already generated HeyGen videos by id without forcing URL normalization.
        # Supported forms:
        # - heygen:<video_id>
        # - <video_id> (32 hex chars)
        if url.lower().startswith("heygen:") or re.fullmatch(r"[0-9a-fA-F]{32}", url):
            return url
    if t_type == "youtube":
        return normalize_youtube_url(url)
    if t_type == "vizard":
        v_id = extract_vizard_project_id(url)
        if v_id:
            return v_id
            
    if not url.startswith(("http://", "https://")) and not url.isdigit():
        url = f"https://{url}"
    return url

def _get_channel_videos_list(channel_data: dict) -> list[dict]:
    if not isinstance(channel_data, dict):
        return []

    candidates: list = []
    for key in ("videos", "items", "results", "data"):
        value = channel_data.get(key)
        if isinstance(value, list):
            candidates.append(value)
        elif isinstance(value, dict):
            for nested_key in ("videos", "items", "results"):
                nested_value = value.get(nested_key)
                if isinstance(nested_value, list):
                    candidates.append(nested_value)

    for candidate in candidates:
        if candidate and isinstance(candidate[0], dict):
            return candidate
    return []

def _extract_video_url_for_transcript(video: dict) -> str | None:
    if not isinstance(video, dict):
        return None

    def _from_id(value: object) -> str | None:
        if isinstance(value, str):
            candidate = value.strip()
            if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
                return f"https://www.youtube.com/watch?v={candidate}"
        return None

    id_keys = ("videoId", "video_id", "id", "yt_video_id", "youtube_video_id")
    for key in id_keys:
        url = _from_id(video.get(key))
        if url:
            return url

    nested_video = video.get("video")
    if isinstance(nested_video, dict):
        for key in id_keys:
            url = _from_id(nested_video.get(key))
            if url:
                return url

    url_keys = ("url", "video_url", "videoUrl", "link", "watch_url")
    for key in url_keys:
        value = video.get(key)
        if isinstance(value, str) and value.strip():
            return normalize_youtube_url(value.strip())

    if isinstance(nested_video, dict):
        for key in url_keys:
            value = nested_video.get(key)
            if isinstance(value, str) and value.strip():
                return normalize_youtube_url(value.strip())

    return None

def normalize_ending_platform(value: str | None) -> str:
    platform = (value or "").strip().lower()
    aliases = {
        "ig": "instagram",
        "insta": "instagram",
        "yt": "youtube",
        "you_tube": "youtube",
        "tt": "tiktok",
    }
    platform = aliases.get(platform, platform)
    if platform in {"instagram", "youtube", "tiktok", "universal"}:
        return platform
    raise HTTPException(status_code=400, detail="platform must be one of: instagram, youtube, tiktok, universal")

def parse_optional_account_id(value: str | None) -> int | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="account_id must be an integer")

def normalize_percent(value: int | None, *, field_name: str) -> int:
    if value is None:
        raise HTTPException(status_code=400, detail=f"{field_name} is required")
    if value < 0 or value > 100:
        raise HTTPException(status_code=400, detail=f"{field_name} must be between 0 and 100")
    return int(value)

def _build_safe_upload_filename(original_name: str | None, fallback_extension: str = ".mp4") -> str:
    base = os.path.basename((original_name or "").strip())
    if not base:
        base = f"upload{fallback_extension}"
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base)
    if "." not in base:
        base = f"{base}{fallback_extension}"
    return base
