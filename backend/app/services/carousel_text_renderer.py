from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .carousel_pipeline import get_design_profile, normalize_design_image


FONT_CANDIDATES = {
    "regular": (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ),
    "bold": (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ),
}


def _font_path(weight: str) -> str:
    for candidate in FONT_CANDIDATES[weight]:
        if Path(candidate).is_file():
            return candidate
    raise RuntimeError(f"Не найден системный шрифт для веса {weight}")


def _font(size: int, *, bold: bool) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(_font_path("bold" if bold else "regular"), size)


def _layout_tokens(text: str | None) -> list[str]:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    # ponytail: keep one-letter Russian words attached to the next word; replace with
    # a full line-breaking engine only if typography rules become more complex.
    clean = re.sub(
        r"(?iu)(?<!\S)([авикосуя])\s+(?=\S)",
        lambda match: f"{match.group(1)}\u00a0",
        clean,
    )
    return clean.split(" ") if clean else []


def wrap_text(draw: ImageDraw.ImageDraw, text: str | None, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    tokens = _layout_tokens(text)
    lines: list[str] = []
    current = ""
    for token in tokens:
        candidate = token if not current else f"{current} {token}"
        if current and draw.textlength(candidate, font=font) > max_width:
            lines.append(current)
            current = token
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    max_width: int,
    max_height: int,
    start_size: int,
    min_size: int,
    bold: bool,
) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    last: tuple[ImageFont.FreeTypeFont, list[str], int] | None = None
    for size in range(start_size, min_size - 1, -2):
        font = _font(size, bold=bold)
        lines = wrap_text(draw, text, font, max_width)
        line_height = round(size * 1.22)
        candidate = (font, lines, line_height)
        last = candidate
        if lines and len(lines) * line_height <= max_height:
            return candidate
    if last is None:
        raise ValueError("Текст для слайда не может быть пустым")
    return last


def _draw_centered_block(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    line_height: int,
    box: tuple[int, int, int, int],
    fill: tuple[int, int, int, int],
) -> None:
    left, top, right, bottom = box
    total_height = len(lines) * line_height
    y = top + max(0, (bottom - top - total_height) // 2)
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        x = left + max(0, (right - left - (bbox[2] - bbox[0])) // 2)
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height


def render_text_overlay(
    source_path: str,
    output_path: str,
    *,
    text: str,
    cta: str | None,
    design_format: str,
) -> str:
    profile = get_design_profile(design_format)
    with Image.open(source_path) as source:
        base = source.convert("RGBA")

    width, height = profile["width"], profile["height"]
    if base.size != (width, height):
        normalized_path = f"{output_path}.normalized.png"
        normalize_design_image(source_path, normalized_path, design_format)
        with Image.open(normalized_path) as normalized:
            base = normalized.convert("RGBA")
        Path(normalized_path).unlink(missing_ok=True)

    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    margin = 78 if design_format == "carousel" else 92
    top = 100 if design_format == "carousel" else 150
    bottom = height - (100 if design_format == "carousel" else 150)
    panel = (margin, top, width - margin, bottom)
    draw.rounded_rectangle(panel, radius=42, fill=(255, 255, 255, 238), outline=(20, 34, 48, 185), width=3)
    accent_x = margin + 46
    draw.rounded_rectangle((accent_x, top + 44, accent_x + 14, top + 150), radius=7, fill=(72, 150, 82, 255))

    inner_left = margin + 74
    inner_right = width - margin - 74
    cta_lines: list[str] = []
    cta_font = None
    cta_line_height = 0
    cta_box = None
    if cta and cta.strip():
        cta_box_height = 190 if design_format == "carousel" else 250
        cta_box = (inner_left, bottom - cta_box_height - 52, inner_right, bottom - 52)
        draw.rounded_rectangle(cta_box, radius=28, fill=(232, 249, 221, 245), outline=(72, 150, 82, 210), width=2)
        cta_font, cta_lines, cta_line_height = _fit_text(
            draw,
            cta,
            max_width=cta_box[2] - cta_box[0] - 46,
            max_height=cta_box_height - 34,
            start_size=42 if design_format == "carousel" else 46,
            min_size=22,
            bold=True,
        )
        _draw_centered_block(
            draw,
            cta_lines,
            cta_font,
            cta_line_height,
            (cta_box[0] + 22, cta_box[1] + 16, cta_box[2] - 22, cta_box[3] - 16),
            (20, 34, 48, 255),
        )

    text_bottom = cta_box[1] - 42 if cta_box else bottom - 72
    main_font, main_lines, main_line_height = _fit_text(
        draw,
        text,
        max_width=inner_right - inner_left,
        max_height=text_bottom - top - 90,
        start_size=82 if design_format == "carousel" else 88,
        min_size=28,
        bold=True,
    )
    _draw_centered_block(
        draw,
        main_lines,
        main_font,
        main_line_height,
        (inner_left, top + 90, inner_right, text_bottom),
        (20, 34, 48, 255),
    )

    composed = Image.alpha_composite(base, overlay).convert("RGB")
    temporary_path = Path(f"{output_path}.text.tmp.png")
    composed.save(temporary_path, format="PNG", optimize=True)
    temporary_path.replace(output_path)
    return output_path
