import json
import re
from typing import Any

from .carousel_layout import build_slide_text_content
from .carousel_pipeline import get_design_profile


DEFAULT_PALETTE = {
    "background": "#111827",
    "surface": "#1f2937",
    "text": "#f9fafb",
    "muted": "#d1d5db",
    "accent": "#f59e0b",
}
DEFAULT_BOXES = {
    "carousel": {
        "heading": (108, 170, 864, 270),
        "body": (108, 520, 864, 470),
        "cta": (108, 1165, 864, 100),
    },
    "story": {
        "heading": (108, 260, 864, 330),
        "body": (108, 730, 864, 700),
        "cta": (108, 1745, 864, 110),
    },
}


def _contract_data(contract: str | None) -> dict[str, Any]:
    try:
        value = json.loads(contract or "")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name)
    return value if isinstance(value, dict) else {}


def _value(section: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in section and section[name] not in (None, ""):
            return section[name]
    return None


def _pixels(value: Any, total: int, fallback: int) -> int:
    if isinstance(value, str) and value.strip().endswith("%"):
        try:
            return round(total * float(value.strip()[:-1]) / 100)
        except ValueError:
            return fallback
    try:
        return round(float(value))
    except (TypeError, ValueError):
        return fallback


def _measure(section: dict[str, Any], total: int, *names: str) -> int | None:
    for name in names:
        if name not in section or section[name] in (None, ""):
            continue
        value = section[name]
        if name.endswith("_percent") and not isinstance(value, str):
            value = f"{value}%"
        return _pixels(value, total, 0)
    return None


def _box(section: dict[str, Any], default: tuple[int, int, int, int], width: int, height: int) -> dict[str, int]:
    default_x, default_y, default_width, default_height = default
    x_value = _measure(section, width, "x", "left", "left_percent")
    y_value = _measure(section, height, "y", "top", "top_percent")
    width_value = _measure(section, width, "width", "width_percent")
    height_value = _measure(section, height, "height", "height_percent")
    x = x_value if x_value is not None else default_x
    y = y_value if y_value is not None else default_y
    box_width = width_value if width_value is not None else default_width
    box_height = height_value if height_value is not None else default_height
    right = _value(section, "right", "right_percent")
    bottom = _value(section, "bottom", "bottom_percent")
    if right is not None and x_value is None:
        x = width - _pixels(f"{right}%" if isinstance(right, (int, float)) else right, width, 0) - box_width
    if bottom is not None and y_value is None:
        y = height - _pixels(f"{bottom}%" if isinstance(bottom, (int, float)) else bottom, height, 0) - box_height
    return {"x": max(0, x), "y": max(0, y), "width": max(1, box_width), "height": max(1, box_height)}


def _color(value: Any, fallback: str) -> str:
    candidate = str(value or "").strip()
    return candidate if re.fullmatch(r"#[0-9a-fA-F]{6}", candidate) else fallback


def _palette(data: dict[str, Any]) -> dict[str, str]:
    source = _section(data, "palette")
    return {
        name: _color(_value(source, name, f"{name}_color", f"{name}Color"), fallback)
        for name, fallback in DEFAULT_PALETTE.items()
    }


def _font_name(data: dict[str, Any]) -> str:
    value = _value(_section(data, "typography"), "font_family", "fontFamily", "family")
    candidate = str(value or "Inter").strip()
    return candidate if re.fullmatch(r"[A-Za-z][A-Za-z0-9 ]{1,40}", candidate) else "Inter"


def _font_size(data: dict[str, Any], name: str, fallback: int) -> int:
    typography = _section(data, "typography")
    value = _value(typography, name, f"{name}_size", f"{name}Size")
    try:
        return max(18, min(160, int(value)))
    except (TypeError, ValueError):
        return fallback


def _fit_font_size(text: str, box_width: int, base: int) -> int:
    longest_line = max((len(line) for line in (text or "").splitlines()), default=1)
    if longest_line <= 1:
        return base
    return max(18, min(base, int(box_width / (longest_line * 0.56))))


def _text_align(section: dict[str, Any]) -> str:
    value = str(_value(section, "align", "alignment", "horizontal_align", "text_align") or "left").lower()
    return {"center": "center", "right": "right", "право": "right", "центр": "center"}.get(value, "left")


def _text_element(
    element_id: str,
    box: dict[str, int],
    content: str,
    font: str,
    size: int,
    color: str,
    weight: int,
    align: str,
) -> dict[str, Any]:
    return {
        "id": element_id,
        "type": "text",
        **box,
        "content": content,
        "fontFamily": font,
        "fontSize": size,
        "fontWeight": weight,
        "lineHeight": 1.15,
        "color": color,
        "textAlign": align,
        "verticalAlign": "top",
        "wordBreak": False,
    }


def build_carousel_render_request(
    part: str,
    contract: str | None,
    design_format: str,
    cta: str = "",
) -> tuple[dict[str, Any], dict[str, str]]:
    profile = get_design_profile(design_format)
    width, height = profile["width"], profile["height"]
    data = _contract_data(contract)
    palette = _palette(data)
    boxes = DEFAULT_BOXES[design_format]
    heading_box = _box(_section(data, "heading"), boxes["heading"], width, height)
    body_box = _box(_section(data, "body"), boxes["body"], width, height)
    cta_box = _box(_section(data, "cta"), boxes["cta"], width, height)
    content = build_slide_text_content(part, contract, design_format)
    heading = str(content["heading"])
    if content["is_bullet"] and heading:
        heading = f"• {heading}"
    font = _font_name(data)
    heading_size = _fit_font_size(heading, heading_box["width"], _font_size(data, "heading", 72))
    body_size = _fit_font_size(str(content["body"]), body_box["width"], _font_size(data, "body", 38))
    cta_size = _fit_font_size(cta, cta_box["width"], _font_size(data, "cta", 28))
    elements: list[dict[str, Any]] = [{
        "id": "background",
        "type": "shape",
        "x": 0,
        "y": 0,
        "width": width,
        "height": height,
        "backgroundColor": palette["background"],
    }]
    accent_line = {"x": heading_box["x"], "y": max(24, heading_box["y"] - 28), "width": min(220, heading_box["width"]), "height": 8}
    elements.append({"id": "accent-line", "type": "shape", **accent_line, "backgroundColor": palette["accent"], "borderRadius": 4})
    if heading:
        elements.append(_text_element("heading", heading_box, heading, font, heading_size, palette["text"], 700, _text_align(_section(data, "heading"))))
    if content["body"]:
        elements.append(_text_element("body", body_box, str(content["body"]), font, body_size, palette["muted"], 400, _text_align(_section(data, "body"))))
    if cta:
        elements.append({"id": "cta-background", "type": "shape", **cta_box, "backgroundColor": palette["accent"], "borderRadius": 18})
        elements.append(_text_element("cta", cta_box, cta, font, cta_size, palette["background"], 700, _text_align(_section(data, "cta"))))
    return {"width": width, "height": height, "elements": elements}, {}
