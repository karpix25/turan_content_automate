import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def build_design_composition_analysis_prompt(design_format: str, reference_urls: list[str]) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [{
        "type": "text",
        "text": (
            f"Проанализируй дизайн-референс для серии {design_format}. "
            "Нужен только точный паспорт композиции, без переписывания текста с картинки. "
            "Определи и зафиксируй: размер и соотношение сторон; положение и выравнивание заголовка; "
            "положение основного текста; левый и правый отступы; ширину текстовой колонки; "
            "интерлиньяж; иерархию шрифтов; безопасные зоны; положение CTA, если он есть; "
            "правила переносов, маркеров, линий, разделителей и пустого пространства. "
            "Отдельно укажи, какие элементы являются чужим контентом и должны быть удалены: "
            "исходный CTA, никнеймы, подписи, логотипы, водяные знаки, социальные иконки и цифры. "
            "Позиции указывай относительно кадра в процентах и, если видно, в пикселях. "
            "Не копируй и не цитируй слова, имена, CTA или цифры с референса. "
            "Верни только JSON с ключами: canvas, alignment, heading, body, cta, spacing, typography, "
            "safe_zones, foreign_elements. Значения должны быть короткими и конкретными."
        ),
    }]
    content.extend({"type": "image_url", "image_url": {"url": url}} for url in reference_urls)
    return [
        {
            "role": "system",
            "content": (
                "Ты арт-директор и специалист по анализу макетов. Извлекай геометрию и правила вёрстки "
                "из изображения, а не содержание текста. Отвечай только валидным JSON."
            ),
        },
        {"role": "user", "content": content},
    ]


def analyze_design_composition(llm_client: Any, reference_urls: list[str], design_format: str) -> str:
    urls = [url.strip() for url in reference_urls if isinstance(url, str) and url.strip()]
    if not urls:
        return ""
    result = llm_client._complete(
        build_design_composition_analysis_prompt(design_format, urls[:4]),
        temperature=0.1,
    )
    if not result:
        logger.warning("Design composition analysis returned no contract for %s", design_format)
        return ""
    raw = result.strip()
    try:
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            return json.dumps(json.loads(raw[start:end + 1]), ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError, json.JSONDecodeError):
        logger.warning("Design composition analysis was not valid JSON for %s", design_format)
    return raw[:5000]
