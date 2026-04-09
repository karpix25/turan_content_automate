import datetime
import httpx
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PostMyPostClient:
    BASE_URL = "https://api.postmypost.io/v4.1"
    DEFAULT_PER_PAGE = 20

    def __init__(self, api_key: str):
        self.api_key = self._normalize_api_key(api_key)
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "X-API-KEY": self.api_key,
            "Accept": "application/json",
        }

    @staticmethod
    def _normalize_api_key(api_key: str) -> str:
        normalized = (api_key or "").strip().strip('"').strip("'")
        if normalized.lower().startswith("bearer "):
            normalized = normalized.split(" ", 1)[1].strip()
        return normalized

    def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        if not self.api_key:
            raise ValueError("POSTMYPOST_API_KEY is empty")

        url = f"{self.BASE_URL}{path}"
        headers = kwargs.pop("headers", {})
        merged_headers = {**self.headers, **headers}

        with httpx.Client(timeout=60.0) as client:
            response = client.request(method, url, headers=merged_headers, **kwargs)
            if response.status_code >= 400:
                body = response.text[:500]
                logger.error(
                    f"PostMyPost API error {response.status_code} for {method} {path}: {body}"
                )
                response.raise_for_status()
            return response.json()

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

    def get_projects(self) -> List[Dict[str, Any]]:
        return self._request_all_pages("/projects")

    def get_channels(self) -> List[Dict[str, Any]]:
        return self._request_all_pages("/channels")

    def get_accounts(self, project_id: int) -> List[Dict[str, Any]]:
        return self._request_all_pages("/accounts", params={"project_id": project_id})

    def init_upload(self, project_id: int, file_name: str, file_size: int) -> Dict[str, Any]:
        response = self._request(
            "POST",
            "/upload/init",
            json={"project_id": project_id, "name": file_name, "size": file_size},
        )
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

        for _ in range(30):
            status_payload = self.status_upload(upload_id)
            status_code = status_payload.get("status")
            file_id = status_payload.get("file_id")
            if file_id and status_code == 1:
                return int(file_id)
            if status_code == 2:
                raise RuntimeError(f"Upload failed for id={upload_id}")
            time.sleep(2)

        raise TimeoutError(f"Upload polling timeout for id={upload_id}")

    def create_publication(
        self,
        project_id: int,
        account_ids: List[int],
        post_at: datetime.datetime,
        file_id: int,
        content: str = "",
        content_by_account: Optional[Dict[int, str]] = None,
        publication_type: int = 1,
    ) -> Dict[str, Any]:
        post_at_iso = post_at.astimezone(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        content_by_account = content_by_account or {}
        details: List[Dict[str, Any]] = []
        for account_id in account_ids:
            item: Dict[str, Any] = {
                "account_id": account_id,
                "publication_type": publication_type,
                "file_ids": [file_id],
            }
            account_content = content_by_account.get(account_id, content)
            if account_content:
                item["content"] = account_content
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
        publication_type: int = 1,
    ) -> Dict[str, Any]:
        post_at_iso = post_at.astimezone(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        content_by_account = content_by_account or {}
        details: List[Dict[str, Any]] = []
        for account_id in account_ids:
            item: Dict[str, Any] = {
                "account_id": account_id,
                "publication_type": publication_type,
                "file_ids": [file_id],
            }
            account_content = content_by_account.get(account_id, content)
            if account_content:
                item["content"] = account_content
            details.append(item)

        payload = {
            "post_at": post_at_iso,
            "account_ids": account_ids,
            "publication_status": 5,
            "details": details,
        }
        response = self._request("PUT", f"/publications/{publication_id}", json=payload)
        return self._unwrap_data(response)

    def get_publication(self, publication_id: int) -> Dict[str, Any]:
        response = self._request("GET", f"/publications/{publication_id}")
        return self._unwrap_data(response)

    def delete_publication(self, publication_id: int, account_ids: List[int], delete_option: int = 3) -> None:
        account_ids_csv = ",".join(str(item) for item in account_ids)
        self._request(
            "DELETE",
            f"/publications/{publication_id}",
            params={"delete_option": delete_option, "account_ids": account_ids_csv},
        )

    def ensure_project_id(self, project_id: Optional[int]) -> int:
        if project_id:
            return int(project_id)
        projects = self.get_projects()
        if not projects:
            raise RuntimeError("PostMyPost returned empty projects list")
        return int(projects[0]["id"])
