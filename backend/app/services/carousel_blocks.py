"""Block-based carousel deck: schema, validation and writer prompt.

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
    "body_words": 80,
    "takeaway_words": 18,
    "checklist_min_items": 2,
    "checklist_max_items": 6,
    "checklist_item_words": 24,
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
    "qa_min_pairs": 1,
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
        if slide_type == "steps":
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
        if "paragraphs" in slide:
            paragraphs = slide["paragraphs"]
            if "body" in slide or not isinstance(paragraphs, list) or not 1 <= len(paragraphs) <= 3:
                raise ValueError("text: передай 1–3 paragraphs вместо body")
            clean["paragraphs"] = [_require_string("text", "paragraphs", value, "body_words") for value in paragraphs]
            clean["body"] = _require_string("text", "body", " ".join(clean["paragraphs"]), "body_words")
        else:
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
    if slide.get("kicker"):
        clean["kicker"] = _require_string(slide_type, "kicker", slide["kicker"], "kicker_words")
    takeaway = slide.get("takeaway")
    if takeaway not in (None, ""):
        clean["takeaway"] = _require_string(slide_type, "takeaway", takeaway, "takeaway_words")
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
    # Visual block choice is not a narrative role: text can explain both a cause
    # and its consequence. Do not force unrelated checklists just for variety.
    fingerprints = [deck_to_text([slide]).casefold() for slide in body_slides]
    if len(fingerprints) != len(set(fingerprints)):
        raise ValueError("Содержательные слайды не должны повторяться")
    titles = [slide.get("title", "").casefold() for slide in cleaned if slide.get("title")]
    if len(titles) != len(set(titles)):
        raise ValueError("Заголовки слайдов не должны повторяться")
    for original, slide in zip(slides, cleaned):
        if "title_lines" in original:
            lines = original["title_lines"]
            if (not isinstance(lines, list) or not 2 <= len(lines) <= 3
                    or any(not isinstance(line, str) or not line.strip() for line in lines)):
                raise ValueError("title_lines: нужны 2–3 непустые смысловые строки")
            lines = [polish_text(line) for line in lines]
            if " ".join(lines) != slide.get("title"):
                raise ValueError("title_lines должны точно сохранять текст title")
            if any(_is_dangling(line) for line in lines):
                raise ValueError("Не оставляй предлог или союз в конце строки заголовка")
            slide["title_lines"] = lines
    return cleaned, frame


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
    catalog = frames_catalog_text()
    forced_frame = ""
    if frame:
        forced_frame = f" Фрейм выбран заранее: \"{frame['id']}\" — используй именно его."
    frame_block = (
        f"\nБИБЛИОТЕКА КОПИРАЙТ-ФРЕЙМОВ (выбери ОДИН, лучше всего подходящий тексту):\n{catalog}\n"
        "Поле frame в ответе — id выбранного фрейма. Используй его как редакторскую подсказку. "
        "Сохраняй ход мысли источника; пропускай роли, для которых в нём нет материала. "
        "Типы блоков в каталоге — примеры оформления, а не обязательный порядок."
        + forced_frame + "\n"
    )
    rules = (
        f"Площадка: {platform}. Стиль подачи: {style}.\n\n"
        f"Исходный текст:\n{master_text}\n\n"
        + frame_block +
        f"Собери карусель из типовых блоков. Верни JSON с обязательными полями frame и slides: frame=\"{frame['id'] if frame else 'insight'}\", slides=[...]. Каждый слайд — один из типов:\n"
        "- cover: {type, kicker?, title, subtitle?} — обложка, сильная первая фраза;\n"
        "- text: {type, title, body} — мысль, которую лучше раскрыть абзацем;\n"
        "- checklist: {type, title, items} — признаки, ошибки, правила, что сделать;\n"
        "- table: {type, title, columns, rows} — сравнение по параметрам, колонок 2–3, ячейки очень короткие;\n"
        "- steps: {type, title, items} — порядок действий по шагам;\n"
        "- comparison: {type, title, left_title, right_title, left_items, right_items} — «до/после», «так/не так»;\n"
        "- stat: {type, title, value, caption, body?} — одна яркая цифра или факт из источника;\n"
        "- qa: {type, title, pairs} — 1–3 пары {q: вопрос до 10 слов, a: ответ до 20 слов};\n"
        "- quote: {type, text, author?} — цитата из исходного текста;\n"
        "- cta: {type, cta: \"\"} — последний слайд, текст CTA подставит бэкенд.\n\n"
        "Жесткие требования:\n"
        f"- Целевое количество слайдов — {max(3, min(7, int(slide_count)))}: обложка, {content_count} содержательных, CTA. Если материала мало, сократи до 3–4 слайдов.\n"
        "- Сначала выстрой связный рассказ: обещание обложки → раскрытие → объяснение или пример → вывод. "
        "Каждый следующий слайд продолжает предыдущий; местоимения должны иметь понятный предмет. "
        "Не меняй тему и не начинай практические советы до объяснения проблемы.\n"
        "- Выбирай оформление после смысла. Несколько текстовых слайдов подряд допустимы. "
        "Чек-лист нужен только для реального списка, сравнение — для сопоставления из источника. "
        "Не придумывай проверки, шаги, цифры или цитаты ради шаблона. "
        "Не используй универсальное «Что важно проверить», если это не тема материала.\n"
        f"- Заголовок до {limits['title_words']} слов, kicker до {limits['kicker_words']}, subtitle до {limits['subtitle_words']}, body до {limits['body_words']}.\n"
        f"- checklist: {limits['checklist_min_items']}–{limits['checklist_max_items']} пунктов до {limits['checklist_item_words']} слов; "
        f"steps: {limits['steps_min_items']}–{limits['steps_max_items']} пунктов до {limits['steps_item_words']} слов.\n"
        f"- Ячейки таблицы до {limits['table_cell_words']} слов; пункты сравнения до {limits['comparison_item_words']} слов.\n"
        "- На основном слайде ориентируйся на 45–70 слов суммарно: тезис, объяснение и конкретика. "
        "Обложка и CTA остаются короткими. Не растягивай одно предложение на отдельный слайд. "
        "Если исходник короткий, используй меньше слайдов (минимум 3), не добавляй вымышленные факты.\n"
        "- У любого содержательного блока можно добавить takeaway: вывод до 18 слов, "
        "который следует из источника и не повторяет заголовок. Для text используй 2–3 связных предложения.\n"
        "- НАПОЛНЯЙ слайды плотно: в subtitle, body и caption — конкретика из источника (цифры, причины, примеры, следствия),"
        " а не общие фразы. stat поддерживает поле body — раскрой цифру абзацем.\n"
        "- В steps последовательность действий обозначена бейджами; в checklist можно явно обозначить номера обещанных пунктов.\n"
        "- Каждый пункт — законченная фраза без обрывов и без висячих слов; не дели одну мысль на два пункта.\n"
        "- ЗАГОЛОВКИ: у каждого слайда свой уникальный заголовок — законченная мысль; не дублируй заголовок\n"
        "  обложки на содержательных слайдах и не обрывай фразу ради лимита — лучше сократи формулировку, сохранив смысл.\n"
        "- Не повторяй одну и ту же мысль на разных слайдах. Пиши только по-русски, без Markdown, без латиницы и ссылок.\n"
        "- Не выдумывай фактов и цифр, которых нет в исходном тексте.\n"
        "- Поля cta оставь пустыми строками. Верни только JSON без пояснений и без блока ```."
    )
    return [
        {"role": "system", "content": "Ты арт-директор соцсетей и редактор. Собираешь карусели из типовых блоков и возвращаешь строгий JSON."},
        {"role": "user", "content": rules},
    ]


def build_fallback_deck(master_text: str, slide_count: int, cta: str) -> list[dict]:
    """Offline smoke-test fixture only; never called by production generation.

    Pack adjacent source sentences without truncation or round-robin reordering.

    The fallback is intentionally editorially neutral: it adds no new claims.
    A very long indivisible passage is left intact for the overflow guard.
    """
    text = normalize_master_text(master_text)
    if not text:
        raise ValueError("Текст карусели не может быть пустым")
    units = [part.strip().removeprefix("•").strip()
             for part in re.split(r"(?<=[.!?…])\s+|\s*•\s*|\n+", text) if part.strip()]
    # Keep long opening sentences in the body instead of overflowing the cover.
    short_opening = len(units) > 1 and len(units[0].split()) <= 16
    cover = {"type": "cover", "kicker": "Разбор", "title": units[0] if short_opening else "Разбираем по существу"}
    remaining = units[1:] if short_opening else units
    chunks: list[list[str]] = []
    for unit in remaining:
        if not chunks or (len(" ".join(chunks[-1]).split()) + len(unit.split()) > 75
                          and len(" ".join(chunks[-1]).split()) >= 35):
            chunks.append([])
        chunks[-1].append(unit)
    # Fold a short tail into its neighbour when it remains readable.
    if len(chunks) > 1 and len(" ".join(chunks[-1]).split()) < 25:
        if len(" ".join(chunks[-2] + chunks[-1]).split()) <= 95:
            chunks[-2].extend(chunks.pop())
    if len(chunks) > DECK_LIMITS["max_slides"] - 2:
        raise ValueError("Исходник слишком длинный для запасной карусели: нужно редакторское сокращение")
    deck = [cover]
    for index, chunk in enumerate(chunks):
        deck.append({"type": "text", "title": "Подробности" if len(chunks) == 1 else f"Разбор · {index + 1}",
                     "body": " ".join(chunk)})
    deck.append({"type": "cta", "cta": cta})
    return deck


def build_platform_deck(llm_client, master_text: str, platform: str, cta: str) -> tuple[list[dict], dict | None]:
    # The LLM owns both the outline and the writing; no production fallback.
    from .carousel_editor import build_editorial_deck
    return build_editorial_deck(llm_client, master_text, platform, cta)


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
        for field in ("kicker", "title", "subtitle", "body", "text", "caption", "value", "takeaway"):
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
