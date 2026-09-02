from pathlib import Path
from typing import Any

TEMPLATE_NAMES = {
    "cover": "обложка",
    "content": "основное",
    "cta": "ста",
}
TRANSPARENT_AVATAR_DATA_URI = "data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs="


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
        "cover": _find_template(templates, "cover", ("ОБЛОЖКА", "Обложка", "cover", "Stories — Обложка")),
        "content": _find_template(templates, "content", ("Основное", "content", "Сторис основной")),
        "cta": _find_template(templates, "cta", ("СТА", "CTA", "cta", "СТОРИС CTA")),
    }


def template_variable_names(template: dict) -> set[str]:
    variables = template.get("variables")
    if isinstance(variables, dict):
        return {str(name) for name in variables}
    return {
        str(element.get("variableName"))
        for element in template.get("elements", [])
        if isinstance(element, dict) and element.get("variableName")
    }


def build_render_data(
    template: dict,
    data: dict,
    cta: str = "",
    author: str = "",
    avatar_url: str = "",
) -> dict[str, str]:
    if not isinstance(data, dict):
        raise ValueError("Данные слайда KARPIX должны быть объектом")
    values = {str(name): str(value or "") for name, value in data.items()}
    avatar_value = avatar_url or TRANSPARENT_AVATAR_DATA_URI
    values.update({
        "CTA": cta,
        "cta": cta,
        "аватар": avatar_value,
        "аватара": avatar_value,
        "author": author,
        "автор": author,
    })
    names = template_variable_names(template)
    missing = sorted(name for name in names if name not in values)
    if missing:
        raise ValueError(
            f"Для шаблона KARPIX «{template.get('name', 'без названия')}» нет полей: "
            + ", ".join(missing)
        )
    return {name: values[name] for name in names}


def render_account_carousel(
    renderer,
    template_set: dict[str, dict],
    package: dict,
    cta: str,
    author: str,
    avatar_url: str,
    destination: Path,
    design_format: str,
    platform: str,
    account_id: int,
) -> list[str]:
    main_slides = package.get("main") if isinstance(package, dict) else None
    if not isinstance(main_slides, list) or package.get("slide_count") != len(main_slides) + 2:
        raise ValueError("Некорректное количество слайдов в JSON KARPIX")
    output_paths: list[str] = []

    def render(kind: str, data: dict, final_cta: str = "") -> None:
        template = template_set[kind]
        render_data = build_render_data(template, data, final_cta, author, avatar_url)
        index = len(output_paths) + 1
        path = destination / f"{design_format}-{platform}-{account_id}-{index}.png"
        renderer.render_saved_template(template["id"], render_data, str(path))
        output_paths.append(str(path))

    render("cover", package.get("cover"))
    for data in main_slides:
        render("content", data)
    render("cta", package.get("cta"), cta)
    return output_paths
