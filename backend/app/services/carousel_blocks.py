"""Block-based carousel deck: schema, validation, LLM prompt and fallbacks.

A deck is a list of typed slides (cover, checklist, table, steps, comparison,
stat, quote, text, cta). The LLM chooses block types and fills them with
structured content; Python validates every word limit so the HTML renderer
never receives content that cannot fit a slide.
"""

import json
import re

from .carousel_copy import PLATFORM_COPY_RULES, is_russian_text
from .carousel_pipeline import normalize_master_text

DECK_LIMITS = {
    "min_slides": 3,
    "max_slides": 7,
    "kicker_words": 3,
    "title_words": 8,
    "subtitle_words": 20,
    "body_words": 64,
    "checklist_min_items": 3,
    "checklist_max_items": 6,
    "checklist_item_words": 12,
    "table_min_columns": 2,
    "table_max_columns": 3,
    "table_min_rows": 2,
    "table_max_rows": 5,
    "table_cell_words": 6,
    "table_column_words": 3,
    "steps_min_items": 3,
    "steps_max_items": 5,
    "steps_item_words": 14,
    "comparison_min_items": 2,
    "comparison_max_items": 4,
    "comparison_item_words": 10,
    "comparison_side_words": 3,
    "stat_value_words": 4,
    "stat_caption_words": 16,
    "stat_body_words": 36,
    "quote_words": 28,
    "quote_author_words": 3,
    "cta_words": 8,
}
BLOCK_TYPES = ("cover", "text", "checklist", "table", "steps", "comparison", "stat", "quote", "cta")
CONTENT_TYPES = ("text", "checklist", "table", "steps", "comparison", "stat", "quote")
STRING_FIELDS = ("kicker", "title", "subtitle", "body", "value", "caption", "text", "author",
                 "left_title", "right_title", "cta")
LIST_FIELDS = ("items", "left_items", "right_items")
ITEM_LIMITS = {
    "items": ("checklist_item_words", "checklist_min_items", "checklist_max_items", "checklist"),
    "left_items": ("comparison_item_words", "comparison_min_items", "comparison_max_items", "сравнение"),
    "right_items": ("comparison_item_words", "comparison_min_items", "comparison_max_items", "сравнение"),
}
SIDE_TITLE_LIMIT = "comparison_side_words"


def _words(value: str) -> int:
    return len(value.split())


def polish_text(value: str) -> str:
    """Typographic hygiene: real quotes, dashes, ellipsis, no markdown."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(r"[*#_`]+", "", text)
    text = re.sub(r"\.{3}|…", "…", text)
    text = re.sub(r"(?<=\s)-(?=\s)", "— ", text)
    text = re.sub(r'"([^"]*)"', "«\\1»", text)
    return re.sub(r"\s+", " ", text).strip()


def _require_string(slide_type: str, field: str, value, limit_key: str, cyrillic: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Слайд «{slide_type}»: поле {field} должно быть строкой")
    text = polish_text(value)
    if not text:
        raise ValueError(f"Слайд «{slide_type}»: поле {field} пустое")
    if re.search(r"[A-Za-z]", text):
        raise ValueError(f"Слайд «{slide_type}»: поле {field} содержит латиницу")
    if cyrillic and not is_russian_text(text):
        raise ValueError(f"Слайд «{slide_type}»: поле {field} без русского текста")
    limit = DECK_LIMITS[limit_key]
    if _words(text) > limit:
        raise ValueError(f"Слайд «{slide_type}»: поле {field} длиннее {limit} слов")
    return text


def _require_items(slide_type: str, field: str, value, word_limit: int, low: int, high: int) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"Слайд «{slide_type}»: поле {field} должно быть непустым списком")
    if not (low <= len(value) <= high):
        raise ValueError(f"Слайд «{slide_type}»: поле {field} должно содержать {low}–{high} пунктов")
    result = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"Слайд «{slide_type}»: пункты поля {field} должны быть строками")
        text = polish_text(item)
        # списки рисуются с бейджами/маркерами — ручная нумерация пунктов задваивается
        text = re.sub(r"^\s*\d+\s*[.)]\s*", "", text)
        if not text or re.search(r"[A-Za-z]", text) or not is_russian_text(text):
            raise ValueError(f"Слайд «{slide_type}»: пункт поля {field} не русский текст")
        if _words(text) > word_limit:
            raise ValueError(f"Слайд «{slide_type}»: пункт поля {field} длиннее {word_limit} слов")
        result.append(text)
    folded = [item.casefold() for item in result]
    if len(set(folded)) != len(folded):
        raise ValueError(f"Слайд «{slide_type}»: поле {field} повторяет пункты")
    return result


def _validate_cover(slide: dict) -> dict:
    clean: dict = {"type": "cover"}
    kicker = slide.get("kicker")
    if kicker not in (None, ""):
        clean["kicker"] = _require_string("cover", "kicker", kicker, "kicker_words")
    clean["title"] = _require_string("cover", "title", slide.get("title"), "title_words")
    subtitle = slide.get("subtitle")
    if subtitle not in (None, ""):
        clean["subtitle"] = _require_string("cover", "subtitle", subtitle, "subtitle_words")
    return clean


def _validate_content(slide_type: str, slide: dict) -> dict:
    clean: dict = {"type": slide_type}
    title = slide.get("title")
    if title not in (None, ""):
        clean["title"] = _require_string(slide_type, "title", title, "title_words")
    if slide_type == "text":
        if "title" not in clean:
            raise ValueError("Слайд «text»: нужен заголовок")
        clean["body"] = _require_string("text", "body", slide.get("body"), "body_words")
    elif slide_type == "checklist":
        if "title" not in clean:
            raise ValueError("Слайд «checklist»: нужен заголовок")
        limits = DECK_LIMITS
        clean["items"] = _require_items(
            "checklist", "items", slide.get("items"),
            limits["checklist_item_words"], limits["checklist_min_items"], limits["checklist_max_items"],
        )
    elif slide_type == "table":
        if "title" not in clean:
            raise ValueError("Слайд «table»: нужен заголовок")
        columns = _require_items(
            "table", "columns", slide.get("columns"),
            DECK_LIMITS["table_column_words"],
            DECK_LIMITS["table_min_columns"], DECK_LIMITS["table_max_columns"],
        )
        clean["columns"] = columns
        rows = slide.get("rows")
        if not isinstance(rows, list) or not (DECK_LIMITS["table_min_rows"] <= len(rows) <= DECK_LIMITS["table_max_rows"]):
            raise ValueError(f"Слайд «table»: строк должно быть {DECK_LIMITS['table_min_rows']}–{DECK_LIMITS['table_max_rows']}")
        clean_rows = []
        for row in rows:
            if not isinstance(row, list) or len(row) != len(columns):
                raise ValueError("Слайд «table»: в каждой строке должно быть столько ячеек, сколько колонок")
            clean_rows.append([
                _require_items("table", "ячейка", [cell], DECK_LIMITS["table_cell_words"], 1, 1)[0]
                for cell in row
            ])
        clean["rows"] = clean_rows
    elif slide_type == "steps":
        if "title" not in clean:
            raise ValueError("Слайд «steps»: нужен заголовок")
        clean["items"] = _require_items(
            "steps", "items", slide.get("items"),
            DECK_LIMITS["steps_item_words"], DECK_LIMITS["steps_min_items"], DECK_LIMITS["steps_max_items"],
        )
    elif slide_type == "comparison":
        if "title" not in clean:
            raise ValueError("Слайд «comparison»: нужен заголовок")
        clean["left_title"] = _require_string(
            "comparison", "left_title", slide.get("left_title"), SIDE_TITLE_LIMIT)
        clean["right_title"] = _require_string(
            "comparison", "right_title", slide.get("right_title"), SIDE_TITLE_LIMIT)
        limits = DECK_LIMITS
        clean["left_items"] = _require_items(
            "comparison", "left_items", slide.get("left_items"),
            limits["comparison_item_words"], limits["comparison_min_items"], limits["comparison_max_items"])
        clean["right_items"] = _require_items(
            "comparison", "right_items", slide.get("right_items"),
            limits["comparison_item_words"], limits["comparison_min_items"], limits["comparison_max_items"])
    elif slide_type == "stat":
        if "title" not in clean:
            raise ValueError("Слайд «stat»: нужен заголовок")
        value = _require_string("stat", "value", slide.get("value"), "stat_value_words", cyrillic=False)
        clean["value"] = value
        clean["caption"] = _require_string("stat", "caption", slide.get("caption"), "stat_caption_words")
        body = slide.get("body")
        if body not in (None, ""):
            clean["body"] = _require_string("stat", "body", body, "stat_body_words")
    elif slide_type == "quote":
        clean["text"] = _require_string("quote", "text", slide.get("text"), "quote_words")
        author = slide.get("author")
        if author not in (None, ""):
            clean["author"] = _require_string("quote", "author", author, "quote_author_words")
    return clean


def validate_deck(raw: object, cta: str) -> list[dict]:
    """Validate an LLM deck against block limits; returns cleaned slides."""
    if not isinstance(raw, dict) or not isinstance(raw.get("slides"), list):
        raise ValueError("Дека должна быть объектом со списком slides")
    slides = raw["slides"]
    limits = DECK_LIMITS
    if not (limits["min_slides"] <= len(slides) <= limits["max_slides"]):
        raise ValueError(f"В деке должно быть {limits['min_slides']}–{limits['max_slides']} слайдов")
    cleaned = []
    for index, slide in enumerate(slides):
        if not isinstance(slide, dict):
            raise ValueError(f"Слайд {index + 1} должен быть объектом")
        slide_type = slide.get("type")
        if slide_type not in BLOCK_TYPES:
            raise ValueError(f"Слайд {index + 1}: неизвестный тип «{slide_type}»")
        if index == 0 and slide_type != "cover":
            raise ValueError("Первый слайд должен быть обложкой")
        if index == len(slides) - 1 and slide_type != "cta":
            raise ValueError("Последний слайд должен быть CTA")
        if index not in (0, len(slides) - 1) and slide_type not in CONTENT_TYPES:
            raise ValueError(
                f"Слайд {index + 1}: тип «{slide_type}» допустим только последним слайдом (CTA)"
            )
        if slide_type == "cover":
            cleaned.append(_validate_cover(slide))
        elif slide_type == "cta":
            cleaned.append({"type": "cta", "cta": cta})
        else:
            cleaned.append(_validate_content(slide_type, slide))
    body_types = [slide["type"] for slide in cleaned[1:-1]]
    if len(set(body_types)) < min(2, len(body_types)):
        raise ValueError("Содержательные слайды должны использовать минимум два разных блока")
    return cleaned


def parse_deck(raw: str | None, cta: str) -> list[dict]:
    text = str(raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("Модель вернула не JSON") from exc
    return validate_deck(payload, cta)


def build_deck_prompt(master_text: str, platform: str, slide_count: int, cta: str) -> list[dict]:
    style = PLATFORM_COPY_RULES.get(platform, "короткая ясная подача для социальной сети")
    limits = DECK_LIMITS
    content_count = max(1, int(slide_count) - 2)
    example = {
        "slides": [
            {"type": "cover", "kicker": "Разбор", "title": "Главная мысль обложки", "subtitle": "Одно предложение с конкретикой"},
            {"type": "stat", "title": "Заголовок слайда", "value": "72%", "caption": "Пояснение к цифре из источника"},
            {"type": "checklist", "title": "Заголовок слайда", "items": ["Пункт до 10 слов", "Пункт до 10 слов", "Пункт до 10 слов"]},
            {"type": "cta", "cta": ""},
        ]
    }
    rules = (
        f"Площадка: {platform}. Стиль подачи: {style}.\n\n"
        f"Исходный текст:\n{master_text}\n\n"
        "Собери карусель из типовых блоков. Верни JSON вида {\"slides\": [...]}, где каждый слайд — один из типов:\n"
        "- cover: {type, kicker?, title, subtitle?} — обложка, сильная первая фраза;\n"
        "- text: {type, title, body} — мысль, которую лучше раскрыть абзацем;\n"
        "- checklist: {type, title, items} — признаки, ошибки, правила, что сделать;\n"
        "- table: {type, title, columns, rows} — сравнение по параметрам, колонок 2–3, ячейки очень короткие;\n"
        "- steps: {type, title, items} — порядок действий по шагам;\n"
        "- comparison: {type, title, left_title, right_title, left_items, right_items} — «до/после», «так/не так»;\n"
        "- stat: {type, title, value, caption} — одна яркая цифра или факт из источника;\n"
        "- quote: {type, text, author?} — цитата из исходного текста;\n"
        "- cta: {type, cta: \"\"} — последний слайд, текст CTA подставит бэкенд.\n\n"
        "Жесткие требования:\n"
        f"- Количество слайдов — ровно {max(3, min(7, int(slide_count)))}: обложка, {content_count} содержательных, CTA.\n"
        f"- Содержательные слайды — минимум два РАЗНЫХ типа; выбирай блок по смыслу, а не подряд одинаковые.\n"
        f"- Заголовок до {limits['title_words']} слов, kicker до {limits['kicker_words']}, subtitle до {limits['subtitle_words']}, body до {limits['body_words']}.\n"
        f"- checklist: {limits['checklist_min_items']}–{limits['checklist_max_items']} пунктов до {limits['checklist_item_words']} слов; "
        f"steps: {limits['steps_min_items']}–{limits['steps_max_items']} пунктов до {limits['steps_item_words']} слов.\n"
        f"- Ячейки таблицы до {limits['table_cell_words']} слов; пункты сравнения до {limits['comparison_item_words']} слов.\n"
        "- НАПОЛНЯЙ слайды плотно: в subtitle, body и caption — конкретика из источника (цифры, причины, примеры, следствия),"
        " а не общие фразы. stat поддерживает поле body — раскрой цифру абзацем.\n"
        "- Не нумеруй пункты в checklist и steps — бейджи с цифрами рисует дизайн.\n"
        "- Каждый пункт — законченная фраза без обрывов и без висячих слов; не дели одну мысль на два пункта.\n"
        "- Не повторяй одну и ту же мысль на разных слайдах. Пиши только по-русски, без Markdown, без латиницы и ссылок.\n"
        "- Не выдумывай фактов и цифр, которых нет в исходном тексте.\n"
        "- Поля cta оставь пустыми строками. Верни только JSON без пояснений и без блока ```."
    )
    return [
        {"role": "system", "content": "Ты арт-директор соцсетей и редактор. Собираешь карусели из типовых блоков и возвращаешь строгий JSON."},
        {"role": "user", "content": rules + "\n\nПример структуры:\n" + json.dumps(example, ensure_ascii=False, indent=2)},
    ]


def build_deck(llm_client, master_text: str, platform: str, slide_count: int, cta: str) -> list[dict]:
    """LLM deck with retries; raises ValueError if every attempt fails."""
    prompt = build_deck_prompt(master_text, platform, slide_count, cta)
    last_error: ValueError | None = None
    for temperature in (0.5, 0.25):
        try:
            return parse_deck(llm_client._complete(prompt, temperature=temperature), cta)
        except ValueError as exc:
            last_error = exc
    raise ValueError(f"Не удалось собрать деку для {platform}: {last_error}")


def _first_sentence(text: str, limit: int) -> str:
    sentences = [part.strip() for part in re.split(r"(?<=[.!?…])\s+", text) if part.strip()]
    if not sentences:
        return " ".join(text.split()[:limit])
    sentence = sentences[0]
    words = sentence.split()
    return " ".join(words[:limit]) if len(words) > limit else sentence


def build_fallback_deck(master_text: str, slide_count: int, cta: str) -> list[dict]:
    """Deterministic deck when the LLM fails; guaranteed to pass validation."""
    limits = DECK_LIMITS
    text = normalize_master_text(master_text)
    blocks = [block.strip() for block in re.sub(r"\s*•\s*", "\n• ", text).splitlines() if block.strip()]
    bullets = [block[2:].strip() for block in blocks if block.startswith("• ")]
    sentences = []
    for block in blocks:
        if block.startswith("• "):
            continue
        sentences.extend(part.strip() for part in re.split(r"(?<=[.!?…])\s+", block) if part.strip())
    cover_title = _first_sentence(sentences[0] if sentences else text, limits["title_words"])
    cover_subtitle = " ".join(sentences[1].split()[:limits["subtitle_words"]]) if len(sentences) > 1 else ""
    body_sentences = sentences[2:] if len(sentences) > 2 else sentences
    count = max(limits["min_slides"], min(limits["max_slides"], int(slide_count or limits["min_slides"])))
    deck: list[dict] = [{"type": "cover", "title": cover_title}]
    if cover_subtitle:
        deck[0]["subtitle"] = cover_subtitle

    if len(bullets) >= limits["checklist_min_items"]:
        deck.append({"type": "checklist", "title": cover_title, "items": [
            " ".join(item.split()[:limits["checklist_item_words"]])
            for item in bullets[:limits["checklist_max_items"]]
        ]})
        body_sentences = body_sentences or bullets[limits["checklist_max_items"]:]
    content_target = max(1, count - 2)
    chunks: list[list[str]] = [[] for _ in range(content_target)]
    for index, sentence in enumerate(body_sentences):
        chunks[index % content_target].append(sentence)
    for chunk in chunks:
        body = " ".join(chunk)
        deck.append({"type": "text", "title": _first_sentence(body, limits["title_words"]),
                     "body": " ".join(body.split()[:limits["body_words"]])})
    deck.append({"type": "cta", "cta": cta})
    deck = deck[:limits["max_slides"]]
    deck[-1] = {"type": "cta", "cta": cta}
    filler = {"type": "text", "title": cover_title, "body": cover_subtitle or " ".join(body_sentences)}
    while len(deck) < limits["min_slides"]:
        deck.insert(len(deck) - 1, dict(filler))
    return deck


def build_platform_deck(llm_client, master_text: str, platform: str, slide_count: int, cta: str) -> list[dict]:
    try:
        return build_deck(llm_client, master_text, platform, slide_count, cta)
    except ValueError as exc:
        import logging

        logging.getLogger(__name__).warning("Deck generation failed for %s, using fallback: %s", platform, exc)
        return build_fallback_deck(master_text, slide_count, cta)


def deck_to_text(deck: object) -> str:
    """Flat text of a deck for the publication caption."""
    slides = deck.get("slides") if isinstance(deck, dict) else deck
    if not isinstance(slides, list):
        return ""
    parts: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            parts.append(text)

    for slide in slides:
        if not isinstance(slide, dict):
            continue
        if slide.get("type") == "cta":
            continue
        for field in ("title", "subtitle", "body", "text", "caption", "value"):
            add(slide.get(field, ""))
        for field in ("items", "left_items", "right_items"):
            for item in slide.get(field) or []:
                add(item)
        for field in ("left_title", "right_title", "author"):
            add(slide.get(field, ""))
    return "\n".join(parts)
