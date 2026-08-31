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


def normalize_master_text(text: str | None) -> str:
    """Normalize list markers before the text is split into slide-sized blocks."""
    value = str(text or "").strip()
    value = re.sub(r"(?m)^\s*\d+[.)]\s*", "• ", value)
    value = re.sub(r"(?<!\w)\d+[-–](?:е|ое|ый|ий|ая|ое)\b[.:]?\s*[—-]?\s*", "• ", value, flags=re.IGNORECASE)
    value = re.sub(r"[ \t]+", " ", value)
    return re.sub(r"\n\s*\n+", "\n\n", value).strip()


def _split_sentences(text: str) -> list[str]:
    return [
        part.strip()
        for part in re.split(r"(?<=[.!?…])\s+(?=[А-ЯЁ«„])", text)
        if part.strip()
    ]


def _split_bullet_blocks(text: str) -> list[str]:
    marked = re.sub(r"\s*•\s*", "\n• ", text).strip()
    blocks = []
    for line in marked.splitlines():
        value = line.strip()
        if value:
            blocks.append(value)
    return blocks or _split_sentences(text)


def _split_longest_block(blocks: list[str]) -> bool:
    if not blocks:
        return False
    index = max(range(len(blocks)), key=lambda item: len(blocks[item].split()))
    block = blocks[index]
    prefix = "• " if block.startswith("• ") else ""
    body = block[2:].strip() if prefix else block
    sentences = _split_sentences(body)
    if len(sentences) > 1:
        midpoint = max(1, len(sentences) // 2)
        first = " ".join(sentences[:midpoint])
        second = " ".join(sentences[midpoint:])
        blocks[index:index + 1] = [prefix + first, second]
        return True
    words = body.split()
    if len(words) < 2:
        return False
    midpoint = max(1, len(words) // 2)
    blocks[index:index + 1] = [prefix + " ".join(words[:midpoint]), " ".join(words[midpoint:])]
    return True


def split_master_text(text: str, slide_count: int, max_words: int = 20) -> list[str]:
    clean = normalize_master_text(text)
    if not clean:
        raise ValueError("Текст карусели не может быть пустым")
    count = max(1, min(5, int(slide_count or 1)))
    words = clean.split()
    required_count = math.ceil(len(words) / max(1, int(max_words)))
    count = min(5, max(count, required_count))
    blocks = _split_bullet_blocks(clean)
    while len(blocks) < count and _split_longest_block(blocks):
        pass
    if len(blocks) <= count:
        return blocks

    parts = []
    current = []
    remaining_words = sum(len(block.split()) for block in blocks)
    remaining_groups = count
    for block in blocks:
        block_words = len(block.split())
        target = math.ceil(remaining_words / remaining_groups)
        current_words = len(" ".join(current).split())
        if current and current_words + block_words > target and remaining_groups > 1:
            parts.append(" ".join(current))
            remaining_words -= current_words
            remaining_groups -= 1
            current = []
        current.append(block)
    if current:
        parts.append(" ".join(current))
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


def build_master_image_prompt(image_instructions: str | None = None) -> str:
    prompt = (
        "Общий визуальный мастер-промт всей серии: выдерживай один визуальный язык, "
        "палитру, типографическую и композиционную логику на всех слайдах; "
        "изменяй только визуальную сцену, которая поддерживает смысл конкретного слайда."
    )
    instructions = (image_instructions or "").strip()
    return f"{prompt} Дополнительные инструкции пользователя: {instructions}" if instructions else prompt


def build_slide_prompts(
    master_text: str,
    slide_count: int,
    platform: str,
    cta: str,
    design_format: str = "carousel",
    image_instructions: str | None = None,
) -> list[str]:
    profile = get_design_profile(design_format)
    master_prompt = build_master_image_prompt(image_instructions)
    parts = split_master_text(master_text, min(slide_count, profile["max_slides"]), profile["max_words"])
    prompts = []
    for index, part in enumerate(parts, start=1):
        final_cta = cta if index == len(parts) else ""
        slide_text = part.strip()
        safe_cta = limit_words(final_cta, 8)
        prompts.append(
            "Создай один готовый финальный слайд формата {format_name} размером ровно {width}x{height} px, "
            "соотношение сторон {ratio}, для {platform}. "
            "{master_prompt} "
            "Референсы — главный источник визуального стиля: сохрани их фон, палитру, контраст, "
            "типографическую и композиционную логику, включая тёмный фон, если он есть в референсе. "
            "Сделай полностью готовое изображение: весь текст отрисуй непосредственно внутри него. "
            "Основной текст выведи дословно, "
            "без перевода, сокращений, перефразирования и добавления новых слов: «{text}». "
            "Используй единый шрифт и единый стиль текста на всей серии; не разрывай слова и не оставляй "
            "одиночные буквы на конце строки. Не добавляй никакого текста, кроме указанного основного текста и CTA. "
            "Не используй нумерованные списки и префиксы «1.», «2.», «3.»; если нужен список, используй маркер «•». "
            "Размести весь текст слайда целиком: не обрывай предложения и не опускай слова; "
            "если текста много, уменьши размер шрифта и добавь строки, сохранив читаемость. "
            "Не добавляй логотипы, водяные знаки или псевдотекст. "
            "{cta}".format(
                format_name="карусели" if design_format == "carousel" else "сторис",
                width=profile["width"],
                height=profile["height"],
                ratio=profile["ratio"],
                platform=platform,
                master_prompt=master_prompt,
                text=slide_text,
                cta=(
                    "В нижней части слайда отрисуй CTA дословно, без изменений: «{cta}»."
                    .format(cta=safe_cta)
                    if safe_cta
                    else "CTA не добавляй."
                ),
            )
        )
    return prompts


def build_package_prompts(
    master_text: str,
    slide_count: int,
    design_format: str,
    platforms: list[str],
    ctas: dict[str, str],
    image_instructions: str | None = None,
) -> tuple[list[str], dict[str, str]]:
    shared = build_slide_prompts(
        master_text,
        slide_count,
        "всех социальных сетей",
        "",
        design_format,
        image_instructions,
    )
    finals = {
        platform: build_slide_prompts(
            master_text,
            slide_count,
            platform,
            ctas.get(platform, ""),
            design_format,
            image_instructions,
        )[-1]
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
