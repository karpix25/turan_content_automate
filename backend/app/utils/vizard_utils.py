import re
import asyncio
import logging
import os
import time
from typing import List

from .. import models
from ..telegram_progress import update_task_status_message


def _extract_vizard_project_id(url_or_id: str) -> str | None:
    raw = str(url_or_id).strip()
    # Remove accidental http(s) prefix if it was added to a pure numeric ID
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

def _extract_vizard_clip_title(clip: dict) -> str | None:
    if not isinstance(clip, dict):
        return None

    direct_keys = (
        "title",
        "headline",
        "headLine",
        "clipTitle",
        "videoTitle",
        "name",
    )
    for key in direct_keys:
        value = clip.get(key)
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                return normalized

    def find_nested_title(node) -> str | None:
        if isinstance(node, dict):
            for key, value in node.items():
                key_text = str(key).lower()
                if isinstance(value, str) and ("title" in key_text or "headline" in key_text):
                    normalized = value.strip()
                    if normalized:
                        return normalized
            for value in node.values():
                found = find_nested_title(value)
                if found:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = find_nested_title(item)
                if found:
                    return found
        return None

    # Fallback: search nested dictionaries/lists for title-like keys.
    for key, value in clip.items():
        key_text = str(key).lower()
        if not isinstance(value, str):
            continue
        if "title" in key_text or "headline" in key_text:
            normalized = value.strip()
            if normalized:
                return normalized
    return find_nested_title(clip)

def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default

def _vizard_message(data: dict | None) -> str:
    if not isinstance(data, dict):
        return "empty response"
    for key in ("errMsg", "msg", "message", "error"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    code = data.get("code")
    return f"code={code}" if code is not None else "unknown response"

def _download_vizard_project_clips(db, task: models.VideoTask, source_url: str, **create_kwargs) -> List[tuple[str, str | None]]:
    from ..worker import vizard, downloader
    logging.info(f"Task {task.id}: Processing vizard/youtube source: '{source_url}'")
    update_task_status_message(
        db,
        task,
        stage="Vizard",
        detail="Готовлю отправку видео в Vizard.",
    )
    
    # Check if we already have a project ID or if source_url is a Vizard link
    task_vizard_project_id = str(getattr(task, "vizard_project_id", "") or "").strip()
    existing_v_id = task_vizard_project_id or _extract_vizard_project_id(source_url)
    
    # If the task is explicitly of type 'vizard', we should NEVER try to create a new project
    # unless it's a YouTube URL that we chose to process with Vizard.
    # However, if it's a pure 'vizard' task, it usually means a project link was sent.
    is_vizard_project_link = (task.type == "vizard")
    
    if existing_v_id or is_vizard_project_link:
        p_id_str = existing_v_id or source_url
        if p_id_str.isdigit():
            p_id = int(p_id_str)
            logging.info(f"Task {task.id}: SUCCESS - Identified Vizard project ID {p_id}. Calling Retrieve Video Clips.")
        else:
            # Maybe it's a link that wasn't extracted? try extracting again
            p_id_str = _extract_vizard_project_id(p_id_str)
            if p_id_str and p_id_str.isdigit():
                p_id = int(p_id_str)
                logging.info(f"Task {task.id}: SUCCESS - Extracted Vizard project ID {p_id} from URL. Calling Retrieve Video Clips.")
            else:
                # If we still don't have a numeric ID but task was 'vizard', something is wrong
                if task.type == "vizard":
                    raise Exception(f"Task type is 'vizard' but could not find a numeric PROJECT ID in '{source_url}'. Please send a valid vizard.ai link.")
                
                logging.info(f"Task {task.id}: No numeric Vizard ID found in '{source_url}'. Proceeding to create new project.")
                p_id = asyncio.run(vizard.create_project(source_url, **create_kwargs))
    else:
        logging.info(f"Task {task.id}: Standard creation flow for: {source_url}")
        p_id = asyncio.run(vizard.create_project(source_url, **create_kwargs))

    if not p_id:
        raise Exception(f"Failed to resolve Vizard project ID for: {source_url}")

    task.vizard_project_id = p_id
    db.commit()

    update_task_status_message(
        db,
        task,
        stage="Vizard",
        detail=f"Видео отправлено в Vizard. Проект #{p_id}. Жду, пока сервис нарежет клипы.",
    )

    poll_interval = max(5, int(os.getenv("VIZARD_POLL_INTERVAL_SECONDS", "30")))
    max_attempts = max(1, int(os.getenv("VIZARD_POLL_MAX_ATTEMPTS", "60")))
    started_at = time.monotonic()
    clips = None
    last_poll_message = "no polling response yet"
    for attempt in range(1, max_attempts + 1):
        data = asyncio.run(vizard.query_project(p_id))
        if not isinstance(data, dict):
            last_poll_message = "Vizard did not return JSON"
        else:
            code = data.get("code")
            if code == 2000:
                videos = data.get("videos")
                if isinstance(videos, list) and videos:
                    clips = videos
                    break
                last_poll_message = "Vizard returned success, but clips are not ready yet"
            elif code == 1000:
                last_poll_message = _vizard_message(data) or "Vizard is still processing"
            else:
                message = _vizard_message(data)
                logging.error("Task %s: Vizard project %s failed while polling: %s", task.id, p_id, data)
                raise Exception(f"Vizard project #{p_id} failed: {message}")

        elapsed_minutes = int((time.monotonic() - started_at) // 60)
        update_task_status_message(
            db,
            task,
            stage="Vizard",
            detail=(
                f"Проект #{p_id} обрабатывается. Жду клипы: попытка {attempt}/{max_attempts}, "
                f"прошло ~{elapsed_minutes} мин."
            ),
        )
        logging.info(
            "Task %s: Vizard project %s still processing... (Attempt %s/%s). Last status: %s",
            task.id,
            p_id,
            attempt,
            max_attempts,
            last_poll_message,
        )
        if attempt < max_attempts:
            time.sleep(poll_interval)

    if not clips:
        raise Exception(f"Vizard conversion timed out or failed: {last_poll_message}")

    max_clips = _env_int("VIZARD_MAX_CLIPS_PER_TASK", 8)
    total_clips = len(clips)
    if max_clips > 0 and total_clips > max_clips:
        clips = clips[:max_clips]
        logging.warning(
            "Task %s: Vizard returned %s clips; limiting processing to first %s clips",
            task.id,
            total_clips,
            max_clips,
        )
        update_task_status_message(
            db,
            task,
            stage="Vizard",
            detail=f"Vizard вернул {total_clips} клипов. Беру первые {max_clips}, чтобы задача не зависла на часы.",
        )

    update_task_status_message(
        db,
        task,
        stage="Vizard",
        detail=f"Vizard подготовил клипы: {len(clips)}. Скачиваю результаты.",
    )

    input_videos: List[tuple[str, str | None]] = []
    for i, clip in enumerate(clips):
        url = clip.get("videoUrl")
        if not url:
            raise Exception(f"Vizard clip #{i} has no download URL")
        clip_title = _extract_vizard_clip_title(clip)
        update_task_status_message(
            db,
            task,
            stage="Vizard",
            detail=f"Скачиваю клип {i + 1}/{len(clips)} из проекта #{p_id}.",
        )
        local_file = downloader.download_video(url, f"vizard_{p_id}_{i}")
        if not local_file:
            raise Exception(f"Failed to download Vizard clip #{i}")
        input_videos.append((local_file, clip_title))
    return input_videos
