import os
import time
from urllib.parse import quote

import httpx


class YandexDiskClient:
    BASE_URL = "https://cloud-api.yandex.net/v1/disk"

    def __init__(self, token: str):
        self.token = (token or "").strip()
        self.timeout_seconds = float(os.getenv("YANDEX_DISK_TIMEOUT_SECONDS", "120"))
        self.upload_timeout_seconds = float(os.getenv("YANDEX_DISK_UPLOAD_TIMEOUT_SECONDS", "600"))
        self.upload_retries = max(0, int(os.getenv("YANDEX_DISK_UPLOAD_RETRIES", "2")))
        self.upload_retry_backoff_seconds = max(
            0.0,
            float(os.getenv("YANDEX_DISK_UPLOAD_RETRY_BACKOFF_SECONDS", "2")),
        )
        self.public_url_retries = max(0, int(os.getenv("YANDEX_DISK_PUBLIC_URL_RETRIES", "6")))
        self.public_url_retry_backoff_seconds = max(
            0.0,
            float(os.getenv("YANDEX_DISK_PUBLIC_URL_RETRY_BACKOFF_SECONDS", "1")),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.token)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"OAuth {self.token}"}

    def _normalize_disk_path(self, path: str) -> str:
        raw = (path or "").strip().replace("\\", "/")
        if not raw:
            return "disk:/"
        if raw.startswith("disk:/"):
            return raw
        if raw.startswith("disk:"):
            suffix = raw[len("disk:"):].lstrip("/")
            return f"disk:/{suffix}" if suffix else "disk:/"
        if raw.startswith("disk/"):
            suffix = raw[len("disk/"):].lstrip("/")
            return f"disk:/{suffix}" if suffix else "disk:/"
        if raw.startswith("/"):
            return f"disk:{raw}"
        return f"disk:/{raw.lstrip('/')}"

    def _request(self, method: str, endpoint: str, **kwargs) -> httpx.Response:
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.request(
                method=method,
                url=f"{self.BASE_URL}{endpoint}",
                headers=self._headers(),
                **kwargs,
            )
        return response

    def ensure_directory(self, directory_path: str) -> str:
        if not self.is_configured:
            raise RuntimeError("YANDEX_DISK_TOKEN is empty")

        normalized = self._normalize_disk_path(directory_path).rstrip("/")
        if normalized in {"disk:", "disk:/"}:
            return "disk:/"

        tail = normalized[len("disk:/"):].strip("/")
        current = "disk:/"
        for part in [item for item in tail.split("/") if item]:
            current = f"{current.rstrip('/')}/{part}"
            encoded = quote(current, safe=":/")
            response = self._request("PUT", f"/resources?path={encoded}")
            if response.status_code in {201, 409}:
                continue
            if response.status_code == 401:
                raise RuntimeError("Yandex.Disk authorization failed (401). Check YANDEX_DISK_TOKEN.")
            raise RuntimeError(
                f"Failed to create Yandex.Disk folder '{current}': "
                f"{response.status_code} {response.text[:300]}"
            )
        return normalized

    def upload_file(self, local_path: str, remote_path: str, overwrite: bool = True) -> str:
        if not self.is_configured:
            raise RuntimeError("YANDEX_DISK_TOKEN is empty")
        if not os.path.isfile(local_path):
            raise RuntimeError(f"Local file for Yandex.Disk upload not found: {local_path}")

        normalized_remote = self._normalize_disk_path(remote_path)
        encoded_path = quote(normalized_remote, safe=":/")
        encoded_overwrite = "true" if overwrite else "false"
        get_href_response = self._request(
            "GET",
            f"/resources/upload?path={encoded_path}&overwrite={encoded_overwrite}",
        )
        if get_href_response.status_code != 200:
            if get_href_response.status_code == 401:
                raise RuntimeError("Yandex.Disk authorization failed (401). Check YANDEX_DISK_TOKEN.")
            raise RuntimeError(
                f"Failed to get Yandex.Disk upload URL for '{normalized_remote}': "
                f"{get_href_response.status_code} {get_href_response.text[:300]}"
            )

        href = (get_href_response.json() or {}).get("href")
        if not href:
            raise RuntimeError(f"Yandex.Disk upload URL is missing for '{normalized_remote}'")

        upload_timeout = httpx.Timeout(
            connect=min(self.timeout_seconds, 30.0),
            read=self.upload_timeout_seconds,
            write=self.upload_timeout_seconds,
            pool=self.timeout_seconds,
        )
        last_timeout_error: Exception | None = None
        upload_response: httpx.Response | None = None
        for attempt in range(1, self.upload_retries + 2):
            try:
                with open(local_path, "rb") as fh, httpx.Client(timeout=upload_timeout) as client:
                    upload_response = client.put(href, content=fh)
                last_timeout_error = None
                break
            except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.ConnectTimeout) as exc:
                last_timeout_error = exc
                if attempt >= self.upload_retries + 1:
                    break
                time.sleep(self.upload_retry_backoff_seconds * attempt)

        if last_timeout_error is not None:
            raise RuntimeError(
                f"Yandex.Disk upload timed out for '{normalized_remote}' after {self.upload_retries + 1} attempts"
            ) from last_timeout_error
        if upload_response is None:
            raise RuntimeError(f"Yandex.Disk upload failed for '{normalized_remote}' with unknown transport state")

        if upload_response.status_code not in {201, 202}:
            raise RuntimeError(
                f"Failed to upload '{normalized_remote}' to Yandex.Disk: "
                f"{upload_response.status_code} {upload_response.text[:300]}"
            )
        return normalized_remote

    def publish_and_get_public_url(self, remote_path: str) -> str:
        if not self.is_configured:
            raise RuntimeError("YANDEX_DISK_TOKEN is empty")

        normalized_remote = self._normalize_disk_path(remote_path)
        encoded_path = quote(normalized_remote, safe=":/")

        publish_response = self._request("PUT", f"/resources/publish?path={encoded_path}")
        if publish_response.status_code not in {200, 201, 202, 409}:
            if publish_response.status_code == 401:
                raise RuntimeError("Yandex.Disk authorization failed (401). Check YANDEX_DISK_TOKEN.")
            raise RuntimeError(
                f"Failed to publish '{normalized_remote}' on Yandex.Disk: "
                f"{publish_response.status_code} {publish_response.text[:300]}"
            )

        last_metadata_response: httpx.Response | None = None
        for attempt in range(1, self.public_url_retries + 2):
            metadata_response = self._request("GET", f"/resources?path={encoded_path}&fields=public_url")
            last_metadata_response = metadata_response
            if metadata_response.status_code == 200:
                public_url = str((metadata_response.json() or {}).get("public_url") or "").strip()
                if public_url:
                    return public_url
            elif metadata_response.status_code == 401:
                raise RuntimeError("Yandex.Disk authorization failed (401). Check YANDEX_DISK_TOKEN.")
            elif metadata_response.status_code not in {404, 423, 429, 500, 502, 503, 504}:
                raise RuntimeError(
                    f"Failed to read public URL for '{normalized_remote}': "
                    f"{metadata_response.status_code} {metadata_response.text[:300]}"
                )

            if attempt <= self.public_url_retries:
                time.sleep(self.public_url_retry_backoff_seconds * attempt)

        if last_metadata_response is not None and last_metadata_response.status_code != 200:
            raise RuntimeError(
                f"Failed to read public URL for '{normalized_remote}' after publish: "
                f"{last_metadata_response.status_code} {last_metadata_response.text[:300]}"
            )
        raise RuntimeError(
            f"Public URL is empty for '{normalized_remote}' after {self.public_url_retries + 1} attempts"
        )

    def list_video_files(self, directory_path: str, limit: int = 500, include_debug: bool = False) -> list[dict] | tuple[list[dict], dict]:
        if not self.is_configured:
            raise RuntimeError("YANDEX_DISK_TOKEN is empty")

        normalized_dir = self._normalize_disk_path(directory_path)
        encoded_path = quote(normalized_dir, safe=":/")
        fields = "_embedded.items.name,_embedded.items.path,_embedded.items.type,_embedded.items.media_type,_embedded.items.mime_type"
        response = self._request(
            "GET",
            f"/resources?path={encoded_path}&limit={int(limit)}&fields={fields}",
        )
        if response.status_code != 200:
            if response.status_code == 401:
                raise RuntimeError("Yandex.Disk authorization failed (401). Check YANDEX_DISK_TOKEN.")
            raise RuntimeError(
                f"Failed to list Yandex.Disk folder '{normalized_dir}': "
                f"{response.status_code} {response.text[:300]}"
            )

        items = (((response.json() or {}).get("_embedded") or {}).get("items") or [])
        video_exts = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".mpeg"}
        result: list[dict] = []
        debug_items: list[dict] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "").strip()
            name = str(item.get("name") or os.path.basename(path)).strip()
            item_type = str(item.get("type") or "").strip()
            mime_type = str(item.get("mime_type") or "").lower()
            media_type = str(item.get("media_type") or "").lower()
            _, ext = os.path.splitext(name.lower())
            is_video = media_type == "video" or mime_type.startswith("video/") or ext in video_exts
            debug_items.append(
                {
                    "name": name,
                    "path": path,
                    "type": item_type,
                    "mime_type": mime_type,
                    "media_type": media_type,
                    "ext": ext,
                    "is_video": is_video,
                }
            )
            if item_type != "file":
                continue
            if is_video:
                result.append({"path": path, "name": name, "mime_type": mime_type, "media_type": media_type})
        if include_debug:
            return result, {"directory": normalized_dir, "items_count": len(items), "items": debug_items[:50]}
        return result

    def download_file(self, remote_path: str, local_path: str) -> str:
        if not self.is_configured:
            raise RuntimeError("YANDEX_DISK_TOKEN is empty")

        normalized_remote = self._normalize_disk_path(remote_path)
        encoded_path = quote(normalized_remote, safe=":/")
        get_href_response = self._request("GET", f"/resources/download?path={encoded_path}")
        if get_href_response.status_code != 200:
            if get_href_response.status_code == 401:
                raise RuntimeError("Yandex.Disk authorization failed (401). Check YANDEX_DISK_TOKEN.")
            raise RuntimeError(
                f"Failed to get Yandex.Disk download URL for '{normalized_remote}': "
                f"{get_href_response.status_code} {get_href_response.text[:300]}"
            )

        href = (get_href_response.json() or {}).get("href")
        if not href:
            raise RuntimeError(f"Yandex.Disk download URL is missing for '{normalized_remote}'")

        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        temp_path = f"{local_path}.part"
        timeout = httpx.Timeout(
            connect=min(self.timeout_seconds, 30.0),
            read=self.upload_timeout_seconds,
            write=self.upload_timeout_seconds,
            pool=self.timeout_seconds,
        )
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                with client.stream("GET", href) as response:
                    response.raise_for_status()
                    with open(temp_path, "wb") as output:
                        for chunk in response.iter_bytes(chunk_size=1024 * 512):
                            if chunk:
                                output.write(chunk)
            os.replace(temp_path, local_path)
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
        return local_path
