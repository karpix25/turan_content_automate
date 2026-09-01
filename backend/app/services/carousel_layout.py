import re


def _sentences(text: str) -> list[str]:
    return [
        part.strip()
        for part in re.split(r"(?<=[.!?…])\s+(?=[А-ЯЁ«„])", text)
        if part.strip()
    ]


def split_slide_content(part: str) -> dict[str, str | bool]:
    value = re.sub(r"\s+", " ", str(part or "").strip())
    is_bullet = value.startswith("•")
    value = re.sub(r"^•\s*", "", value).strip()
    sentences = _sentences(value)
    if is_bullet and sentences:
        heading = sentences[0]
        body = " ".join(sentences[1:]).strip()
        if ":" in heading:
            heading, first_body = heading.split(":", 1)
            heading = f"{heading.strip()}:"
            body = " ".join(value for value in (first_body.strip(), body) if value)
    elif len(sentences) > 1:
        heading = sentences[0]
        body = " ".join(sentences[1:]).strip()
    else:
        heading, body = value, ""
    return {"heading": heading, "body": body, "is_bullet": is_bullet}
