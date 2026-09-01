import os
import re
import math
from pathlib import Path

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
    value = re.sub(
        r"(?m)^\s*\d+[.)]\s*",
        lambda match: "" if match.start() == 0 else "• ",
        value,
    )
    value = re.sub(r"(?<=[.!?…])\s+\d+[.)]\s+", "\n• ", value)
    value = re.sub(
        r"(?<=[.!?…])\s+(?:первый|второй|третий|четвёртый|четвертый)"
        r"(?:\s+(?:вариант|способ|пункт))?\s*[—-]\s*",
        "\n• ",
        value,
        flags=re.IGNORECASE,
    )
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
    if "•" not in text:
        return _split_sentences(text)
    marked = re.sub(r"\s*•\s*", "\n• ", text).strip()
    blocks = []
    for line in marked.splitlines():
        value = line.strip()
        if value:
            blocks.append(value)
    return blocks or _split_sentences(text)


def _split_long_bullet_thoughts(blocks: list[str]) -> list[str]:
    result = []
    for block in blocks:
        if not block.startswith("• "):
            result.append(block)
            continue
        sentences = _split_sentences(block[2:].strip())
        if len(sentences) <= 2:
            result.append(block)
            continue
        result.extend("• " + " ".join(sentences[index:index + 2]) for index in range(0, len(sentences), 2))
    return result


def _split_longest_block(blocks: list[str]) -> bool:
    if not blocks:
        return False
    index = max(range(len(blocks)), key=lambda item: len(blocks[item].split()))
    block = blocks[index]
    if block.startswith("• "):
        return False
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
    blocks = _split_long_bullet_thoughts(_split_bullet_blocks(clean))
    # One sentence/list item is one thought; never merge short independent thoughts.
    count = max(count, len(blocks))
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


def output_dir(draft_id: int) -> Path:
    return Path(os.getenv("OUTPUT_DIR", "/app/database/media/output")) / "carousels" / str(draft_id)
