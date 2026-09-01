import logging
import os
from pathlib import Path
from typing import Any

import httpx


logger = logging.getLogger(__name__)


class CarouselRendererClient:
    """Client for the internal karlo_carouselv2 HTML-to-PNG renderer."""

    def __init__(self) -> None:
        self.base_url = (os.getenv("CAROUSEL_RENDERER_URL") or "http://karlo-carousel:2305").strip().rstrip("/")
        self.api_key = (os.getenv("CAROUSEL_RENDERER_API_KEY") or "").strip()
        self.timeout_seconds = max(30.0, float(os.getenv("CAROUSEL_RENDERER_TIMEOUT_SECONDS", "180")))

    def render(self, template: dict[str, Any], data: dict[str, Any], output_path: str) -> str:
        if not self.base_url:
            raise RuntimeError("Не задан CAROUSEL_RENDERER_URL для karlo_carouselv2")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        try:
            with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
                response = client.post(
                    f"{self.base_url}/templates/render",
                    json={"template": template, "data": data},
                    headers=headers,
                )
                response.raise_for_status()
        except (httpx.HTTPError, OSError) as exc:
            logger.exception("karlo_carouselv2 render failed")
            raise RuntimeError(f"Renderer karlo_carouselv2 недоступен: {exc}") from exc

        return self._save_png(response.content, output_path)

    def list_templates(self) -> list[dict[str, Any]]:
        response = self._request("GET", "/templates")
        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError("karlo_carouselv2 вернул некорректный список шаблонов")
        return payload

    def render_saved_template(self, template_id: str, data: dict[str, Any], output_path: str) -> str:
        response = self._request("POST", f"/templates/{template_id}/render", json=data)
        return self._save_png(response.content, output_path)

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        try:
            with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
                response = client.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)
                response.raise_for_status()
                return response
        except (httpx.HTTPError, OSError) as exc:
            logger.exception("karlo_carouselv2 request failed")
            raise RuntimeError(f"Renderer karlo_carouselv2 недоступен: {exc}") from exc

    @staticmethod
    def _save_png(content: bytes, output_path: str) -> str:
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("karlo_carouselv2 вернул не PNG")
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp")
        temporary.write_bytes(content)
        temporary.replace(destination)
        return str(destination)
