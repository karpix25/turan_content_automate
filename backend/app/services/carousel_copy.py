import re


def build_reference_rewrite_prompt(posts: list[dict], author_style: str | None) -> list[dict]:
    source = "\n\n".join(
        f"Пост {index}: {post.get('title') or ''}\n{post.get('body') or ''}"
        for index, post in enumerate(posts, start=1)
    )
    style = (author_style or "").strip()[:5000] or "живой, ясный, уверенный авторский стиль"
    return [
        {
            "role": "system",
            "content": (
                "Ты редактор социальных сетей. Объедини смысл нескольких свежих постов в один оригинальный текст "
                "для карусели. Не копируй фразы дословно, не упоминай источники, не добавляй CTA. "
                "Пиши на русском, 500-900 символов, с коротким хуком в начале. Верни только готовый текст."
            ),
        },
        {
            "role": "user",
            "content": f"Стиль автора:\n{style}\n\nИсточники:\n{source[:18000]}",
        },
    ]


def fallback_reference_text(posts: list[dict]) -> str:
    pieces = []
    for post in posts:
        text = re.sub(r"\s+", " ", str(post.get("body") or post.get("title") or "")).strip()
        if text:
            pieces.append(text)
    return "\n\n".join(pieces)[:3000]
