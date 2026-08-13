import datetime
import os
import re
from typing import Any


def _ass_time(seconds: float) -> str:
    centiseconds = round(max(0.0, float(seconds)) * 100)
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    seconds_value, centiseconds_value = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{seconds_value:02d}.{centiseconds_value:02d}"


def _ass_color(value: str | None) -> str:
    raw = re.sub(r"[^0-9a-fA-F]", "", value or "FFFFFF")
    raw = (raw if len(raw) == 6 else "FFFFFF").upper()
    red, green, blue = raw[:2], raw[2:4], raw[4:6]
    return f"&H00{blue}{green}{red}"


def _escape_text(value: object) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text.replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def _word_timings(utterance: dict[str, Any]) -> list[tuple[str, float, float]]:
    try:
        start = float(utterance.get("start", 0.0))
        end = float(utterance.get("end", start))
    except (TypeError, ValueError):
        return []
    if end <= start:
        return []

    words = utterance.get("words") or []
    timed_words: list[tuple[str, float, float]] = []
    for word in words:
        text = word.get("punctuated_word") or word.get("word") or word.get("text")
        if not text:
            continue
        try:
            word_start = float(word.get("start", start))
            word_end = float(word.get("end", word_start))
        except (TypeError, ValueError):
            continue
        if word_end > word_start:
            timed_words.append((str(text), word_start, word_end))
    if timed_words:
        return timed_words

    fallback_words = re.findall(r"\S+", str(utterance.get("transcript") or ""))
    if not fallback_words:
        return []
    total_weight = sum(max(1, len(word)) for word in fallback_words)
    cursor = start
    result: list[tuple[str, float, float]] = []
    for index, word in enumerate(fallback_words):
        if index == len(fallback_words) - 1:
            word_end = end
        else:
            word_end = cursor + (end - start) * max(1, len(word)) / total_weight
        result.append((word, cursor, word_end))
        cursor = word_end
    return result


def build_ass(
    transcript_payload: dict[str, Any],
    *,
    font_name: str = "Montserrat",
    font_size: int = 60,
    font_color: str = "FFFFFF",
    play_res_x: int = 1080,
    play_res_y: int = 1920,
    start_offset: float = 0.0,
) -> str | None:
    utterances = ((transcript_payload or {}).get("results") or {}).get("utterances") or []
    events: list[str] = []
    for utterance in utterances:
        for word, start, end in _word_timings(utterance):
            events.append(
                f"Dialogue: 0,{_ass_time(start + start_offset)},{_ass_time(end + start_offset)},Default,,0,0,0,,{_escape_text(word)}"
            )
    if not events:
        return None

    safe_font = (font_name or "Montserrat").replace(",", " ").strip() or "Montserrat"
    safe_size = max(10, int(font_size or 60))
    return "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {int(play_res_x)}",
            f"PlayResY: {int(play_res_y)}",
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            f"Style: Default,{safe_font},{safe_size},{_ass_color(font_color)},&H00000000,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,4,0,2,60,60,100,1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
            *events,
            "",
        ]
    )


def write_ass_file(content: str, *, directory: str, prefix: str) -> str:
    os.makedirs(directory, exist_ok=True)
    filename = f"{prefix}_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S%f')}.ass"
    path = os.path.join(directory, filename)
    with open(path, "w", encoding="utf-8") as output:
        output.write(content)
    return path
