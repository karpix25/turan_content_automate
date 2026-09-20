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
from .copy_frames import FRAME_BY_ID, frames_catalog_text

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
    "qa_min_pairs": 2,
    "qa_max_pairs": 3,
    "qa_q_words": 10,
    "qa_a_words": 20,
    "cta_words": 8,
}
BLOCK_TYPES = ("cover", "text", "checklist", "table", "steps", "comparison", "stat", "quote", "qa", "cta")
CONTENT_TYPES = ("text", "checklist", "table", "steps", "comparison", "stat", "quote", "qa")
STRING_FIELDS = ("kicker", "title", "subtitle", "body", "value", "caption", "text", "author",
                 "left_title", "right_title", "cta")
# qa-пары обрабатываются отдельной веткой валидации
LIST_FIELDS = ("items", "left_items", "right_items")
ITEM_LIMITS = {
    "items": ("checklist_item_words", "checklist_min_items", "checklist_max_items", "checklist"),
    "left_items": ("comparison_item_words", "comparison_min_items", "comparison_max_items", "сравнение"),
    "right_items": ("comparison_item_words", "comparison_min_items", "comparison_max_items", "сравнение"),
}
SIDE_TITLE_LIMIT = "comparison_side_words"

# фраза, заканчивающаяся на эти слова, почти всегда оборвана
DANGLING_ENDINGS = {
    "и", "а", "но", "или", "что", "чтобы", "который", "которая", "которые", "которое",
    "в", "на", "с", "со", "к", "по", "за", "из", "у", "о", "об", "от", "до", "для",
    "при", "под", "над", "без", "это", "как", "же", "бы", "ли", "то", "не",
    "перед", "про", "через", "между", "после", "около", "среди", "внутри", "вокруг",
}


def _is_dangling(text: str) -> bool:
    words = re.findall(r"[а-яёa-z-]+", text.casefold())
    return bool(words) and words[-1] in DANGLING_ENDINGS


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
    if _is_dangling(text):
        raise ValueError(f"Слайд «{slide_type}»: поле {field} обрывается на предлоге или союзе — сократи мысль")
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
        if _is_dangling(text):
            raise ValueError(f"Слайд «{slide_type}»: пункт поля {field} оборван — закончи мысль")
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
    elif slide_type == "qa":
        if "title" not in clean:
            raise ValueError("Слайд «qa»: нужен заголовок")
        pairs = slide.get("pairs")
        if not isinstance(pairs, list) or not (
            DECK_LIMITS["qa_min_pairs"] <= len(pairs) <= DECK_LIMITS["qa_max_pairs"]
        ):
            raise ValueError(
                f"Слайд «qa»: пар должно быть {DECK_LIMITS['qa_min_pairs']}–{DECK_LIMITS['qa_max_pairs']}"
            )
        clean_pairs = []
        for pair in pairs:
            if not isinstance(pair, dict):
                raise ValueError("Слайд «qa»: каждая пара должна быть объектом {q, a}")
            q = _require_string("qa", "q", pair.get("q"), "qa_q_words")
            a = _require_string("qa", "a", pair.get("a"), "qa_a_words")
            clean_pairs.append({"q": q, "a": a})
        clean["pairs"] = clean_pairs
    elif slide_type == "quote":
        clean["text"] = _require_string("quote", "text", slide.get("text"), "quote_words")
        author = slide.get("author")
        if author not in (None, ""):
            clean["author"] = _require_string("quote", "author", author, "quote_author_words")
    return clean


def validate_deck(raw: object, cta: str) -> tuple[list[dict], dict]:
    """Validate an LLM deck against block limits; returns cleaned slides and frame."""
    if not isinstance(raw, dict) or not isinstance(raw.get("slides"), list):
        raise ValueError("Дека должна быть объектом со списком slides")
    frame_id = raw.get("frame")
    if not frame_id or frame_id not in FRAME_BY_ID:
        raise ValueError("Укажи поле frame — id подходящего фрейма из библиотеки")
    frame = FRAME_BY_ID[frame_id]
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
    body_slides = cleaned[1:-1]
    body_types = [slide["type"] for slide in body_slides]
    for index in range(len(body_types) - 2):
        if body_types[index] == body_types[index + 1] == body_types[index + 2]:
            raise ValueError("Не ставь три одинаковых блока подряд — чередуй типы")
    if len(set(body_types)) < min(2, len(body_types)):
        raise ValueError("Содержательные слайды должны использовать минимум два разных блока")
    _check_frame_roles(body_slides, frame)
    titles = [slide.get("title", "").casefold() for slide in cleaned if slide.get("title")]
    if len(titles) != len(set(titles)):
        raise ValueError("Заголовки слайдов не должны повторяться")
    return cleaned, frame


def _check_frame_roles(content_slides: list[dict], frame: dict) -> None:
    """Content slides must follow the frame's role order (skips allowed)."""
    roles = frame.get("roles") or []
    pointer = 0
    for slide in content_slides:
        slide_type = slide["type"]
        while pointer < len(roles) and slide_type not in roles[pointer]["blocks"]:
            pointer += 1
        if pointer >= len(roles):
            raise ValueError(
                f"Фрейм «{frame['name']}»: блок «{slide_type}» нарушает порядок ролей фрейма"
            )


def parse_deck(raw: str | None, cta: str) -> tuple[list[dict], dict]:
    text = str(raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("Модель вернула не JSON") from exc
    return validate_deck(payload, cta)


def build_deck_prompt(master_text: str, platform: str, slide_count: int, cta: str, frame: dict | None = None) -> list[dict]:
    style = PLATFORM_COPY_RULES.get(platform, "короткая ясная подача для социальной сети")
    limits = DECK_LIMITS
    content_count = max(1, int(slide_count) - 2)
    example = {
        "frame": "mistakes",
        "slides": [
            {"type": "cover", "kicker": "Разбор", "title": "Главная мысль обложки", "subtitle": "Одно предложение с конкретикой"},
            {"type": "stat", "title": "Заголовок слайда", "value": "72%", "caption": "Пояснение к цифре из источника", "body": "Развёрнутое пояснение с конкретикой"},
            {"type": "checklist", "title": "Заголовок слайда", "items": ["Пункт до 12 слов", "Пункт до 12 слов", "Пункт до 12 слов"]},
            {"type": "cta", "cta": ""},
        ]
    }
    catalog = frames_catalog_text()
    forced_frame = ""
    if frame:
        forced_frame = f" Фрейм выбран заранее: \"{frame['id']}\" — используй именно его."
    frame_block = (
        f"\nБИБЛИОТЕКА КОПИРАЙТ-ФРЕЙМОВ (выбери ОДИН, лучше всего подходящий тексту):\n{catalog}\n"
        "Поле frame в ответе — id выбранного фрейма. Содержательные слайды должны идти в порядке"
        " ролей фрейма: роли можно пропускать, нельзя менять порядок и вставлять чужие блоки."
        + forced_frame + "\n"
    )
    rules = (
        f"Площадка: {platform}. Стиль подачи: {style}.\n\n"
        f"Исходный текст:\n{master_text}\n\n"
        + frame_block +
        "Собери карусель из типовых блоков. Верни JSON вида {\"slides\": [...]}, где каждый слайд — один из типов:\n"
        "- cover: {type, kicker?, title, subtitle?} — обложка, сильная первая фраза;\n"
        "- text: {type, title, body} — мысль, которую лучше раскрыть абзацем;\n"
        "- checklist: {type, title, items} — признаки, ошибки, правила, что сделать;\n"
        "- table: {type, title, columns, rows} — сравнение по параметрам, колонок 2–3, ячейки очень короткие;\n"
        "- steps: {type, title, items} — порядок действий по шагам;\n"
        "- comparison: {type, title, left_title, right_title, left_items, right_items} — «до/после», «так/не так»;\n"
        "- stat: {type, title, value, caption, body?} — одна яркая цифра или факт из источника;\n"
        "- qa: {type, title, pairs} — 2–3 пары {q: вопрос до 10 слов, a: ответ до 20 слов};\n"
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
        "- ЗАГОЛОВКИ: у каждого слайда свой уникальный заголовок — законченная мысль; не дублируй заголовок\n"
        "  обложки на содержательных слайдах и не обрывай фразу ради лимита — лучше сократи формулировку, сохранив смысл.\n"
        "- Не повторяй одну и ту же мысль на разных слайдах. Пиши только по-русски, без Markdown, без латиницы и ссылок.\n"
        "- Не выдумывай фактов и цифр, которых нет в исходном тексте.\n"
        "- Поля cta оставь пустыми строками. Верни только JSON без пояснений и без блока ```."
    )
    return [
        {"role": "system", "content": "Ты арт-директор соцсетей и редактор. Собираешь карусели из типовых блоков и возвращаешь строгий JSON."},
        {"role": "user", "content": rules + "\n\nПример структуры:\n" + json.dumps(example, ensure_ascii=False, indent=2)},
    ]


def build_deck(llm_client, master_text: str, platform: str, slide_count: int, cta: str, frame: dict | None = None) -> tuple[list[dict], dict]:
    """LLM deck with retries; raises ValueError if every attempt fails."""
    prompt = build_deck_prompt(master_text, platform, slide_count, cta, frame)
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
    """Deterministic deck when the LLM fails; guaranteed to pass validation.

    Uses whole sentences and whole bullets only — never cuts a phrase
    mid-word to satisfy a word limit (the renderer's auto-fit absorbs
    slightly longer lines instead).
    """
    limits = DECK_LIMITS
    text = normalize_master_text(master_text)
    blocks = [block.strip() for block in re.sub(r"\s*•\s*", "\n• ", text).splitlines() if block.strip()]
    bullets = [block[2:].strip() for block in blocks if block.startswith("• ")]
    sentences = []
    for block in blocks:
        if block.startswith("• "):
            continue
        sentences.extend(part.strip() for part in re.split(r"(?<=[.!?…])\s+", block) if part.strip())
    cover_title = sentences[0] if sentences else " ".join(text.split()[:limits["title_words"]])
    cover_subtitle = sentences[1] if len(sentences) > 1 else ""
    body_sentences = sentences[2:] if len(sentences) > 2 else sentences
    count = max(limits["min_slides"], min(limits["max_slides"], int(slide_count or limits["min_slides"])))
    deck: list[dict] = [{"type": "cover", "title": cover_title}]
    if cover_subtitle:
        deck[0]["subtitle"] = cover_subtitle

    if len(bullets) >= limits["checklist_min_items"]:
        deck.append({"type": "checklist", "title": "Что важно проверить", "items": bullets[:limits["checklist_max_items"]]})
        body_sentences = body_sentences or bullets[limits["checklist_max_items"]:]
    content_target = max(1, count - 2)
    chunks: list[list[str]] = [[] for _ in range(content_target)]
    for index, sentence in enumerate(body_sentences):
        chunks[index % content_target].append(sentence)
    for index, chunk in enumerate(chunks):
        body = " ".join(chunk).strip()
        if not body:
            continue
        deck.append({"type": "text", "body": body})
    deck.append({"type": "cta", "cta": cta})
    deck = deck[:limits["max_slides"]]
    deck[-1] = {"type": "cta", "cta": cta}
    filler = {"type": "text", "body": cover_subtitle or " ".join(body_sentences)}
    while len(deck) < limits["min_slides"]:
        deck.insert(len(deck) - 1, dict(filler))
    return deck


def build_platform_deck(llm_client, master_text: str, platform: str, slide_count: int, cta: str, frame: dict | None = None) -> tuple[list[dict], dict | None]:
    try:
        return build_deck(llm_client, master_text, platform, slide_count, cta, frame)
    except ValueError as exc:
        import logging

        logging.getLogger(__name__).warning("Deck generation failed for %s, using fallback: %s", platform, exc)
        return build_fallback_deck(master_text, slide_count, cta), None


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
        for pair in slide.get("pairs") or []:
            if isinstance(pair, dict):
                add(pair.get("q", ""))
                add(pair.get("a", ""))
        for field in ("left_title", "right_title", "author"):
            add(slide.get(field, ""))
    return "\n".join(parts)
