import base64
import mimetypes
import os


DEFAULT_MAX_IMAGE_DATA_URL_BYTES = 4 * 1024 * 1024


def image_file_to_data_url(path: str | None, *, max_bytes: int = DEFAULT_MAX_IMAGE_DATA_URL_BYTES) -> str | None:
    if not path or not os.path.isfile(path):
        return None
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    if size <= 0 or size > max_bytes:
        return None

    mime_type = mimetypes.guess_type(path)[0] or "image/jpeg"
    if not mime_type.startswith("image/"):
        return None

    try:
        with open(path, "rb") as fh:
            encoded = base64.b64encode(fh.read()).decode("ascii")
    except OSError:
        return None
    return f"data:{mime_type};base64,{encoded}"
