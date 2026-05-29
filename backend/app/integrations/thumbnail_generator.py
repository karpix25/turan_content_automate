import logging
import os
from typing import Any
import json
import time
import hashlib

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
        self.create_task_max_attempts = max(1, int((os.getenv("THUMBNAIL_KIE_CREATE_TASK_MAX_ATTEMPTS") or "4").strip() or "4"))
        self.create_task_retry_delay_seconds = max(
            0.5,
            float((os.getenv("THUMBNAIL_KIE_CREATE_TASK_RETRY_DELAY_SECONDS") or "3").strip() or "3"),
        )
        self.aspect_ratio = (os.getenv("THUMBNAIL_KIE_ASPECT_RATIO") or "16:9").strip()
        self.resolution = (os.getenv("THUMBNAIL_KIE_RESOLUTION") or "1K").strip()
        self.callback_url = (os.getenv("THUMBNAIL_KIE_CALLBACK_URL") or "").strip()
        self.cloudinary_cloud_name = (os.getenv("CLOUDINARY_CLOUD_NAME") or "").strip()
        self.cloudinary_api_key = (os.getenv("CLOUDINARY_API_KEY") or "").strip()
        self.cloudinary_api_secret = (os.getenv("CLOUDINARY_API_SECRET") or "").strip()
        self.cloudinary_upload_preset = (os.getenv("CLOUDINARY_UPLOAD_PRESET") or "").strip()
        self.cloudinary_folder = (os.getenv("CLOUDINARY_FOLDER") or "turan/thumbnails").strip().strip("/")
        self.strict_topic_mode = (os.getenv("THUMBNAIL_STRICT_TOPIC_MODE") or "1").strip() not in {"0", "false", "False"}
        self.max_style_references = max(0, int((os.getenv("THUMBNAIL_MAX_STYLE_REFERENCES") or "4").strip() or "4"))

    @staticmethod
    def _is_surveillance_topic(prompt: str) -> bool:
        text = (prompt or "").lower()
        markers = (
            "vpn", "впн", "фсб", "слеж", "контрол", "роскомнадзор",
            "яндекс", "сбер", "ozon", "озон", "vk", "вконтакте", "avito", "авито",
            "утечк", "трекер", "ip-адрес", "айпи",
        )
        return any(marker in text for marker in markers)

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

    def _cloudinary_upload_endpoint(self) -> str | None:
        if not self.cloudinary_cloud_name:
            return None
        return f"https://api.cloudinary.com/v1_1/{self.cloudinary_cloud_name}/image/upload"

    def _build_cloudinary_signature(self, params: dict[str, Any]) -> str:
        sorted_items = sorted((k, v) for k, v in params.items() if v is not None and v != "")
        payload = "&".join(f"{k}={v}" for k, v in sorted_items)
        digest = hashlib.sha1(f"{payload}{self.cloudinary_api_secret}".encode("utf-8")).hexdigest()
        return digest

    def _upload_local_file_to_cloudinary(self, file_path: str, *, prefix: str) -> str | None:
        endpoint = self._cloudinary_upload_endpoint()
        if not endpoint:
            logger.error("CLOUDINARY_CLOUD_NAME is not configured.")
            return None
        if not os.path.isfile(file_path):
            return None

        timestamp = int(time.time())
        public_id = f"{prefix}_{timestamp}_{os.urandom(4).hex()}"
        folder = self.cloudinary_folder
        upload_params: dict[str, Any] = {"folder": folder, "public_id": public_id}

        signed_mode = bool(self.cloudinary_api_key and self.cloudinary_api_secret)
        unsigned_mode = bool(self.cloudinary_upload_preset)
        if not signed_mode and not unsigned_mode:
            logger.error(
                "Cloudinary is not fully configured. "
                "Set CLOUDINARY_UPLOAD_PRESET for unsigned uploads or CLOUDINARY_API_KEY/CLOUDINARY_API_SECRET."
            )
            return None

        data: dict[str, Any] = dict(upload_params)
        if unsigned_mode:
            data["upload_preset"] = self.cloudinary_upload_preset
        else:
            data["timestamp"] = timestamp
            data["api_key"] = self.cloudinary_api_key
            sign_params = {**upload_params, "timestamp": timestamp}
            data["signature"] = self._build_cloudinary_signature(sign_params)

        try:
            with open(file_path, "rb") as fh:
                files = {"file": (os.path.basename(file_path), fh, "application/octet-stream")}
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.post(endpoint, data=data, files=files)
                    response.raise_for_status()
                    payload = response.json()
        except Exception as exc:
            logger.error("Cloudinary upload failed for %s: %s", file_path, exc)
            return None

        secure_url = (payload or {}).get("secure_url")
        if isinstance(secure_url, str) and secure_url.strip():
            return secure_url.strip()
        logger.error("Cloudinary upload response has no secure_url: %s", payload)
        return None

    def _ensure_public_url(self, value: str | None, *, prefix: str) -> str | None:
        if not value:
            return None
        raw = value.strip()
        if not raw:
            return None
        if raw.startswith("http://") or raw.startswith("https://"):
            return raw
        return self._upload_local_file_to_cloudinary(raw, prefix=prefix)

    def _kie_http_client(self) -> httpx.Client:
        return httpx.Client(timeout=self.timeout_seconds)

    def _create_task(self, payload: dict[str, Any]) -> str | None:
        if not self.api_key:
            logger.warning("KIE_API_KEY is empty; thumbnail generation skipped.")
            return None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        data = None
        with self._kie_http_client() as client:
            for attempt in range(1, self.create_task_max_attempts + 1):
                try:
                    response = client.post(f"{self.base_url}/api/v1/jobs/createTask", headers=headers, json=payload)
                    response.raise_for_status()
                    data = response.json()
                    break
                except httpx.HTTPStatusError as exc:
                    status_code = exc.response.status_code if exc.response is not None else None
                    response_text = exc.response.text[:1000] if exc.response is not None else ""
                    if status_code and 400 <= status_code < 500 and status_code != 429:
                        logger.error("KIE createTask failed with non-retryable HTTP %s: %s", status_code, response_text)
                        return None
                    if attempt >= self.create_task_max_attempts:
                        logger.error(
                            "KIE createTask failed after %s attempts with HTTP %s: %s",
                            attempt,
                            status_code,
                            response_text,
                        )
                        return None
                    delay = self.create_task_retry_delay_seconds * attempt
                    logger.warning(
                        "KIE createTask HTTP %s failed on attempt %s/%s; retrying in %.1fs: %s",
                        status_code,
                        attempt,
                        self.create_task_max_attempts,
                        delay,
                        response_text,
                    )
                    time.sleep(delay)
                except (httpx.TimeoutException, httpx.NetworkError, httpx.TransportError) as exc:
                    if attempt >= self.create_task_max_attempts:
                        logger.error("KIE createTask failed after %s attempts: %s", attempt, exc)
                        return None
                    delay = self.create_task_retry_delay_seconds * attempt
                    logger.warning(
                        "KIE createTask transport failed on attempt %s/%s; retrying in %.1fs: %s",
                        attempt,
                        self.create_task_max_attempts,
                        delay,
                        exc,
                    )
                    time.sleep(delay)
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
        with self._kie_http_client() as client:
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
        face_paths: list[str] | None = None,
        reference_paths: list[str],
        output_path: str,
        aspect_ratio: str | None = None,
        resolution: str | None = None,
        max_style_references: int | None = None,
    ) -> str | None:
        clean_prompt = (prompt or "").strip()
        if not clean_prompt:
            return None

        topic_requires_strict_refs = self.strict_topic_mode and self._is_surveillance_topic(clean_prompt)
        refs = [p for p in reference_paths if p and (os.path.isfile(p) or p.startswith("http://") or p.startswith("https://"))]
        candidate_face_paths = [p for p in ([face_path] + list(face_paths or [])) if p]
        face_urls = []
        for index, path in enumerate(dict.fromkeys(candidate_face_paths), start=1):
            maybe_url = self._ensure_public_url(path, prefix=f"face{index}")
            if maybe_url and maybe_url not in face_urls:
                face_urls.append(maybe_url)
        face_url = face_urls[0] if face_urls else None
        ref_urls = []
        style_ref_limit = self.max_style_references if max_style_references is None else max(0, int(max_style_references))
        effective_ref_limit = 0 if topic_requires_strict_refs else style_ref_limit
        for index, path in enumerate(refs[:effective_ref_limit], start=1):
            maybe_url = self._ensure_public_url(path, prefix=f"ref{index}")
            if maybe_url:
                ref_urls.append(maybe_url)

        input_urls: list[str] = []
        input_urls.extend(face_urls)
        input_urls.extend([url for url in ref_urls if url not in face_urls])

        if not input_urls:
            logger.error(
                "Thumbnail generation skipped: failed to resolve Cloudinary/public URLs for references."
            )
            return None

        augmented_prompt = clean_prompt
        if face_url:
            augmented_prompt += (
                "\nВажно: первые референсы в input_urls — лицо автора. "
                "Сохрани идентичность этого лица (черты, пропорции, узнаваемость), без подмены человека. "
                "Если в промте указано добавить автора/лицо автора, автор должен быть явно виден в кадре как realistic cutout sticker; не пропускай его."
            )
        augmented_prompt += (
            "\nВажно: не копируй сюжет/композицию/текст/цифры/логотипы/интерфейсы с референсов буквально."
            "\nРеференсы можно использовать только как стиль (свет, цвет, контраст), но смысл и композицию бери из сценарного хука."
        )
        if topic_requires_strict_refs:
            augmented_prompt += (
                "\nКритично: тема про слежку/контроль/VPN. Игнорируй любые финансовые и маркетинговые паттерны."
            )
            logger.info("Thumbnail strict-topic mode enabled: style references disabled for this prompt.")

        request_payload: dict[str, Any] = {
            "model": self.model_id,
            "input": {
                "prompt": augmented_prompt,
                "input_urls": input_urls,
                "aspect_ratio": (aspect_ratio or self.aspect_ratio).strip(),
                "resolution": (resolution or self.resolution).strip(),
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

    def generate_image_from_references(
        self,
        *,
        prompt: str,
        reference_paths: list[str],
        output_path: str,
        aspect_ratio: str | None = None,
        resolution: str | None = None,
    ) -> str | None:
        clean_prompt = (prompt or "").strip()
        if not clean_prompt:
            return None

        input_urls: list[str] = []
        for index, path in enumerate(reference_paths, start=1):
            maybe_url = self._ensure_public_url(path, prefix=f"image_ref{index}")
            if maybe_url and maybe_url not in input_urls:
                input_urls.append(maybe_url)

        if not input_urls:
            logger.error("Image generation skipped: no public reference URLs.")
            return None

        request_payload: dict[str, Any] = {
            "model": self.model_id,
            "input": {
                "prompt": clean_prompt,
                "input_urls": input_urls,
                "aspect_ratio": (aspect_ratio or self.aspect_ratio).strip(),
                "resolution": (resolution or self.resolution).strip(),
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
