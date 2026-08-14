FORMAT_LABELS = {
    "avatar_heygen": "ИИ-аватар",
    "avatar_horizontal": "ИИ-аватар горизонтальный",
    "avatar_vertical": "ИИ-аватар вертикальный",
    "avatar_youtube": "ИИ-аватар YouTube",
    "avatar_instagram": "ИИ-аватар Reels",
    "avatar_instagram_post_5s": "5 секунд",
    "avatar_shorts": "ИИ-аватар Shorts",
    "avatar_tiktok": "ИИ-аватар TikTok",
    "infographic_reels": "Инфографика 5 секунд",
    "local_upload": "Локальное видео",
    "vizard": "Vizard",
}

EXTERNAL_VIDEO_LABELS = {
    "instagram": "Чужое видео + плашка (Instagram)",
    "youtube": "Чужое видео + плашка (YouTube)",
    "tiktok": "Чужое видео + плашка (TikTok)",
}


def get_task_format_label(task_or_type) -> str:
    task_type = (getattr(task_or_type, "type", task_or_type) or "").strip()
    if task_type in EXTERNAL_VIDEO_LABELS:
        if getattr(task_or_type, "vizard_project_id", None):
            return "Vizard"
        return EXTERNAL_VIDEO_LABELS[task_type]
    return FORMAT_LABELS.get(task_type, task_type or "Видео")
