import json
import math
import re
from typing import Any


DEFAULT_TEXT_SLOTS = {
    "carousel": {
        "heading_lines": 3,
        "description_lines": 4,
        "bullet_heading_lines": 1,
        "bullet_body_lines": 4,
    },
    "story": {
        "heading_lines": 3,
        "description_lines": 6,
        "bullet_heading_lines": 1,
        "bullet_body_lines": 6,
    },
}


def _positive_int(value: Any, fallback: int) -> int:
    try:
        return max(1, min(12, int(value)))
    except (TypeError, ValueError):
        return fallback


def _line_label(value: int) -> str:
    return "строку" if value == 1 else "строки"


def _contract_data(contract: str | None) -> dict[str, Any]:
    if not contract:
        return {}
    try:
        value = json.loads(contract)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _slot(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name)
    return value if isinstance(value, dict) else {}


def parse_text_slots(contract: str | None, design_format: str) -> dict[str, int]:
    defaults = DEFAULT_TEXT_SLOTS.get(design_format, DEFAULT_TEXT_SLOTS["carousel"])
    data = _contract_data(contract)
    slots = data.get("text_slots")
    if not isinstance(slots, dict):
        slots = _slot(data, "content") or _slot(data, "default")
    heading = _slot(data, "heading")
    body = _slot(data, "body")
    return {
        "heading_lines": _positive_int(slots.get("heading_lines") or heading.get("lines"), defaults["heading_lines"]),
        "description_lines": _positive_int(
            slots.get("description_lines") or slots.get("body_lines") or body.get("lines"),
            defaults["description_lines"],
        ),
        "bullet_heading_lines": _positive_int(
            slots.get("bullet_heading_lines") or slots.get("item_heading_lines"),
            defaults["bullet_heading_lines"],
        ),
        "bullet_body_lines": _positive_int(
            slots.get("bullet_body_lines") or slots.get("item_body_lines"),
            defaults["bullet_body_lines"],
        ),
    }


def build_layout_instruction(contract: str | None, design_format: str) -> str:
    slots = parse_text_slots(contract, design_format)
    return (
        "Жёсткий невидимый каркас, извлечённый из дизайн-референса: "
        f"заголовок всегда в одной и той же зоне и выравнивании, ровно {slots['heading_lines']} {_line_label(slots['heading_lines'])}; "
        f"описание всегда в одной и той же зоне под ним, ровно {slots['description_lines']} {_line_label(slots['description_lines'])}; "
        f"заголовок буллета — ровно {slots['bullet_heading_lines']} {_line_label(slots['bullet_heading_lines'])}, "
        f"описание буллета — ровно {slots['bullet_body_lines']} {_line_label(slots['bullet_body_lines'])}. "
        "Не меняй эти зоны и количество строк между слайдами. "
        "Если видимого текста меньше слота, оставь пустое место, не сдвигай блок. "
        "Если текста больше, сначала сокращай формулировку без потери факта и смысла, "
        "затем уменьши кегль внутри той же зоны. Не добавляй новые мысли."
    )


def _sentences(text: str) -> list[str]:
    return [
        part.strip()
        for part in re.split(r"(?<=[.!?…])\s+(?=[А-ЯЁ«„])", text)
        if part.strip()
    ]


def split_slide_content(part: str) -> dict[str, str | bool]:
    value = re.sub(r"\s+", " ", str(part or "").strip())
    is_bullet = value.startswith("•")
    value = re.sub(r"^•\s*", "", value).strip()
    sentences = _sentences(value)
    if is_bullet and sentences:
        heading = sentences[0]
        body = " ".join(sentences[1:]).strip()
    elif len(sentences) > 1:
        heading = sentences[0]
        body = " ".join(sentences[1:]).strip()
    else:
        heading, body = value, ""
    return {"heading": heading, "body": body, "is_bullet": is_bullet}


def _preferred_line_breaks(text: str, line_count: int) -> str:
    words = (text or "").split()
    if not words or line_count <= 1:
        return text or ""
    target = max(1, math.ceil(len(text) / line_count))
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join(current + [word])
        if current and len(candidate) > target and len(lines) < line_count - 1:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return "\n".join(lines)


def build_slide_text_spec(part: str, contract: str | None, design_format: str) -> str:
    content = split_slide_content(part)
    slots = parse_text_slots(contract, design_format)
    heading_lines = slots["bullet_heading_lines"] if content["is_bullet"] else slots["heading_lines"]
    body_lines = slots["bullet_body_lines"] if content["is_bullet"] else slots["description_lines"]
    marker = "• " if content["is_bullet"] else ""
    heading = _preferred_line_breaks(str(content["heading"]), heading_lines)
    body = _preferred_line_breaks(str(content["body"]), body_lines)
    return (
        "РОВНО ОДНА МЫСЛЬ НА СЛАЙД. Единственный разрешённый видимый текст ниже; "
        "служебные названия полей и эти инструкции не печатай.\n"
        f"ЗАГОЛОВОК ({heading_lines} {_line_label(heading_lines)}): {marker}{heading}\n"
        f"ОПИСАНИЕ ({body_lines} {_line_label(body_lines)}): {body or 'нет'}"
    )
