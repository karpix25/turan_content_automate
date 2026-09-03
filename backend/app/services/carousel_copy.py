import json
import re

from .karpix_carousel import template_variable_names
from .reference_sources import reference_post_content


SOURCE_CTA_PATTERN = re.compile(
    r"(?:телеграм|telegram|ссылк[аеиу]|в профиле|подпис(?:ывайся|аться|ывайтесь|ка)|"
    r"подпиш(?:ись|итесь)|"
    r"ставь реакци|пиши слово|подробнее|остальн\w*\s+\d+\s+мест)",
    re.IGNORECASE,
)


def is_russian_text(text: str | None) -> bool:
    """Return True only when readable letters are Cyrillic (numbers are fine)."""
    value = str(text or "")
    return bool(re.search(r"[А-Яа-яЁё]", value)) and not bool(re.search(r"[A-Za-z]", value))


def strip_source_cta(text: str | None) -> str:
    """Remove source-specific calls to action before slide composition."""
    value = re.sub(r"\s+", " ", str(text or "").strip())
    fragments = re.split(r"(?<=[.!?…])\s+", value)
    kept = [fragment for fragment in fragments if fragment and not SOURCE_CTA_PATTERN.search(fragment)]
    return re.sub(r"\s+", " ", " ".join(kept)).strip()


def build_reference_rewrite_prompt(posts: list[dict], author_style: str | None) -> list[dict]:
    source_parts = []
    image_urls: list[str] = []
    for index, post in enumerate(posts, start=1):
        source_parts.append(
            f"Источник {index} ({post.get('content_kind') or 'post'}):\n"
            f"Заголовок: {post.get('title') or 'нет'}\n"
            f"Подпись: {post.get('caption') or 'нет'}\n"
            f"Транскрипция: {post.get('transcript') or 'нет'}\n"
            f"Текст: {post.get('body') or 'нет'}"
        )
        for url in post.get("image_urls") or []:
            if url not in image_urls:
                image_urls.append(url)
    style = (author_style or "").strip()[:5000] or "живой, ясный, уверенный авторский стиль"
    content: list[dict] = [{
        "type": "text",
        "text": (
            f"Стиль автора используй только для тона и подачи:\n{style}\n\n"
            "Источники — единственный источник смысла и фактов:\n"
            + "\n\n".join(source_parts)[:18000]
            + "\n\nПравила: сохрани одну главную мысль исходных материалов; не добавляй бизнес,"
            " не объединяй несколько несвязанных тем и не перечисляй разные источники в одном тексте;"
            " госзакупки, цифры, причины или выводы, которых нет в источнике; не выдавай"
            " догадки за факты. Если есть транскрипция, опирайся прежде всего на неё."
            " Если приложены изображения или кадры видео, внимательно прочитай видимый текст на них"
            " и используй его только как источник фактов и смысла; не игнорируй инфографику и скриншоты."
            " Пиши только на русском языке кириллицей; переводи английские фразы из источника"
            " по смыслу и не оставляй английские предложения, слова или латинские заголовки."
            " Если содержательного текста или транскрипции нет, верни ровно:"
            " НЕДОСТАТОЧНО ДАННЫХ ДЛЯ АНАЛИЗА."
            " Напиши 20–60 слов, чтобы одну мысль можно было раскрыть на 1–5 слайдах"
            " и поместить в лимиты карусели и Stories."
            " Не используй нумерацию вида 1., 2., 3.; для перечисления используй маркеры «•»."
            " Не добавляй CTA, ссылки и упоминание источника. Верни только готовый текст."
        ),
    }]
    content.extend({"type": "image_url", "image_url": {"url": url}} for url in image_urls[:4])
    return [
        {
            "role": "system",
            "content": (
                "Ты редактор социальных сетей и умеешь анализировать подписи, транскрипции и изображения "
                "постов. Не подменяй тему источника стилем автора."
            ),
        },
        {"role": "user", "content": content},
    ]


PLATFORM_COPY_RULES = {
    "instagram": "короткий разговорный ритм, сильная первая фраза и лёгкая эмоциональная подача",
    "tiktok": "очень быстрый хук, короткие фразы и максимально плотная подача",
    "vk": "понятная практичная подача с чуть более подробным объяснением",
    "telegram": "прямой авторский тон, ясная мысль и немного больше контекста",
}
RUNTIME_VARIABLES = {"аватар", "аватара", "author", "автор"}
CTA_VARIABLES = {"CTA", "cta"}
TEXT_VARIABLES = {
    "headlineAccent", "headlineMain", "хук заголовок", "описание",
    "Заголовок", "подзаголовок",
}
SUPPORTED_TEMPLATE_VARIABLES = RUNTIME_VARIABLES | CTA_VARIABLES | TEXT_VARIABLES
TEXT_VARIABLE_ORDER = (
    "headlineAccent", "headlineMain", "хук заголовок", "описание",
    "Заголовок", "подзаголовок",
)
STORY_VARIABLE_WORD_LIMITS = {
    "хук заголовок": 3,
    "описание": 6,
    "Заголовок": 3,
    "подзаголовок": 8,
}


def _slide_count(value: int) -> int:
    return max(3, min(5, int(value or 3)))


def _template_contract(template_set: dict[str, dict]) -> dict[str, list[str]]:
    contract = {
        kind: sorted(template_variable_names(template_set[kind]))
        for kind in ("cover", "content", "cta")
    }
    unsupported = sorted(
        name for names in contract.values() for name in names
        if name not in SUPPORTED_TEMPLATE_VARIABLES
    )
    if unsupported:
        raise ValueError("Неизвестные переменные шаблона KARPIX: " + ", ".join(unsupported))
    return contract


def _example_section(names: list[str], cta: str) -> dict[str, str]:
    examples = {
        "headlineAccent": "Короткий акцент",
        "headlineMain": "Главная мысль обложки",
        "хук заголовок": "Короткий хук",
        "описание": "Краткое пояснение",
        "Заголовок": "Заголовок слайда",
        "подзаголовок": "Раскрытие одной мысли",
        "CTA": cta,
        "cta": cta,
    }
    return {name: examples.get(name, "") for name in names}


def build_template_package_prompt(
    master_text: str,
    platform: str,
    template_set: dict[str, dict],
    slide_count: int,
    cta: str,
) -> list[dict]:
    style = PLATFORM_COPY_RULES.get(platform, "короткая ясная подача для социальной сети")
    count = _slide_count(slide_count)
    contract = _template_contract(template_set)
    example = {
        "slide_count": count,
        "cover": _example_section(contract["cover"], cta),
        "main": [_example_section(contract["content"], cta) for _ in range(count - 2)],
        "cta": _example_section(contract["cta"], cta),
    }
    max_words = 12 if int(template_set["cover"].get("height", 0)) == 1920 else 20
    story_limits = (
        ", ".join(f"{name} — до {limit} слов" for name, limit in STORY_VARIABLE_WORD_LIMITS.items())
        if max_words == 12 else ""
    )
    story_rule = f"Для Stories соблюдай лимиты полей: {story_limits}. " if story_limits else ""
    return [
        {
            "role": "system",
            "content": "Ты редактор социальных сетей. Верни данные слайдов как строгий JSON.",
        },
        {
            "role": "user",
            "content": (
                f"Площадка: {platform}. Стиль подачи: {style}.\n\n"
                f"Исходный текст:\n{master_text}\n\n"
                "Выбери только одну связную тему. Не смешивай разные источники. "
                f"Количество слайдов — ровно {count}: одна обложка, {count - 2} основных и один CTA. "
                f"В каждом объекте слайда должно быть не больше {max_words} слов. "
                f"{story_rule}"
                "Все текстовые поля заполни по-русски, без Markdown, заголовков «Версия», ссылок и новых фактов. "
                "Поля author, автор, аватар и аватара оставь пустыми: их заполнит бэкенд. "
                "Значение CTA/cta скопируй точно из примера. Ключи не добавляй и не удаляй. "
                "Верни только JSON-объект без пояснений и без блока ```:\n"
                + json.dumps(example, ensure_ascii=False, indent=2)
            ),
        },
    ]


def _template_package_response_format(template_set: dict[str, dict], slide_count: int) -> dict:
    count = _slide_count(slide_count)
    contract = _template_contract(template_set)

    def section_schema(kind: str) -> dict:
        names = contract[kind]
        return {
            "type": "object",
            "properties": {name: {"type": "string"} for name in names},
            "required": names,
            "additionalProperties": False,
        }

    return {
        "type": "json_schema",
        "json_schema": {
            "name": "karpix_carousel",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "slide_count": {"type": "integer", "const": count},
                    "cover": section_schema("cover"),
                    "main": {
                        "type": "array",
                        "items": section_schema("content"),
                        "minItems": count - 2,
                        "maxItems": count - 2,
                    },
                    "cta": section_schema("cta"),
                },
                "required": ["slide_count", "cover", "main", "cta"],
                "additionalProperties": False,
            },
        },
    }


def parse_template_package(
    raw: str | None,
    template_set: dict[str, dict],
    slide_count: int,
    cta: str,
) -> dict:
    try:
        package = json.loads(str(raw or "").strip())
    except json.JSONDecodeError as exc:
        raise ValueError("Модель вернула не JSON") from exc
    if not isinstance(package, dict) or set(package) != {"slide_count", "cover", "main", "cta"}:
        raise ValueError("JSON должен содержать только slide_count, cover, main и cta")
    count = _slide_count(slide_count)
    if type(package["slide_count"]) is not int or package["slide_count"] != count:
        raise ValueError(f"slide_count должен быть равен {count}")
    if not isinstance(package["main"], list) or len(package["main"]) != count - 2:
        raise ValueError(f"main должен содержать {count - 2} слайда")

    contract = _template_contract(template_set)
    max_words = 12 if int(template_set["cover"].get("height", 0)) == 1920 else 20

    def clean_section(kind: str, section: object) -> dict[str, str]:
        expected = contract[kind]
        if not isinstance(section, dict) or set(section) != set(expected):
            raise ValueError(f"Секция {kind} должна содержать переменные: {', '.join(expected)}")
        cleaned = {}
        editorial_values = []
        for name in expected:
            value = section[name]
            if not isinstance(value, str):
                raise ValueError(f"Переменная {name} должна быть строкой")
            value = re.sub(r"\s+", " ", value).strip()
            if "#" in value or "***" in value or "```" in value or re.search(r"\bверсия\b", value, re.I):
                raise ValueError(f"В переменной {name} запрещены Markdown и варианты")
            if name in RUNTIME_VARIABLES:
                value = ""
            elif name in CTA_VARIABLES:
                value = cta
            else:
                if not value or not is_russian_text(value):
                    raise ValueError(f"Переменная {name} должна содержать русский текст")
                variable_limit = STORY_VARIABLE_WORD_LIMITS.get(name) if max_words == 12 else None
                if variable_limit and len(value.split()) > variable_limit:
                    raise ValueError(f"Переменная {name} превышает лимит {variable_limit} слов")
                editorial_values.append(value)
            cleaned[name] = value
        if len(" ".join(editorial_values).split()) > max_words:
            raise ValueError(f"Секция {kind} превышает лимит {max_words} слов")
        if len(editorial_values) != len(set(value.casefold() for value in editorial_values)):
            raise ValueError(f"Секция {kind} дублирует текст")
        return cleaned

    result = {
        "slide_count": count,
        "cover": clean_section("cover", package["cover"]),
        "main": [clean_section("content", section) for section in package["main"]],
        "cta": clean_section("cta", package["cta"]),
    }
    main_keys = [json.dumps(section, ensure_ascii=False, sort_keys=True).casefold() for section in result["main"]]
    if len(main_keys) != len(set(main_keys)):
        raise ValueError("Основные слайды не должны повторяться")
    return result


def build_template_package(
    llm_client,
    master_text: str,
    platform: str,
    template_set: dict[str, dict],
    slide_count: int,
    cta: str,
) -> dict:
    prompt = build_template_package_prompt(master_text, platform, template_set, slide_count, cta)
    response_format = _template_package_response_format(template_set, slide_count)
    last_error = None
    for temperature in (0.45, 0.2):
        try:
            return parse_template_package(
                llm_client._complete(prompt, temperature=temperature, response_format=response_format),
                template_set,
                slide_count,
                cta,
            )
        except ValueError as exc:
            last_error = exc
    raise ValueError(f"Не удалось получить JSON слайдов для {platform}: {last_error}")


def template_package_text(package: dict) -> str:
    slides = [package.get("cover"), *(package.get("main") or [])]
    result = []
    seen = set()
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        values = [str(slide[name]).strip() for name in TEXT_VARIABLE_ORDER if slide.get(name)]
        text = re.sub(r"\s+", " ", " ".join(values)).strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return "\n\n".join(result)


def fallback_reference_text(posts: list[dict]) -> str:
    pieces = []
    for post in posts:
        text = re.sub(
            r"\s+",
            " ",
            str(post.get("transcript") or post.get("caption") or post.get("body") or post.get("title") or ""),
        ).strip()
        if text:
            pieces.append(text)
    return "\n\n".join(pieces)[:3000]
