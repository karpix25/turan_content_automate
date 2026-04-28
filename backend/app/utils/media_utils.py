import os
def _estimate_script_minutes(text: str, words_per_minute: int | None = None) -> float:
    from ..worker import llm, AVATAR_SCRIPT_WPM
    if words_per_minute is None:
        words_per_minute = AVATAR_SCRIPT_WPM
    words = llm.estimate_word_count(text)
    if words_per_minute <= 0:
        return 0.0
    return round(words / words_per_minute, 1)


def _resolve_media_file_path(path: str | None, media_kind: str) -> str | None:
    value = (path or "").strip()
    if not value:
        return None
    if os.path.isfile(value):
        return value

    normalized = value.lstrip("./")
    base_name = os.path.basename(normalized)
    candidates = [
        os.path.join("/app", normalized),
        os.path.join("/app/database/media", media_kind, base_name),
        os.path.join("/app/database/media", base_name),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def _resolve_local_input_video_path(path: str | None) -> str | None:
    value = (path or "").strip()
    if not value:
        return None
    if os.path.isfile(value):
        return value

    normalized = value.lstrip("./")
    base_name = os.path.basename(normalized)
    test_inputs_dir = (os.getenv("TEST_VIDEO_INPUT_DIR") or "/app/database/media/test-input").strip()
    candidates = [
        os.path.join("/app", normalized),
        os.path.join(test_inputs_dir, base_name),
        os.path.join("/app/database/media/test-input", base_name),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None
