import logging
import os
from typing import Any
import json
import time

import httpx


logger = logging.getLogger(__name__)


class ThumbnailGeneratorClient:
    def __init__(self) -> None:
        self.api_key = (os.getenv("KIE_API_KEY") or "").strip()
        self.base_url = (os.getenv("KIE_BASE_URL") or "https://api.kie.ai").rstrip("/")
        self.model_id = "gpt-image-2-image-to-image"
        self.timeout_seconds = float(os.getenv("THUMBNAIL_GENERATOR_TIMEOUT_SECONDS", "240"))
        self.poll_timeout_seconds = float(os.getenv("THUMBNAIL_KIE_POLL_TIMEOUT_SECONDS", "300"))
        self.poll_interval_seconds = float(os.getenv("THUMBNAIL_KIE_POLL_INTERVAL_SECONDS", "3"))
        self.aspect_ratio = (os.getenv("THUMBNAIL_KIE_ASPECT_RATIO") or "16:9").strip()
        self.resolution = (os.getenv("THUMBNAIL_KIE_RESOLUTION") or "1K").strip()
        self.callback_url = (os.getenv("THUMBNAIL_KIE_CALLBACK_URL") or "").strip()
        self.media_root = (os.getenv("THUMBNAIL_MEDIA_ROOT") or "/app/database/media").rstrip("/")
        self.public_media_base_url = (os.getenv("THUMBNAIL_MEDIA_PUBLIC_BASE_URL") or "").rstrip("/")

    def _download_to_file(self, image_url: str, output_path: str) -> str | None:
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.get(image_url)
                response.raise_for_status()
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, "wb") as out:
                out.write(response.content)
            return output_path
        except Exception as exc:
            logger.warning("Failed to download generated thumbnail from %s: %s", image_url, exc)
            return None

    def _to_public_url(self, file_path: str | None) -> str | None:
        if not file_path:
            return None
        raw = file_path.strip()
        if not raw:
            return None
        if raw.startswith("http://") or raw.startswith("https://"):
            return raw
        if not self.public_media_base_url:
            return None
        abs_path = os.path.abspath(raw)
        root = os.path.abspath(self.media_root)
        if not abs_path.startswith(root):
            return None
        rel = abs_path[len(root):].lstrip("/")
        if not rel:
            return None
        return f"{self.public_media_base_url}/{rel}"

    def _create_task(self, payload: dict[str, Any]) -> str | None:
        if not self.api_key:
            logger.warning("KIE_API_KEY is empty; thumbnail generation skipped.")
            return None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(f"{self.base_url}/api/v1/jobs/createTask", headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            logger.error("KIE createTask failed: %s", exc)
            return None

        task_id = (((data or {}).get("data") or {}).get("taskId") or "").strip()
        if not task_id:
            logger.error("KIE createTask response has no taskId: %s", data)
            return None
        return task_id

    def _poll_task_result_url(self, task_id: str) -> str | None:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        deadline = time.time() + self.poll_timeout_seconds
        with httpx.Client(timeout=self.timeout_seconds) as client:
            while time.time() < deadline:
                try:
                    response = client.get(
                        f"{self.base_url}/api/v1/jobs/recordInfo",
                        headers=headers,
                        params={"taskId": task_id},
                    )
                    response.raise_for_status()
                    data = response.json()
                except Exception as exc:
                    logger.warning("KIE recordInfo polling failed for %s: %s", task_id, exc)
                    time.sleep(self.poll_interval_seconds)
                    continue

                record = (data or {}).get("data") or {}
                state = (record.get("state") or "").strip().lower()
                if state == "success":
                    result_json_raw = record.get("resultJson")
                    if isinstance(result_json_raw, str) and result_json_raw.strip():
                        try:
                            result_obj = json.loads(result_json_raw)
                            urls = result_obj.get("resultUrls") or []
                            if urls and isinstance(urls[0], str) and urls[0].strip():
                                return urls[0].strip()
                        except Exception as exc:
                            logger.error("Failed to parse KIE resultJson for %s: %s", task_id, exc)
                    return None
                if state == "fail":
                    logger.error(
                        "KIE task %s failed. failCode=%s failMsg=%s",
                        task_id,
                        record.get("failCode"),
                        record.get("failMsg"),
                    )
                    return None
                time.sleep(self.poll_interval_seconds)
        logger.error("KIE task %s timed out after %.1f seconds", task_id, self.poll_timeout_seconds)
        return None

    def generate_thumbnail(
        self,
        *,
        prompt: str,
        face_path: str | None,
        reference_paths: list[str],
        output_path: str,
    ) -> str | None:
        clean_prompt = (prompt or "").strip()
        if not clean_prompt:
            return None

        refs = [p for p in reference_paths if p and os.path.isfile(p)]
        face_url = self._to_public_url(face_path)
        ref_urls = []
        for path in refs[:6]:
            maybe_url = self._to_public_url(path)
            if maybe_url:
                ref_urls.append(maybe_url)

        input_urls: list[str] = []
        if face_url:
            input_urls.append(face_url)
        input_urls.extend([url for url in ref_urls if url != face_url])

        if not input_urls:
            logger.error(
                "Thumbnail generation skipped: no public input_urls. "
                "Set THUMBNAIL_MEDIA_PUBLIC_BASE_URL so KIE can fetch references."
            )
            return None

        augmented_prompt = (
            clean_prompt
            + "\nВажно: первый референс в input_urls — лицо автора. "
            + "Сохрани идентичность этого лица (черты, пропорции, узнаваемость), без подмены человека."
        )
        request_payload: dict[str, Any] = {
            "model": self.model_id,
            "input": {
                "prompt": augmented_prompt,
                "input_urls": input_urls,
                "aspect_ratio": self.aspect_ratio,
                "resolution": self.resolution,
            },
        }
        if self.callback_url:
            request_payload["callBackUrl"] = self.callback_url

        task_id = self._create_task(request_payload)
        if not task_id:
            return None

        result_url = self._poll_task_result_url(task_id)
        if not result_url:
            return None
        return self._download_to_file(result_url, output_path)
