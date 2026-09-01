from pathlib import Path
from typing import Any

from .carousel_layout import split_slide_content
from .carousel_pipeline import split_master_text


TEMPLATE_NAMES = {
    "cover": "обложка",
    "content": "основное",
    "cta": "ста",
}


def _normalized_name(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _find_template(templates: list[dict], key: str, aliases: tuple[str, ...]) -> dict:
    normalized_aliases = {_normalized_name(alias) for alias in aliases}
    for template in templates:
        if _normalized_name(template.get("name")) in normalized_aliases:
            return template
    raise ValueError(
        f"В KARPIX Carousel не найден сохранённый шаблон «{TEMPLATE_NAMES[key]}»"
    )


def load_template_set(renderer, design_format: str = "carousel") -> dict[str, dict]:
    expected_size = (1080, 1350) if design_format == "carousel" else (1080, 1920)
    templates = [
        item for item in renderer.list_templates()
        if isinstance(item, dict)
        and (int(item.get("width", 0)), int(item.get("height", 0))) == expected_size
    ]
    if not templates:
        raise ValueError(
            f"В KARPIX Carousel нет сохранённых шаблонов формата {expected_size[0]}×{expected_size[1]}"
        )
    return {
        "cover": _find_template(templates, "cover", ("ОБЛОЖКА", "Обложка", "cover")),
        "content": _find_template(templates, "content", ("Основное", "content")),
        "cta": _find_template(templates, "cta", ("СТА", "CTA", "cta")),
    }


def _variable_names(template: dict) -> set[str]:
    variables = template.get("variables")
    if isinstance(variables, dict):
        return {str(name) for name in variables}
    return {
        str(element.get("variableName"))
        for element in template.get("elements", [])
        if isinstance(element, dict) and element.get("variableName")
    }


def build_template_data(
    template: dict,
    part: str = "",
    cta: str = "",
    author: str = "",
    avatar_url: str = "",
) -> dict[str, str]:
    content = split_slide_content(part)
    heading = str(content["heading"])
    body = str(content["body"]) or heading
    values = {
        "headlineAccent": heading,
        "headlineMain": body,
        "Заголовок": heading,
        "подзаголовок": body,
        "CTA": cta,
        "cta": cta,
        "аватар": avatar_url,
        "аватара": avatar_url,
        "author": author,
        "автор": author,
    }
    names = _variable_names(template)
    data = {name: values[name] for name in names if name in values}
    required = {
        name for name, definition in (template.get("variables") or {}).items()
        if isinstance(definition, dict) and definition.get("required")
    }
    missing = sorted(name for name in required if name not in data)
    if missing:
        raise ValueError(
            f"Шаблон KARPIX «{template.get('name', 'без названия')}» требует неизвестные поля: "
            + ", ".join(missing)
        )
    return data


def render_account_carousel(
    renderer,
    template_set: dict[str, dict],
    text: str,
    slide_count: int,
    cta: str,
    author: str,
    avatar_url: str,
    destination: Path,
    design_format: str,
    platform: str,
    account_id: int,
) -> list[str]:
    main_count = max(1, int(slide_count or 1) - 2)
    parts = split_master_text(text, main_count, max_words=20)
    output_paths: list[str] = []

    def render(kind: str, part: str = "", final_cta: str = "") -> None:
        template = template_set[kind]
        data = build_template_data(template, part, final_cta, author, avatar_url)
        index = len(output_paths) + 1
        path = destination / f"{design_format}-{platform}-{account_id}-{index}.png"
        renderer.render_saved_template(template["id"], data, str(path))
        output_paths.append(str(path))

    render("cover", parts[0])
    for part in parts[1:]:
        render("content", part)
    render("cta", final_cta=cta)
    return output_paths
