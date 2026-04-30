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

        metadata_response = self._request("GET", f"/resources?path={encoded_path}&fields=public_url")
        if metadata_response.status_code != 200:
            if metadata_response.status_code == 401:
                raise RuntimeError("Yandex.Disk authorization failed (401). Check YANDEX_DISK_TOKEN.")
            raise RuntimeError(
                f"Failed to read public URL for '{normalized_remote}': "
                f"{metadata_response.status_code} {metadata_response.text[:300]}"
            )
        public_url = (metadata_response.json() or {}).get("public_url")
        if not public_url:
            raise RuntimeError(f"Public URL is empty for '{normalized_remote}'")
        return str(public_url).strip()
