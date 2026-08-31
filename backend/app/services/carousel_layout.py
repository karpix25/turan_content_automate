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


def _bounded_int(value: Any, fallback: int, minimum: int = 0) -> int:
    try:
        return max(minimum, min(12, int(value)))
    except (TypeError, ValueError):
        return fallback


def _line_label(value: int) -> str:
    if value == 1:
        return "строку"
    if 2 <= value <= 4:
        return "строки"
    return "строк"


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


def _layout_values(section: dict[str, Any]) -> str:
    labels = {
        "top", "bottom", "left", "right", "width", "height", "x", "y",
        "align", "alignment", "horizontal_align", "vertical_align",
        "top_percent", "bottom_percent", "left_percent", "right_percent",
        "top_px", "bottom_px", "left_px", "right_px",
    }
    values: list[str] = []

    def visit(value: dict[str, Any]) -> None:
        for label, item in value.items():
            if isinstance(item, dict):
                visit(item)
            elif label in labels and item not in (None, ""):
                normalized = label.removesuffix("_percent")
                if label.endswith("_percent"):
                    value = str(item) if str(item).endswith("%") else f"{item}%"
                    values.append(f"{normalized}={value}")
                else:
                    values.append(f"{label}={item}")

    visit(section)
    return ", ".join(dict.fromkeys(values))


def parse_text_slots(contract: str | None, design_format: str) -> dict[str, int]:
    defaults = DEFAULT_TEXT_SLOTS.get(design_format, DEFAULT_TEXT_SLOTS["carousel"])
    data = _contract_data(contract)
    slots = data.get("text_slots")
    if not isinstance(slots, dict):
        slots = _slot(data, "content") or _slot(data, "default")
    heading = _slot(data, "heading")
    body = _slot(data, "body")
    heading_value = slots.get("heading_lines") if "heading_lines" in slots else heading.get("lines")
    description_value = next(
        (slots[name] for name in ("description_lines", "body_lines") if name in slots),
        body.get("lines"),
    )
    bullet_heading_value = next(
        (slots[name] for name in ("bullet_heading_lines", "item_heading_lines") if name in slots),
        None,
    )
    bullet_body_value = next(
        (slots[name] for name in ("bullet_body_lines", "item_body_lines") if name in slots),
        None,
    )
    return {
        "heading_lines": _bounded_int(heading_value, defaults["heading_lines"]),
        "description_lines": _bounded_int(description_value, defaults["description_lines"]),
        "bullet_heading_lines": _bounded_int(bullet_heading_value, defaults["bullet_heading_lines"]),
        "bullet_body_lines": _bounded_int(bullet_body_value, defaults["bullet_body_lines"]),
    }


def build_layout_instruction(contract: str | None, design_format: str) -> str:
    slots = parse_text_slots(contract, design_format)
    data = _contract_data(contract)
    heading_layout = _layout_values(_slot(data, "heading"))
    body_layout = _layout_values(_slot(data, "body"))
    cta_layout = _layout_values(_slot(data, "cta"))
    position_rules = " ".join(
        value for value in (
            f"Зона заголовка: {heading_layout}." if heading_layout else "",
            f"Зона описания: {body_layout}." if body_layout else "",
            f"Зона CTA: {cta_layout}." if cta_layout else "",
        )
    )
    heading_rule = "заголовок отсутствует" if slots["heading_lines"] == 0 else f"заголовок всегда в одной и той же зоне и выравнивании, ровно {slots['heading_lines']} {_line_label(slots['heading_lines'])}"
    description_rule = "описание отсутствует" if slots["description_lines"] == 0 else f"описание всегда в одной и той же зоне под ним, ровно {slots['description_lines']} {_line_label(slots['description_lines'])}"
    return (
        "Жёсткий невидимый каркас, извлечённый из дизайн-референса: "
        f"{heading_rule}; {description_rule}; "
        f"заголовок буллета — ровно {slots['bullet_heading_lines']} {_line_label(slots['bullet_heading_lines'])}, "
        f"описание буллета — ровно {slots['bullet_body_lines']} {_line_label(slots['bullet_body_lines'])}. "
        "Не меняй эти зоны и количество строк между слайдами. "
        "Если видимого текста меньше слота, оставь пустое место, не сдвигай блок. "
        "Если текста больше, сначала сокращай формулировку без потери факта и смысла, "
        "затем уменьши кегль внутри той же зоны. Не добавляй новые мысли. "
        f"{position_rules}"
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
        if ":" in heading:
            heading, first_body = heading.split(":", 1)
            heading = f"{heading.strip()}:"
            body = " ".join(value for value in (first_body.strip(), body) if value)
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


def _line_spec(text: str, line_count: int) -> str:
    lines = _preferred_line_breaks(text, line_count).splitlines() if text else []
    lines.extend([""] * max(0, line_count - len(lines)))
    return "\n".join(lines[:line_count])


def build_slide_text_spec(part: str, contract: str | None, design_format: str) -> str:
    content = split_slide_content(part)
    slots = parse_text_slots(contract, design_format)
    single_body_layout = content["is_bullet"] and not slots["bullet_heading_lines"] and not slots["bullet_body_lines"]
    heading_lines = 0 if single_body_layout else slots["bullet_heading_lines"] if content["is_bullet"] else slots["heading_lines"]
    body_lines = slots["description_lines"] if single_body_layout else slots["bullet_body_lines"] if content["is_bullet"] else slots["description_lines"]
    marker = "• " if content["is_bullet"] else ""
    if heading_lines == 0:
        heading = ""
        body_text = " ".join(value for value in (str(content["heading"]), str(content["body"])) if value).strip()
    else:
        heading = _line_spec(str(content["heading"]), heading_lines)
        body_text = str(content["body"])
    body = _line_spec(body_text, body_lines)
    return (
        "РОВНО ОДНА МЫСЛЬ НА СЛАЙД. Единственный разрешённый видимый текст ниже; "
        "служебные названия полей и эти инструкции не печатай.\n"
        f"ЗАГОЛОВОК ({heading_lines} {_line_label(heading_lines)}): {marker}{heading}\n"
        f"ОПИСАНИЕ ({body_lines} {_line_label(body_lines)}): {body or 'нет'}\n"
        "Сохрани эти переносы строк и эти зоны буквально; если фраза не помещается, "
        "сократи её до более короткой русской формулировки, не перенося блок в другую зону."
    )
