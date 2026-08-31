import logging
import os
from pathlib import Path
from typing import Any

import httpx


logger = logging.getLogger(__name__)


class CarouselRendererClient:
    """Client for the internal karlo_carouselv2 HTML-to-PNG renderer."""

    def __init__(self) -> None:
        self.base_url = (os.getenv("CAROUSEL_RENDERER_URL") or "").strip().rstrip("/")
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

        if not response.content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("karlo_carouselv2 вернул не PNG")
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp")
        temporary.write_bytes(response.content)
        temporary.replace(destination)
        return str(destination)
