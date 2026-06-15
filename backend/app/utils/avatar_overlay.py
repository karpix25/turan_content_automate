import json
import logging
import os
import random
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)


def _run_json(cmd: list[str]) -> dict:
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout or "{}")


def _probe_video(path: str) -> dict:
    payload = _run_json(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            path,
        ]
    )
    for stream in payload.get("streams") or []:
        if stream.get("codec_type") == "video":
            return {"format": payload.get("format") or {}, "video": stream}
    return {"format": payload.get("format") or {}, "video": None}


def _duration(path: str) -> float:
    try:
        probe = _probe_video(path)
    except Exception:
        return 0.0
    return float((probe.get("format") or {}).get("duration") or 0.0)


def _safe_int(value: int | None, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value if value is not None else default)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _plan_overlay_schedule(
    *,
    source_duration: float,
    insert_paths: list[str],
    start_percent: int,
    end_percent: int,
    clips_count: int,
    max_insert_seconds: float,
    seed: Optional[int],
) -> list[tuple[str, float, float]]:
    window_start = source_duration * (start_percent / 100.0)
    window_end = source_duration * (end_percent / 100.0)
    window_length = max(0.0, window_end - window_start)
    if window_length <= 0.2 or clips_count <= 0:
        return []

    candidates: list[tuple[str, float]] = []
    for path in insert_paths:
        if not path or not os.path.isfile(path):
            continue
        duration = _duration(path)
        if duration <= 0.2:
            continue
        bounded = min(duration, max_insert_seconds) if max_insert_seconds > 0 else duration
        candidates.append((path, max(0.2, bounded)))

    if not candidates:
        return []

    rnd = random.Random(seed if seed is not None else random.randint(1, 9999999))
    rnd.shuffle(candidates)
    selected = candidates[: min(max(1, clips_count), len(candidates))]
    total_duration = sum(item[1] for item in selected)
    if total_duration > window_length * 0.95:
        per_clip = max(0.2, (window_length * 0.95) / max(1, len(selected)))
        selected = [(path, min(duration, per_clip)) for path, duration in selected]

    total_duration = sum(item[1] for item in selected)
    slack = max(0.0, window_length - total_duration)
    if len(selected) == 1:
        path, duration = selected[0]
        return [(path, window_start + slack / 2.0, duration)]

    gap = slack / max(1, len(selected) - 1)
    cursor = window_start
    schedule: list[tuple[str, float, float]] = []
    for path, duration in selected:
        schedule.append((path, cursor, duration))
        cursor += duration + gap
    return schedule


def apply_transparent_avatar_overlays(
    *,
    input_path: str,
    overlay_paths: list[str],
    output_path: str,
    start_percent: int,
    end_percent: int,
    clips_count: int,
    x_percent: int,
    y_percent: int,
    size_percent: int,
    opacity_percent: int,
    seed: Optional[int] = None,
    max_insert_seconds: float = 0.0,
    timeout_seconds: Optional[int] = None,
) -> tuple[str | None, dict]:
    meta = {
        "status": "skipped",
        "reason": None,
        "requested_count": clips_count,
        "applied_count": 0,
        "window_percent": [start_percent, end_percent],
        "position": {
            "x_percent": x_percent,
            "y_percent": y_percent,
            "size_percent": size_percent,
            "opacity_percent": opacity_percent,
        },
        "overlays": [],
    }

    if clips_count <= 0:
        meta["reason"] = "clips_count_is_zero"
        return None, meta

    try:
        source_probe = _probe_video(input_path)
    except Exception as exc:
        meta["reason"] = "source_probe_failed"
        meta["error"] = str(exc)
        return None, meta

    source_video = source_probe.get("video")
    source_duration = float((source_probe.get("format") or {}).get("duration") or 0.0)
    if not source_video or source_duration <= 0.2:
        meta["reason"] = "source_video_unavailable"
        return None, meta
    source_height = int(source_video.get("height") or 0)
    if source_height <= 0:
        meta["reason"] = "source_video_height_unavailable"
        return None, meta

    normalized_start = _safe_int(start_percent, 50, 0, 99)
    normalized_end = _safe_int(end_percent, 95, 1, 100)
    if normalized_end <= normalized_start:
        normalized_end = min(100, normalized_start + 1)

    schedule = _plan_overlay_schedule(
        source_duration=source_duration,
        insert_paths=overlay_paths,
        start_percent=normalized_start,
        end_percent=normalized_end,
        clips_count=clips_count,
        max_insert_seconds=max_insert_seconds,
        seed=seed,
    )
    if not schedule:
        meta["reason"] = "no_overlay_schedule"
        return None, meta

    x = _safe_int(x_percent, 50, 0, 100)
    y = _safe_int(y_percent, 100, 0, 100)
    size = _safe_int(size_percent, 45, 5, 100)
    opacity = _safe_int(opacity_percent, 100, 0, 100)
    opacity_expr = round(opacity / 100.0, 4)
    overlay_height = max(2, int(source_height * size / 100))
    if overlay_height % 2:
        overlay_height -= 1
    x_expr = f"(main_w-overlay_w)*{x}/100"
    y_expr = f"(main_h-overlay_h)*{y}/100"

    cmd = ["ffmpeg", "-y", "-i", input_path]
    filter_parts = ["[0:v]format=yuv420p[base0]"]
    current_label = "base0"
    for index, (path, start_sec, duration_sec) in enumerate(schedule, start=1):
        cmd.extend(["-stream_loop", "-1", "-i", path])
        overlay_label = f"ov{index}"
        output_label = f"base{index}"
        safe_start = max(0.0, start_sec)
        safe_end = min(source_duration, safe_start + duration_sec)
        filter_parts.append(
            f"[{index}:v]trim=duration={duration_sec:.3f},setpts=PTS-STARTPTS,"
            f"scale=-2:{overlay_height},format=rgba,"
            f"colorchannelmixer=aa={opacity_expr}[{overlay_label}]"
        )
        filter_parts.append(
            f"[{current_label}][{overlay_label}]overlay="
            f"x='{x_expr}':y='{y_expr}':enable='between(t,{safe_start:.3f},{safe_end:.3f})':"
            f"eof_action=pass:repeatlast=0:format=auto[{output_label}]"
        )
        current_label = output_label
        meta["overlays"].append(
            {
                "source_path": path,
                "start_sec": round(safe_start, 3),
                "duration_sec": round(max(0.0, safe_end - safe_start), 3),
            }
        )

    filter_complex = ";".join(filter_parts)
    cmd.extend(
        [
            "-filter_complex",
            filter_complex,
            "-map",
            f"[{current_label}]",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            os.getenv("FFMPEG_X264_PRESET", "veryfast"),
            "-crf",
            os.getenv("FFMPEG_X264_CRF", "21"),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            output_path,
        ]
    )

    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        meta["status"] = "failed"
        meta["reason"] = "ffmpeg_timeout"
        meta["error"] = str(exc)
        return None, meta
    except subprocess.CalledProcessError as exc:
        logger.error("Avatar overlay ffmpeg failed: %s", exc.stderr[-4000:] if exc.stderr else exc)
        meta["status"] = "failed"
        meta["reason"] = "ffmpeg_failed"
        meta["error"] = (exc.stderr or str(exc))[-4000:]
        return None, meta

    if not os.path.isfile(output_path) or os.path.getsize(output_path) <= 0:
        meta["status"] = "failed"
        meta["reason"] = "output_missing"
        return None, meta

    meta["status"] = "applied"
    meta["applied_count"] = len(meta["overlays"])
    meta["output_path"] = output_path
    meta["position"] = {
        "x_percent": x,
        "y_percent": y,
        "size_percent": size,
        "opacity_percent": opacity,
    }
    return output_path, meta
