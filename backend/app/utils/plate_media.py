import os


PLATE_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
PLATE_VIDEO_EXTENSIONS = {".mov", ".webm"}
PLATE_ALLOWED_EXTENSIONS = PLATE_IMAGE_EXTENSIONS | PLATE_VIDEO_EXTENSIONS


def get_plate_media_type(file_path: str | None) -> str:
    extension = os.path.splitext(file_path or "")[1].lower()
    if extension in PLATE_VIDEO_EXTENSIONS:
        return "video"
    return "image"


def is_plate_video(file_path: str | None) -> bool:
    return get_plate_media_type(file_path) == "video"
