import logging
import os
from typing import Any
import json
import time

import httpx

from .cloudinary_storage import CloudinaryStorage


logger = logging.getLogger(__name__)


class ThumbnailGeneratorClient:
    def __init__(self) -> None:
        self.api_key = (os.getenv("KIE_API_KEY") or "").strip()
        self.base_url = (os.getenv("KIE_BASE_URL") or "https://api.kie.ai").rstrip("/")
        self.model_id = "gpt-image-2-image-to-image"
        self.fallback_model_id = (os.getenv("THUMBNAIL_KIE_FALLBACK_MODEL_ID") or "nano-banana-2").strip()
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
        self.cloudinary_folder = (os.getenv("CLOUDINARY_FOLDER") or "turan/thumbnails").strip().strip("/")
        self.cloudinary_storage = CloudinaryStorage(timeout_seconds=self.timeout_seconds, folder=self.cloudinary_folder)
        self.strict_topic_mode = (os.getenv("THUMBNAIL_STRICT_TOPIC_MODE") or "1").strip() not in {"0", "false", "False"}
        self.max_style_references = max(0, int((os.getenv("THUMBNAIL_MAX_STYLE_REFERENCES") or "4").strip() or "4"))
        self.last_error: dict[str, Any] | None = None

    KIE_ERROR_MESSAGES_RU = {
        401: "KIE не принял API-ключ. Проверь KIE_API_KEY.",
        402: "На аккаунте KIE закончились кредиты. Пополни баланс и запусти задачу заново.",
        404: "KIE не нашел нужный endpoint или модель. Возможно, модель временно недоступна.",
        408: "KIE слишком долго не вернул результат: upstream завис больше чем на 10 минут.",
        422: "KIE отклонил параметры генерации. Обычно это проблема с промптом, форматом или референсами.",
        429: "KIE ограничил частоту запросов. Нужно подождать и повторить позже.",
        455: "KIE сейчас на обслуживании или временно недоступен.",
        500: "KIE вернул внутреннюю ошибку сервера.",
        501: "KIE не смог сгенерировать картинку по этому запросу.",
        505: "KIE отключил эту функцию или модель для текущего аккаунта.",
    }

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

    def _upload_local_file_to_cloudinary(self, file_path: str, *, prefix: str) -> str | None:
        return self.cloudinary_storage.upload_file(file_path, prefix=prefix)

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

    def _set_last_error(
        self,
        *,
        model: str,
        stage: str,
        code: int | None = None,
        message: str | None = None,
        task_id: str | None = None,
    ) -> None:
        self.last_error = {
            "model": model,
            "stage": stage,
            "code": code,
            "message": message,
            "task_id": task_id,
            "russian": self.kie_error_message_ru(code=code, message=message, model=model),
        }

    def kie_error_message_ru(
        self,
        *,
        code: int | None = None,
        message: str | None = None,
        model: str | None = None,
    ) -> str:
        model_part = f" ({model})" if model else ""
        if code in self.KIE_ERROR_MESSAGES_RU:
            base = self.KIE_ERROR_MESSAGES_RU[code]
            return f"{base} Код KIE: {code}{model_part}."
        clean_message = (message or "").strip()
        if clean_message:
            return f"KIE вернул ошибку{model_part}: {clean_message[:220]}"
        return f"KIE не смог сгенерировать картинку{model_part}. Пробую запасную модель, если она доступна."

    def get_last_error_message_ru(self) -> str:
        if self.last_error and self.last_error.get("russian"):
            return str(self.last_error["russian"])
        return "KIE не смог сгенерировать картинку."

    def _create_task(self, payload: dict[str, Any]) -> str | None:
        model = str(payload.get("model") or self.model_id)
        if not self.api_key:
            logger.warning("KIE_API_KEY is empty; thumbnail generation skipped.")
            self._set_last_error(model=model, stage="createTask", message="KIE_API_KEY is empty")
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
                    response_code = data.get("code")
                    try:
                        numeric_code = int(response_code) if response_code is not None else None
                    except (TypeError, ValueError):
                        numeric_code = None
                    if numeric_code and numeric_code != 200:
                        response_msg = str(data.get("msg") or data.get("message") or "")
                        self._set_last_error(model=model, stage="createTask", code=numeric_code, message=response_msg)
                        logger.error("KIE createTask returned code=%s msg=%s model=%s", response_code, response_msg, model)
                        if numeric_code and 400 <= numeric_code < 500 and numeric_code != 429:
                            return None
                        if attempt >= self.create_task_max_attempts:
                            return None
                        delay = self.create_task_retry_delay_seconds * attempt
                        time.sleep(delay)
                        continue
                    break
                except httpx.HTTPStatusError as exc:
                    status_code = exc.response.status_code if exc.response is not None else None
                    response_text = exc.response.text[:1000] if exc.response is not None else ""
                    self._set_last_error(model=model, stage="createTask", code=status_code, message=response_text)
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
                    self._set_last_error(model=model, stage="createTask", message=str(exc))
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
                    self._set_last_error(model=model, stage="createTask", message=str(exc))
                    logger.error("KIE createTask failed: %s", exc)
                    return None

        task_id = (((data or {}).get("data") or {}).get("taskId") or "").strip()
        if not task_id:
            response_code = (data or {}).get("code")
            try:
                numeric_code = int(response_code) if response_code is not None else None
            except (TypeError, ValueError):
                numeric_code = None
            self._set_last_error(
                model=model,
                stage="createTask",
                code=numeric_code,
                message=str((data or {}).get("msg") or (data or {}).get("message") or "taskId is missing"),
            )
            logger.error("KIE createTask response has no taskId: %s", data)
            return None
        return task_id

    def _poll_task_result_url(self, task_id: str, *, model: str) -> str | None:
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
                    self._set_last_error(model=model, stage="recordInfo", message=str(exc), task_id=task_id)
                    logger.warning("KIE recordInfo polling failed for %s: %s", task_id, exc)
                    time.sleep(self.poll_interval_seconds)
                    continue

                response_code = (data or {}).get("code")
                try:
                    numeric_code = int(response_code) if response_code is not None else None
                except (TypeError, ValueError):
                    numeric_code = None
                if numeric_code and numeric_code != 200:
                    response_msg = str((data or {}).get("msg") or (data or {}).get("message") or "")
                    self._set_last_error(
                        model=model,
                        stage="recordInfo",
                        code=numeric_code,
                        message=response_msg,
                        task_id=task_id,
                    )
                    logger.error("KIE recordInfo returned code=%s msg=%s task=%s", response_code, response_msg, task_id)
                    return None

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
                            self._set_last_error(model=model, stage="resultJson", message=str(exc), task_id=task_id)
                            logger.error("Failed to parse KIE resultJson for %s: %s", task_id, exc)
                    self._set_last_error(model=model, stage="resultJson", message="resultUrls is missing", task_id=task_id)
                    return None
                if state == "fail":
                    fail_code = record.get("failCode")
                    try:
                        numeric_code = int(fail_code) if fail_code is not None else None
                    except (TypeError, ValueError):
                        numeric_code = None
                    fail_msg = str(record.get("failMsg") or record.get("msg") or "")
                    self._set_last_error(
                        model=model,
                        stage="generation",
                        code=numeric_code,
                        message=fail_msg,
                        task_id=task_id,
                    )
                    logger.error(
                        "KIE task %s failed. failCode=%s failMsg=%s",
                        task_id,
                        record.get("failCode"),
                        record.get("failMsg"),
                    )
                    return None
                time.sleep(self.poll_interval_seconds)
        self._set_last_error(model=model, stage="recordInfo", code=408, message="poll timeout", task_id=task_id)
        logger.error("KIE task %s timed out after %.1f seconds", task_id, self.poll_timeout_seconds)
        return None

    def _run_generation_payload(self, payload: dict[str, Any], output_path: str) -> str | None:
        model = str(payload.get("model") or self.model_id)
        task_id = self._create_task(payload)
        if not task_id:
            return None

        result_url = self._poll_task_result_url(task_id, model=model)
        if not result_url:
            return None
        downloaded_path = self._download_to_file(result_url, output_path)
        if not downloaded_path:
            self._set_last_error(model=model, stage="download", message="failed to download generated image", task_id=task_id)
        return downloaded_path

    def _build_nano_banana_payload(
        self,
        *,
        prompt: str,
        input_urls: list[str],
        aspect_ratio: str,
        resolution: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.fallback_model_id,
            "input": {
                "prompt": prompt,
                "image_input": input_urls,
                "aspect_ratio": aspect_ratio,
                "resolution": resolution if resolution in {"1K", "2K", "4K"} else "1K",
                "output_format": "png",
            },
        }
        if self.callback_url:
            payload["callBackUrl"] = self.callback_url
        return payload

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

        self.last_error = None
        generated = self._run_generation_payload(request_payload, output_path)
        if generated:
            return generated

        primary_error = self.get_last_error_message_ru()
        logger.warning("Primary KIE image model failed, trying %s fallback: %s", self.fallback_model_id, primary_error)
        fallback_payload = self._build_nano_banana_payload(
            prompt=augmented_prompt,
            input_urls=input_urls,
            aspect_ratio=(aspect_ratio or self.aspect_ratio).strip(),
            resolution=(resolution or self.resolution).strip(),
        )
        generated = self._run_generation_payload(fallback_payload, output_path)
        if generated:
            logger.info("KIE fallback model %s generated image after primary failure.", self.fallback_model_id)
            return generated
        logger.error("KIE primary and fallback image generation failed. Primary: %s Fallback: %s", primary_error, self.get_last_error_message_ru())
        return None

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

        self.last_error = None
        generated = self._run_generation_payload(request_payload, output_path)
        if generated:
            return generated

        primary_error = self.get_last_error_message_ru()
        logger.warning("Primary KIE image model failed, trying %s fallback: %s", self.fallback_model_id, primary_error)
        fallback_payload = self._build_nano_banana_payload(
            prompt=clean_prompt,
            input_urls=input_urls,
            aspect_ratio=(aspect_ratio or self.aspect_ratio).strip(),
            resolution=(resolution or self.resolution).strip(),
        )
        generated = self._run_generation_payload(fallback_payload, output_path)
        if generated:
            logger.info("KIE fallback model %s generated image after primary failure.", self.fallback_model_id)
            return generated
        logger.error("KIE primary and fallback image generation failed. Primary: %s Fallback: %s", primary_error, self.get_last_error_message_ru())
        return None
