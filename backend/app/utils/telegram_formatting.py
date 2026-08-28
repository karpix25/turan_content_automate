import re


def escape_markdown_v2(text: str) -> str:
    return re.sub(r"([_\*\[\]\(\)~`>#+\-=|{}.!\\])", r"\\\1", text or "")


def markdown_v2_code_block(text: str, language: str = "text") -> str:
    body = (text or "").replace("\\", "\\\\").replace("`", "\\`")
    return f"```{language}\n{body}\n```"
