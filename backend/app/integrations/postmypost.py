import datetime
import email.utils
import httpx
import logging
import os
import random
import threading
import time
from typing import Any, Dict, List, Optional

from .postmypost_errors import PostMyPostApiError, format_postmypost_api_error

logger = logging.getLogger(__name__)


class PostMyPostClient:
    BASE_URL = "https://api.postmypost.io/v4.1"
    DEFAULT_PER_PAGE = 20
    RATE_WINDOW_SECONDS = 60.0
    _cache: Dict[str, tuple[float, Any]] = {}
    _rate_limit_lock = threading.Lock()
    _rate_limit_hits: Dict[str, List[float]] = {}

    def __init__(self, api_key: str):
        self.api_key = self._normalize_api_key(api_key)
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "X-API-KEY": self.api_key,
            "Accept": "application/json",
        }
        request_timeout = float(os.getenv("POSTMYPOST_REQUEST_TIMEOUT_SECONDS", "12"))
        connect_timeout = float(os.getenv("POSTMYPOST_CONNECT_TIMEOUT_SECONDS", "4"))
        write_timeout = float(os.getenv("POSTMYPOST_WRITE_TIMEOUT_SECONDS", "20"))
        self.timeout = httpx.Timeout(
            timeout=request_timeout,
            connect=connect_timeout,
            read=request_timeout,
            write=write_timeout,
            pool=connect_timeout,
        )
        self.max_retries = max(0, int(os.getenv("POSTMYPOST_MAX_RETRIES", "2")))
        self.cache_ttl_seconds = max(1, int(os.getenv("POSTMYPOST_CACHE_TTL_SECONDS", "120")))
        self.stale_cache_ttl_seconds = max(
            self.cache_ttl_seconds,
            int(os.getenv("POSTMYPOST_STALE_CACHE_TTL_SECONDS", "900")),
        )
        self.upload_poll_interval_seconds = max(
            6.0,
            float(os.getenv("POSTMYPOST_UPLOAD_POLL_INTERVAL_SECONDS", "8")),
        )
        self.upload_poll_timeout_seconds = max(
            self.upload_poll_interval_seconds,
            float(os.getenv("POSTMYPOST_UPLOAD_POLL_TIMEOUT_SECONDS", "300")),
        )

    @staticmethod
    def _normalize_api_key(api_key: str) -> str:
        normalized = (api_key or "").strip().strip('"').strip("'")
        if normalized.lower().startswith("bearer "):
            normalized = normalized.split(" ", 1)[1].strip()
        return normalized

    @staticmethod
    def _parse_retry_after_seconds(raw: str | None) -> float | None:
        value = (raw or "").strip()
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                parsed = email.utils.parsedate_to_datetime(value)
            except (TypeError, ValueError):
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=datetime.timezone.utc)
            delay = (parsed - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
            return max(0.0, delay)

    @staticmethod
    def _resolve_rate_limit_bucket(method: str, path: str) -> tuple[str, int]:
        normalized_path = (path or "").split("?", 1)[0]
        normalized_method = (method or "").upper()
        if normalized_path.startswith("/upload/"):
            return "upload", 10
        if normalized_method == "POST" and normalized_path == "/publications":
            return "create-publication", 10
        return "default", 30

    @classmethod
    def _acquire_rate_limit_slot(cls, bucket_key: str, limit_per_minute: int) -> None:
        while True:
            now = time.monotonic()
            wait_seconds = 0.0
            with cls._rate_limit_lock:
                hits = cls._rate_limit_hits.setdefault(bucket_key, [])
                threshold = now - cls.RATE_WINDOW_SECONDS
                while hits and hits[0] <= threshold:
                    hits.pop(0)

                if len(hits) < max(1, limit_per_minute):
                    hits.append(now)
                    return
                wait_seconds = max(0.05, (hits[0] + cls.RATE_WINDOW_SECONDS) - now)
            time.sleep(wait_seconds)

    def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        if not self.api_key:
            raise ValueError("POSTMYPOST_API_KEY is empty")

        url = f"{self.BASE_URL}{path}"
        headers = kwargs.pop("headers", {})
        merged_headers = {**self.headers, **headers}
        last_error: Exception | None = None
        bucket_key, bucket_limit = self._resolve_rate_limit_bucket(method, path)

        for attempt in range(self.max_retries + 1):
            try:
                self._acquire_rate_limit_slot(bucket_key, bucket_limit)
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.request(method, url, headers=merged_headers, **kwargs)
                    if response.status_code >= 500 or response.status_code == 429:
                        body = response.text[:500]
                        logger.warning(
                            "PostMyPost API transient error %s for %s %s (attempt %s/%s): %s",
                            response.status_code,
                            method,
                            path,
                            attempt + 1,
                            self.max_retries + 1,
                            body,
                        )
                        response.raise_for_status()
                    if response.status_code >= 400:
                        body = response.text[:1000]
                        logger.error(
                            "PostMyPost API error %s for %s %s: %s",
                            response.status_code,
                            method,
                            path,
                            body,
                        )
                        raise format_postmypost_api_error(response, method=method, path=path)
                    return response.json()
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError, PostMyPostApiError) as exc:
                last_error = exc
                if isinstance(exc, PostMyPostApiError):
                    break
                if (
                    isinstance(exc, httpx.HTTPStatusError)
                    and 400 <= exc.response.status_code < 500
                    and exc.response.status_code != 429
                ):
                    break
                if attempt >= self.max_retries:
                    break
                
                # Determine wait time with exponential backoff and jitter
                delay = 1.0 * (attempt + 1)
                if isinstance(exc, httpx.HTTPStatusError):
                    if exc.response.status_code == 429:
                        retry_after = self._parse_retry_after_seconds(exc.response.headers.get("Retry-After"))
                        # 3^1=3s, 3^2=9s, 3^3=27s... plus jitter
                        delay = retry_after if retry_after is not None else (3.0 ** (attempt + 1)) + random.uniform(0, 1)
                    elif exc.response.status_code >= 500:
                        # 2^1=2s, 2^2=4s, 2^3=8s... plus jitter
                        delay = (2.0 ** (attempt + 1)) + random.uniform(0, 1)
                
                delay = max(0.5, min(60.0, delay))
                logger.info("Retrying PostMyPost API %s %s after %.2fs due to transient error (attempt %s/%s)", 
                            method, path, delay, attempt + 1, self.max_retries + 1)
                time.sleep(delay)

        assert last_error is not None
        if isinstance(last_error, httpx.HTTPStatusError):
            raise format_postmypost_api_error(last_error.response, method=method, path=path) from last_error
        raise last_error

    @classmethod
    def _get_cached_value(cls, key: str, *, max_age_seconds: int) -> Any | None:
        cached = cls._cache.get(key)
        if not cached:
            return None
        created_at, value = cached
        if (time.time() - created_at) > max_age_seconds:
            return None
        return value

    @classmethod
    def _set_cached_value(cls, key: str, value: Any) -> None:
        cls._cache[key] = (time.time(), value)

    def _cached_list_call(self, key: str, loader) -> List[Dict[str, Any]]:
        fresh = self._get_cached_value(key, max_age_seconds=self.cache_ttl_seconds)
        if fresh is not None:
            return fresh
        try:
            value = loader()
            self._set_cached_value(key, value)
            return value
        except Exception as exc:
            stale = self._get_cached_value(key, max_age_seconds=self.stale_cache_ttl_seconds)
            if stale is not None:
                logger.warning("Using stale PostMyPost cache for %s after error: %s", key, exc)
                return stale
            raise

    @staticmethod
    def _unwrap_data(payload: Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            return payload["data"]
        return payload

    @staticmethod
    def _unwrap_data_list(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        if isinstance(payload, dict) and isinstance(payload.get("data"), list):
            return payload["data"]
        return []

    def _request_all_pages(self, path: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        query = dict(params or {})
        query.setdefault("per_page", self.DEFAULT_PER_PAGE)
        page = int(query.get("page", 1))
        result: List[Dict[str, Any]] = []

        while True:
            query["page"] = page
            payload = self._request("GET", path, params=query)
            result.extend(self._unwrap_data_list(payload))

            pages = payload.get("pages") if isinstance(payload, dict) else None
            next_page = pages.get("next") if isinstance(pages, dict) else None
            if not next_page:
                break
            page = int(next_page)

        return result

    @staticmethod
    def extract_preview_url(payload: Any) -> str | None:
        candidate_keys = {
            "preview",
            "preview_url",
            "thumbnail",
            "thumbnail_url",
            "cover",
            "cover_url",
            "poster",
            "poster_url",
            "image",
            "image_url",
        }

        def walk(node: Any) -> str | None:
            if isinstance(node, str):
                return node if node.startswith(("http://", "https://")) else None
            if isinstance(node, list):
                for item in node:
                    found = walk(item)
                    if found:
                        return found
                return None
            if isinstance(node, dict):
                for key in candidate_keys:
                    value = node.get(key)
                    found = walk(value)
                    if found:
                        return found
                for key, value in node.items():
                    key_text = str(key).lower()
                    if any(token in key_text for token in ("preview", "thumb", "cover", "poster", "image")):
                        found = walk(value)
                        if found:
                            return found
                for value in node.values():
                    found = walk(value)
                    if found:
                        return found
            return None

        return walk(payload)

    def get_projects(self) -> List[Dict[str, Any]]:
        return self._cached_list_call("projects", lambda: self._request_all_pages("/projects"))

    def get_channels(self) -> List[Dict[str, Any]]:
        return self._cached_list_call("channels", lambda: self._request_all_pages("/channels"))

    def get_accounts(self, project_id: int) -> List[Dict[str, Any]]:
        return self._cached_list_call(
            f"accounts:{project_id}",
            lambda: self._request_all_pages("/accounts", params={"project_id": project_id}),
        )

    def init_upload(self, project_id: int, file_name: str, file_size: int) -> Dict[str, Any]:
        try:
            response = self._request(
                "POST",
                "/upload/init",
                json={"project_id": project_id, "name": file_name, "size": file_size},
            )
        except PostMyPostApiError as exc:
            raise RuntimeError(
                "PostMyPost отклонил старт загрузки "
                f"(HTTP {exc.status_code}): "
                f"project_id={project_id}, file={file_name}, size={file_size} байт. "
                f"Причина: {exc}"
            ) from exc
        return self._unwrap_data(response)

    def complete_upload(self, upload_id: int) -> Dict[str, Any]:
        response = self._request("POST", "/upload/complete", params={"id": upload_id})
        return self._unwrap_data(response)

    def status_upload(self, upload_id: int) -> Dict[str, Any]:
        response = self._request("GET", "/upload/status", params={"id": upload_id})
        return self._unwrap_data(response)

    def upload_local_file(self, project_id: int, file_path: str) -> int:
        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)

        init_payload = self.init_upload(project_id=project_id, file_name=file_name, file_size=file_size)
        upload_id = init_payload.get("id")
        action = init_payload.get("action")
        fields = init_payload.get("fields", [])

        if not upload_id or not action:
            raise RuntimeError("Upload init did not return id/action")

        form_fields = {
            item.get("key"): item.get("value")
            for item in fields
            if isinstance(item, dict) and item.get("key")
        }

        with open(file_path, "rb") as fp:
            files = {"file": (file_name, fp)}
            with httpx.Client(timeout=300.0) as client:
                upload_response = client.post(action, data=form_fields, files=files)
                upload_response.raise_for_status()

        self.complete_upload(upload_id)
        poll_deadline = time.monotonic() + self.upload_poll_timeout_seconds
        while True:
            status_payload = self.status_upload(upload_id)
            status_code = status_payload.get("status")
            file_id = status_payload.get("file_id")
            if file_id and status_code == 1:
                return int(file_id)
            if status_code == 2:
                raise RuntimeError(f"Upload failed for id={upload_id}")
            if time.monotonic() >= poll_deadline:
                break
            time.sleep(self.upload_poll_interval_seconds)

        raise TimeoutError(
            f"Upload polling timeout for id={upload_id} "
            f"after {int(self.upload_poll_timeout_seconds)}s"
        )

    def _normalize_account_ids(self, account_ids: List[int]) -> List[int]:
        normalized: List[int] = []
        seen: set[int] = set()
        for account_id in account_ids:
            if account_id is None:
                continue
            value = int(account_id)
            if value in seen:
                continue
            normalized.append(value)
            seen.add(value)
        return sorted(normalized)

    def create_publication(
        self,
        project_id: int,
        account_ids: List[int],
        post_at: datetime.datetime,
        file_id: int,
        content: str = "",
        content_by_account: Optional[Dict[int, str]] = None,
        title_by_account: Optional[Dict[int, str]] = None,
        publication_type: int = 1,
    ) -> Dict[str, Any]:
        post_at_iso = post_at.astimezone(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        account_ids = self._normalize_account_ids(account_ids)
        content_by_account = content_by_account or {}
        title_by_account = title_by_account or {}
        details: List[Dict[str, Any]] = []
        for account_id in account_ids:
            item: Dict[str, Any] = {
                "account_id": account_id,
                "publication_type": publication_type,
                "file_ids": [file_id],
            }
            if account_id in content_by_account:
                item["content"] = content_by_account.get(account_id) or ""
            elif content:
                item["content"] = content
            account_title = (title_by_account.get(account_id) or "").strip()
            if account_title:
                item["title"] = account_title
            details.append(item)

        payload = {
            "project_id": project_id,
            "post_at": post_at_iso,
            "account_ids": account_ids,
            "publication_status": 5,
            "details": details,
        }
        response = self._request("POST", "/publications", json=payload)
        return self._unwrap_data(response)

    def update_publication(
        self,
        publication_id: int,
        account_ids: List[int],
        post_at: datetime.datetime,
        file_id: int,
        content: str = "",
        content_by_account: Optional[Dict[int, str]] = None,
        title_by_account: Optional[Dict[int, str]] = None,
        publication_type: int = 1,
    ) -> Dict[str, Any]:
        post_at_iso = post_at.astimezone(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        account_ids = self._normalize_account_ids(account_ids)
        content_by_account = content_by_account or {}
        title_by_account = title_by_account or {}
        details: List[Dict[str, Any]] = []
        for account_id in account_ids:
            item: Dict[str, Any] = {
                "account_id": account_id,
                "publication_type": publication_type,
                "file_ids": [file_id],
            }
            if account_id in content_by_account:
                item["content"] = content_by_account.get(account_id) or ""
            elif content:
                item["content"] = content
            account_title = (title_by_account.get(account_id) or "").strip()
            if account_title:
                item["title"] = account_title
            details.append(item)

        payload = {
            "post_at": post_at_iso,
            "account_ids": account_ids,
            "publication_status": 5,
            "details": details,
        }
        response = self._request("PUT", f"/publications/{publication_id}", json=payload)
        return self._unwrap_data(response)

    @staticmethod
    def _format_account_ids_param(account_ids: Optional[List[int]]) -> str | None:
        if not account_ids:
            return None
        values = [str(int(item)) for item in account_ids if item is not None]
        return ",".join(values) if values else None

    def get_publication(self, publication_id: int, account_ids: Optional[List[int]] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        account_ids_param = self._format_account_ids_param(account_ids)
        if account_ids_param:
            params["account_ids"] = account_ids_param
        response = self._request("GET", f"/publications/{publication_id}", params=params or None)
        return self._unwrap_data(response)

    def delete_publication(self, publication_id: int, account_ids: List[int], delete_option: int = 3) -> None:
        account_ids_csv = self._format_account_ids_param(account_ids) or ""
        try:
            self._request(
                "DELETE",
                f"/publications/{publication_id}",
                params={"delete_option": delete_option, "account_ids": account_ids_csv},
            )
        except (httpx.HTTPStatusError, PostMyPostApiError) as exc:
            status_code = (
                exc.status_code
                if isinstance(exc, PostMyPostApiError)
                else exc.response.status_code if exc.response is not None else None
            )
            if status_code == 404:
                logger.info("PostMyPost publication %s is already absent, treating delete as successful", publication_id)
                return
            raise

    def ensure_project_id(self, project_id: Optional[int]) -> int:
        if project_id:
            return int(project_id)
        projects = self.get_projects()
        if not projects:
            raise RuntimeError("PostMyPost returned empty projects list")
        return int(projects[0]["id"])
