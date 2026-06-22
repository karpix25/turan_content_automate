import os
from typing import Final

from fastapi import HTTPException, UploadFile


DEFAULT_UPLOAD_MAX_BYTES: Final[int] = 1024 * 1024 * 1024
UPLOAD_CHUNK_SIZE: Final[int] = 1024 * 1024


def get_upload_max_bytes() -> int:
    raw_value = (os.getenv("ASSET_UPLOAD_MAX_BYTES") or "").strip()
    if not raw_value:
        return DEFAULT_UPLOAD_MAX_BYTES
    try:
        return max(1, int(raw_value))
    except ValueError:
        return DEFAULT_UPLOAD_MAX_BYTES


def format_file_size(bytes_count: int) -> str:
    value = float(bytes_count)
    for unit in ("Б", "КБ", "МБ"):
        if value < 1024:
            return f"{value:.0f} {unit}"
        value /= 1024
    return f"{value:.1f} ГБ"


async def save_upload_file_stream(file: UploadFile, target_path: str, *, max_bytes: int | None = None) -> int:
    limit = max_bytes or get_upload_max_bytes()
    bytes_written = 0
    try:
        with open(target_path, "wb") as target:
            while True:
                chunk = await file.read(UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > limit:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Файл слишком большой. Максимум: {format_file_size(limit)}.",
                    )
                target.write(chunk)
    except Exception:
        if os.path.exists(target_path):
            try:
                os.remove(target_path)
            except OSError:
                pass
        raise
    finally:
        await file.close()
    return bytes_written
