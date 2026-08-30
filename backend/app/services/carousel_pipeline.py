import os
import re
import math
from pathlib import Path

from PIL import Image, ImageOps
from sqlalchemy.orm import Session

from .. import models
from ..utils.media_utils import _resolve_media_file_path

SUPPORTED_PLATFORMS = ("instagram", "tiktok", "vk", "telegram")
DESIGN_PROFILES = {
    "carousel": {"width": 1080, "height": 1350, "ratio": "4:5", "min_words": 5, "max_words": 20, "max_slides": 5},
    "story": {"width": 1080, "height": 1920, "ratio": "9:16", "min_words": 3, "max_words": 12, "max_slides": 5},
}


def get_design_profile(design_format: str = "carousel") -> dict:
    try:
        return DESIGN_PROFILES[design_format]
    except KeyError as exc:
        raise ValueError(f"Неизвестный формат дизайна: {design_format}") from exc


def limit_words(text: str, max_words: int) -> str:
    return " ".join(re.findall(r"\S+", (text or "").strip())[:max_words]).strip()


def split_master_text(text: str, slide_count: int, max_words: int = 20) -> list[str]:
    clean = re.sub(r"\s+", " ", (text or "")).strip()
    if not clean:
        raise ValueError("Текст карусели не может быть пустым")
    count = max(1, min(5, int(slide_count or 1)))
    words = clean.split()
    required_count = math.ceil(len(words) / max(1, int(max_words)))
    count = min(5, max(count, required_count))
    base_size, remainder = divmod(len(words), count)
    parts = []
    offset = 0
    for index in range(count):
        size = base_size + (1 if index < remainder else 0)
        if size:
            parts.append(" ".join(words[offset:offset + size]))
            offset += size
    return parts


def suggest_slide_count(text: str, design_format: str = "carousel") -> int:
    profile = get_design_profile(design_format)
    word_count = len(re.findall(r"\S+", (text or "").strip()))
    if word_count <= profile["max_words"]:
        return 1
    return max(1, min(profile["max_slides"], math.ceil(word_count / profile["max_words"])))


def suggest_package_slide_count(text: str) -> int:
    """Pick one shared count that fits both carousel and story limits."""
    return max(suggest_slide_count(text, "carousel"), suggest_slide_count(text, "story"))


def build_slide_prompts(
    master_text: str,
    slide_count: int,
    platform: str,
    cta: str,
    design_format: str = "carousel",
) -> list[str]:
    profile = get_design_profile(design_format)
    parts = split_master_text(master_text, min(slide_count, profile["max_slides"]), profile["max_words"])
    prompts = []
    for index, part in enumerate(parts, start=1):
        final_cta = cta if index == len(parts) else ""
        slide_text = limit_words(part, profile["max_words"])
        safe_cta = limit_words(final_cta, 8)
        prompts.append(
            "Создай один слайд формата {format_name} размером ровно {width}x{height} px, "
            "соотношение сторон {ratio}, для {platform}. "
            "Сохрани стиль референсов и сделай чистую композицию с большим свободным местом "
            "под точный текстовый слой. Генератор создаёт только фон и визуальные элементы. "
            "Не рисуй и не добавляй никакие буквы, слова, цифры, подписи, логотипы, водяные знаки "
            "или псевдотекст: весь русский текст будет наложен программно одним шрифтом после генерации. "
            "Смысл слайда для визуального решения (текст НЕ рендерить): «{text}». "
            "На слайде должно быть не больше {max_words} слов после наложения текста. "
            "{cta}".format(
                format_name="карусели" if design_format == "carousel" else "сторис",
                width=profile["width"],
                height=profile["height"],
                ratio=profile["ratio"],
                platform=platform,
                text=slide_text,
                max_words=profile["max_words"],
                cta=("Оставь место под CTA в нижней части панели; сам CTA НЕ рендерить." if safe_cta else "CTA не добавляй."),
            )
        )
    return prompts


def build_package_prompts(
    master_text: str,
    slide_count: int,
    design_format: str,
    platforms: list[str],
    ctas: dict[str, str],
) -> tuple[list[str], dict[str, str]]:
    shared = build_slide_prompts(master_text, slide_count, "всех социальных сетей", "", design_format)
    finals = {
        platform: build_slide_prompts(master_text, slide_count, platform, ctas.get(platform, ""), design_format)[-1]
        for platform in platforms
    }
    return shared[:-1], finals


def normalize_design_image(source_path: str, output_path: str, design_format: str = "carousel") -> str:
    profile = get_design_profile(design_format)
    with Image.open(source_path) as source:
        image = ImageOps.fit(source.convert("RGB"), (profile["width"], profile["height"]), method=Image.Resampling.LANCZOS)
    temporary_path = f"{output_path}.tmp.png"
    image.save(temporary_path, format="PNG", optimize=True)
    Path(temporary_path).replace(output_path)
    return output_path


def resolve_reference_paths(
    db: Session,
    user_id: int,
    reference_ids: list[int],
    project_id: int | None = None,
    design_format: str = "carousel",
) -> list[str]:
    design_query = db.query(models.DesignReference).filter(
        models.DesignReference.user_id == user_id,
        models.DesignReference.design_format == design_format,
    )
    if project_id is not None:
        design_query = design_query.filter(models.DesignReference.project_id == int(project_id))
    if reference_ids:
        design_query = design_query.filter(models.DesignReference.id.in_([int(item) for item in reference_ids]))
    design_paths = []
    for item in design_query.order_by(models.DesignReference.created_at.desc()).limit(8).all():
        value = (item.file_path or "").strip()
        path = value if value.startswith(("http://", "https://")) else _resolve_media_file_path(
            value, media_kind="design-references"
        )
        if path and path not in design_paths:
            design_paths.append(path)
    if design_paths:
        return design_paths

    query = db.query(models.ThumbnailReference).filter(models.ThumbnailReference.user_id == user_id)
    if reference_ids:
        query = query.filter(models.ThumbnailReference.id.in_([int(item) for item in reference_ids]))
    else:
        query = query.filter(models.ThumbnailReference.kind.in_(["horizontal", "vertical", "both"]))
    paths = []
    for reference in query.order_by(models.ThumbnailReference.created_at.desc()).limit(8).all():
        path = _resolve_media_file_path(reference.file_path, media_kind="thumbnails")
        if path and path not in paths:
            paths.append(path)
    if not paths:
        raise ValueError("Добавьте хотя бы один референс для стиля карусели")
    return paths


def output_dir(draft_id: int) -> Path:
    return Path(os.getenv("OUTPUT_DIR", "/app/database/media/output")) / "carousels" / str(draft_id)
