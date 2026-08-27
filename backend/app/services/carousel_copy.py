import re

from .reference_sources import reference_post_content


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
            " госзакупки, цифры, причины или выводы, которых нет в источнике; не выдавай"
            " догадки за факты. Если есть транскрипция, опирайся прежде всего на неё."
            " Если содержательного текста или транскрипции нет, верни ровно:"
            " НЕДОСТАТОЧНО ДАННЫХ ДЛЯ АНАЛИЗА."
            " Напиши 20–60 слов, чтобы одну мысль можно было раскрыть на 1–5 слайдах"
            " и поместить в лимиты карусели и Stories."
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


def fallback_reference_text(posts: list[dict]) -> str:
    pieces = []
    for post in posts:
        text = re.sub(r"\s+", " ", str(post.get("body") or post.get("title") or "")).strip()
        if text:
            pieces.append(text)
    return "\n\n".join(pieces)[:3000]
