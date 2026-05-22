#!/usr/bin/env python3
"""
Deepgram -> LLM -> HyperFrames scene plan pipeline.

1) Transcribes audio/video with Deepgram (utterances + paragraphs + topics + intents)
2) Builds semantic scenes with an LLM (OpenAI-compatible Chat Completions API)
3) Writes scene-plan JSON and injects it into index.html <script id="scene-plan">
"""

from __future__ import annotations

import argparse
import json
import math
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def eprint(msg: str) -> None:
    print(msg, file=sys.stderr)


def find_dotenv(start: Path) -> Path | None:
    for candidate in [start, *start.parents]:
        dotenv = candidate / ".env"
        if dotenv.exists():
            return dotenv
    return None


def load_dotenv(dotenv: Path) -> None:
    for raw in dotenv.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = val


def http_post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url=url, data=body, method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    fallback_error: Exception | None = None
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        if 400 <= err.code < 500:
            raise RuntimeError(f"LLM HTTP auth/client error {err.code}: {err.reason}") from err
        fallback_error = err
        eprint(f"urllib failed for {url}: {err}. Falling back to curl ...")
    except Exception as err:
        fallback_error = err
        eprint(f"urllib failed for {url}: {err}. Falling back to curl ...")
    if not shutil.which("curl"):
        raise RuntimeError("HTTP request failed and curl is not installed in the runtime image") from fallback_error
    cmd = [
        "curl",
        "--silent",
        "--show-error",
        "--fail",
        "--max-time",
        str(timeout),
        "--request",
        "POST",
        "--url",
        url,
    ]
    for k, v in headers.items():
        cmd.extend(["--header", f"{k}: {v}"])
    cmd.extend(["--data", json.dumps(payload, ensure_ascii=False)])
    run = subprocess.run(cmd, capture_output=True, text=True)
    if run.returncode != 0:
        raise RuntimeError(f"curl failed ({run.returncode}): {run.stderr.strip()}") from fallback_error
    return json.loads(run.stdout)


def deepgram_transcribe(
    video_path: Path,
    api_key: str,
    language: str,
    model: str,
    timeout_sec: int,
    include_intelligence: bool,
    utt_split: float,
) -> dict[str, Any]:
    params = {
        "model": model,
        "language": language,
        "punctuate": "true",
        "smart_format": "true",
        "utterances": "true",
        "utt_split": str(utt_split),
        "paragraphs": "true",
    }
    # Some Deepgram intelligence extras are model/language dependent and may return 400.
    # Keep them optional so RU flows remain stable.
    if include_intelligence:
        if language.startswith("en"):
            params["topics"] = "true"
            params["intents"] = "true"
            params["sentiment"] = "true"
            params["summarize"] = "v2"
    url = "https://api.deepgram.com/v1/listen?" + urllib.parse.urlencode(params)
    mime, _ = mimetypes.guess_type(video_path.name)
    content_type = mime or "application/octet-stream"
    data = video_path.read_bytes()
    req = urllib.request.Request(url=url, data=data, method="POST")
    req.add_header("Authorization", f"Token {api_key}")
    req.add_header("Content-Type", content_type)

    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Deepgram HTTP {err.code}: {detail}") from err
    except Exception as err:
        eprint(f"urllib Deepgram call failed: {err}. Falling back to curl ...")
        cmd = [
            "curl",
            "--silent",
            "--show-error",
            "--fail",
            "--max-time",
            str(timeout_sec),
            "--request",
            "POST",
            "--url",
            url,
            "--header",
            f"Authorization: Token {api_key}",
            "--header",
            f"Content-Type: {content_type}",
            "--data-binary",
            f"@{video_path}",
        ]
        run = subprocess.run(cmd, capture_output=True, text=True)
        if run.returncode != 0:
            raise RuntimeError(f"Deepgram curl failed ({run.returncode}): {run.stderr.strip()}") from err
        return json.loads(run.stdout)


def extract_utterances(transcript_payload: dict[str, Any]) -> list[dict[str, Any]]:
    results = transcript_payload.get("results", {})
    utterances = results.get("utterances") or []
    out: list[dict[str, Any]] = []

    if utterances:
        for idx, utt in enumerate(utterances):
            text = (utt.get("transcript") or "").strip()
            if not text:
                continue
            out.append(
                {
                    "id": utt.get("id") or f"utt-{idx:04d}",
                    "start": float(utt.get("start", 0.0)),
                    "end": float(utt.get("end", 0.0)),
                    "text": text,
                    "confidence": float(utt.get("confidence", 0.0)),
                }
            )
        return out

    channels = results.get("channels") or []
    if not channels:
        return out
    alternatives = channels[0].get("alternatives") or []
    if not alternatives:
        return out
    paragraphs = (alternatives[0].get("paragraphs") or {}).get("paragraphs") or []

    for p_idx, para in enumerate(paragraphs):
        sents = para.get("sentences") or []
        if not sents:
            continue
        text = " ".join((s.get("text") or "").strip() for s in sents).strip()
        if not text:
            continue
        out.append(
            {
                "id": f"para-{p_idx:04d}",
                "start": float(para.get("start", 0.0)),
                "end": float(para.get("end", 0.0)),
                "text": text,
                "confidence": 0.0,
            }
        )
    return out


def _anchor_token(text: str) -> str:
    tokens = re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", str(text).lower().replace("ё", "е"))
    return tokens[0] if len(tokens) == 1 else " ".join(tokens)


def extract_transcript_words(transcript_payload: dict[str, Any]) -> list[dict[str, Any]]:
    results = transcript_payload.get("results", {})
    channels = results.get("channels") or []
    if not channels:
        return []
    alternatives = channels[0].get("alternatives") or []
    if not alternatives:
        return []
    words = alternatives[0].get("words") or []
    out: list[dict[str, Any]] = []
    for idx, word in enumerate(words):
        text = str(word.get("punctuated_word") or word.get("word") or "").strip()
        if not text:
            continue
        try:
            start = float(word.get("start", 0.0))
            end = float(word.get("end", start))
        except (TypeError, ValueError):
            continue
        if end < start:
            end = start
        out.append(
            {
                "id": word.get("id") or f"word-{idx:06d}",
                "start": start,
                "end": end,
                "text": text,
                "_token": _anchor_token(text),
            }
        )
    return [word for word in out if word.get("_token")]


def _text_from_tokens(tokens: list[str]) -> str:
    text = " ".join(t for t in tokens if t)
    text = re.sub(r"\s+([,.;!?])", r"\1", text)
    return text.strip()


def synthesize_utterances_from_words(
    transcript_payload: dict[str, Any],
    split_sec: float,
    max_scene_word_span_sec: float = 8.0,
) -> list[dict[str, Any]]:
    results = transcript_payload.get("results", {})
    channels = results.get("channels") or []
    if not channels:
        return []
    alternatives = channels[0].get("alternatives") or []
    if not alternatives:
        return []
    words = alternatives[0].get("words") or []
    if not words:
        return []

    out: list[dict[str, Any]] = []
    buff_tokens: list[str] = []
    start = float(words[0].get("start", 0.0))
    end = start

    def flush_segment() -> None:
        nonlocal buff_tokens, start, end
        text = _text_from_tokens(buff_tokens)
        if text:
            out.append(
                {
                    "id": f"syn-{len(out):04d}",
                    "start": round(start, 2),
                    "end": round(end, 2),
                    "text": text,
                    "confidence": 0.0,
                }
            )
        buff_tokens = []

    for i, w in enumerate(words):
        token = str(w.get("punctuated_word") or w.get("word") or "").strip()
        w_start = float(w.get("start", end))
        w_end = float(w.get("end", w_start))
        if not buff_tokens:
            start = w_start
        end = w_end
        if token:
            buff_tokens.append(token)

        next_start = None
        if i + 1 < len(words):
            next_start = float(words[i + 1].get("start", w_end))
        gap = (next_start - w_end) if next_start is not None else 0.0
        dur = w_end - start
        token_ends_sentence = bool(re.search(r"[.!?]$", token))
        should_split = (
            (next_start is None)
            or (gap >= split_sec)
            or (dur >= max_scene_word_span_sec)
            or token_ends_sentence
        )
        if should_split:
            flush_segment()

    return out


def synthesize_utterances_from_script_text(
    script_text: str,
    duration: float,
    max_segments: int = 40,
) -> list[dict[str, Any]]:
    sentences = split_sentences(script_text)
    sentences = [strip_filler_phrases(sentence) for sentence in sentences]
    sentences = [sentence for sentence in sentences if sentence]
    if not sentences:
        return []

    duration = max(1.0, float(duration or 0.0))
    max_segments = max(1, int(max_segments or 1))
    if len(sentences) > max_segments:
        group_size = math.ceil(len(sentences) / max_segments)
        grouped = [
            " ".join(sentences[index : index + group_size]).strip()
            for index in range(0, len(sentences), group_size)
        ]
        sentences = [item for item in grouped if item]

    total_chars = max(1, sum(len(sentence) for sentence in sentences))
    cursor = 0.0
    out: list[dict[str, Any]] = []
    for idx, sentence in enumerate(sentences):
        ratio = len(sentence) / total_chars
        seg_duration = max(0.5, duration * ratio)
        end = duration if idx == len(sentences) - 1 else min(duration, cursor + seg_duration)
        if end <= cursor:
            end = min(duration, cursor + 0.5)
        out.append(
            {
                "id": f"script-{idx:04d}",
                "start": round(cursor, 2),
                "end": round(end, 2),
                "text": sentence,
                "confidence": 0.0,
                "source": "script_text",
            }
        )
        cursor = end
    return out


STOPWORDS_RU = {
    "и",
    "а",
    "но",
    "или",
    "что",
    "это",
    "как",
    "когда",
    "чтобы",
    "если",
    "так",
    "вот",
    "тут",
    "там",
    "уже",
    "тоже",
    "просто",
    "очень",
    "сейчас",
    "тогда",
    "потом",
    "пока",
    "который",
    "которая",
    "которые",
    "этот",
    "эта",
    "эти",
    "того",
    "того",
    "меня",
    "тебя",
    "вас",
    "мы",
    "вы",
    "они",
    "оно",
    "она",
    "он",
    "же",
    "ли",
    "бы",
    "по",
    "за",
    "для",
    "над",
    "под",
    "при",
    "без",
    "из",
    "до",
    "на",
    "в",
    "к",
    "с",
    "о",
    "об",
    "от",
}

FILLER_PATTERNS = [
    r"\bребята\b",
    r"\bв общем\b",
    r"\bну и да\b",
    r"\bда какая к ч[её]рту\b",
    r"\bя вам честно скажу\b",
    r"\bмягко говоря\b",
    r"\bпо сути\b",
    r"\bкак бы\b",
    r"\bтипа\b",
    r"\bкороче\b",
    r"\bв принципе\b",
]

EDITORIAL_NOISE_PATTERNS = [
    r"\bс\s+одной\s+стороны\b",
    r"\bс\s+1\s+стороны\b",
    r"\bс\s+другой\s+стороны\b",
    r"\bвроде\s+как\b",
    r"\bполучается\b",
    r"\bто\s+есть\b",
    r"\bкак\s+бы\b",
    r"\bну\s+вот\b",
    r"\bну\s+и\b",
    r"\bважный\s+момент\b",
    r"\bважная\s+мысль\b",
    r"\bключевая\s+мысль\b",
]

RAW_TITLE_WORDS = {
    "вам",
    "вас",
    "тебе",
    "тебя",
    "мне",
    "меня",
    "нам",
    "нас",
    "этого",
    "этой",
    "этот",
    "эта",
    "эти",
    "вроде",
    "готовы",
    "получается",
}

TRAILING_WEAK_TITLE_WORDS = {
    "и",
    "а",
    "но",
    "или",
    "если",
    "когда",
    "что",
    "как",
    "через",
    "для",
    "без",
    "по",
    "на",
    "в",
    "с",
    "от",
    "до",
}

TEXT_LIMITS = {
    "title_line": 45,
    "opener": 56,
    "step": 100,
    "insight": 250,
    "cta": 100,
    "keyword": 40,
    "bar_label": 80,
    "utterance": 400,
    "semantic_summary": 500,
    "semantic_sentence": 300,
}

WORD_LIMITS = {
    "title_line": 5,
    "opener": 6,
    "step": 10,
    "insight": 35,
    "cta": 10,
    "keyword": 5,
    "bar_label": 10,
}


def normalize_plain_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\u00A0", " ")).strip()


def strip_filler_phrases(text: str) -> str:
    out = normalize_plain_text(text)
    if not out:
        return ""
    for pattern in FILLER_PATTERNS:
        out = re.sub(pattern, "", out, flags=re.IGNORECASE)
    out = re.sub(r"\s+([,.;!?])", r"\1", out)
    out = re.sub(r"\s{2,}", " ", out).strip(" ,;")
    return out


def strip_editorial_noise(text: str) -> str:
    out = strip_filler_phrases(text)
    if not out:
        return ""
    for pattern in EDITORIAL_NOISE_PATTERNS:
        out = re.sub(pattern, "", out, flags=re.IGNORECASE)
    out = re.sub(r"^\s*(?:и|а|но|вот|ну|значит|так)\s+", "", out, flags=re.IGNORECASE)
    out = re.sub(r"\s+([,.;!?])", r"\1", out)
    return re.sub(r"\s{2,}", " ", out).strip(" ,;")


def split_sentences(text: str) -> list[str]:
    source = normalize_plain_text(text)
    if not source:
        return []
    chunks = [c.strip() for c in re.split(r"(?<=[.!?])\s+", source) if c.strip()]
    if chunks:
        return chunks
    return [source]


def extract_sentences(
    transcript_payload: dict[str, Any], utterances: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    results = transcript_payload.get("results", {})
    channels = results.get("channels") or []
    if channels:
        alternatives = channels[0].get("alternatives") or []
        if alternatives:
            paragraphs = (alternatives[0].get("paragraphs") or {}).get("paragraphs") or []
            extracted: list[dict[str, Any]] = []
            for p_idx, paragraph in enumerate(paragraphs):
                for s_idx, sentence in enumerate(paragraph.get("sentences") or []):
                    text = strip_filler_phrases(str(sentence.get("text") or ""))
                    if not text:
                        continue
                    start = float(sentence.get("start", paragraph.get("start", 0.0)))
                    end = float(sentence.get("end", paragraph.get("end", start)))
                    if end <= start:
                        end = start + 0.2
                    extracted.append(
                        {
                            "id": f"sent-{p_idx:04d}-{s_idx:03d}",
                            "start": round(start, 2),
                            "end": round(end, 2),
                            "text": text,
                        }
                    )
            if extracted:
                return extracted

    synthesized: list[dict[str, Any]] = []
    for u_idx, utt in enumerate(utterances):
        text = normalize_plain_text(str(utt.get("text") or ""))
        if not text:
            continue
        segments = split_sentences(text)
        if not segments:
            continue
        start = float(utt.get("start", 0.0))
        end = float(utt.get("end", start))
        total_len = max(1, sum(len(seg) for seg in segments))
        cursor = start
        for s_idx, segment in enumerate(segments):
            part = strip_filler_phrases(segment)
            if not part:
                continue
            ratio = len(segment) / total_len
            seg_dur = max(0.2, (end - start) * ratio)
            seg_end = end if s_idx == len(segments) - 1 else min(end, cursor + seg_dur)
            synthesized.append(
                {
                    "id": f"sent-u{u_idx:04d}-{s_idx:03d}",
                    "start": round(cursor, 2),
                    "end": round(seg_end, 2),
                    "text": part,
                }
            )
            cursor = seg_end
    return synthesized


def build_semantic_blocks(
    sentences: list[dict[str, Any]],
    min_sentences: int,
    max_sentences: int,
    max_blocks: int,
) -> list[dict[str, Any]]:
    if not sentences:
        return []

    total = len(sentences)
    min_s = max(1, min_sentences)
    max_s = max(min_s, max_sentences)
    min_possible_blocks = max(1, math.ceil(total / max_s))
    max_possible_blocks = max(1, total // min_s)

    preferred_blocks = max(1, round(total / max(1, (min_s + max_s) / 2)))
    if max_blocks > 0:
        preferred_blocks = min(preferred_blocks, max_blocks)

    target_blocks = max(min_possible_blocks, min(max_possible_blocks, preferred_blocks))

    base = total // target_blocks
    remainder = total % target_blocks
    counts = [base + (1 if i < remainder else 0) for i in range(target_blocks)]

    blocks: list[dict[str, Any]] = []
    cursor = 0
    for count in counts:
        chunk = sentences[cursor : cursor + count]
        cursor += count
        if not chunk:
            continue
        text = " ".join(s.get("text", "") for s in chunk).strip()
        blocks.append(
            {
                "id": f"block-{len(blocks):03d}",
                "start": round(float(chunk[0].get("start", 0.0)), 2),
                "end": round(float(chunk[-1].get("end", chunk[0].get("start", 0.0))), 2),
                "sentence_count": len(chunk),
                "sentences": chunk,
                "text": text,
            }
        )

    return blocks


def trim_chars(text: str, max_chars: int) -> str:
    src = normalize_plain_text(text)
    if len(src) <= max_chars:
        return src
    return src[: max(1, max_chars - 1)].rstrip() + "…"


def extract_keywords(text: str, limit: int) -> list[str]:
    tokens = re.findall(r"[A-Za-zА-Яа-яЁё0-9]{3,}", normalize_plain_text(text).lower())
    freq: dict[str, int] = {}
    for token in tokens:
        if token in STOPWORDS_RU:
            continue
        freq[token] = freq.get(token, 0) + 1
    ranked = sorted(freq.items(), key=lambda item: (-item[1], -len(item[0]), item[0]))
    return [word for word, _ in ranked[:limit]]


def normalize_scene_text(text: str, max_chars: int, max_words: int | None = None) -> str:
    cleaned = strip_editorial_noise(text)
    if max_words and max_words > 0:
        tokens = [t for t in cleaned.split(" ") if t]
        cleaned = " ".join(tokens[:max_words])
    polished = trim_chars(cleaned, max_chars)
    return polished or "Смысловой блок"

def hash_score(text: str, low: float = 0.3, high: float = 0.95) -> float:
    if not text:
        return low
    raw = sum(ord(ch) for ch in text) % 1000
    k = raw / 1000.0
    return low + (high - low) * k


def phrase_from_sentence(text: str, max_words: int = 7) -> str:
    cleaned = normalize_scene_text(
        text,
        TEXT_LIMITS["insight"],
        WORD_LIMITS["insight"],
    )
    if not cleaned:
        return ""
    words = [w for w in re.findall(r"[A-Za-zА-Яа-яЁё0-9-]+", cleaned) if len(w) > 1]
    if not words:
        return cleaned
    return " ".join(words[:max_words])


def build_scene_from_semantic_block(block: dict[str, Any], idx: int) -> dict[str, Any]:
    text = normalize_plain_text(str(block.get("text") or ""))
    sentences = block.get("sentences") or []
    sentence_texts = [normalize_plain_text(str(s.get("text") or "")) for s in sentences]
    sentence_texts = [s for s in sentence_texts if s]

    keywords = extract_keywords(text, 6)
    keyword_main = keywords[0] if keywords else "фокус"
    keyword_pair = " ".join(keywords[:2]) if keywords else "смысловой блок"

    title_1 = normalize_scene_text(
        phrase_from_sentence(sentence_texts[0] if sentence_texts else text, 6),
        TEXT_LIMITS["title_line"],
        WORD_LIMITS["title_line"],
    )
    title_2_source = sentence_texts[1] if len(sentence_texts) > 1 else text
    title_2 = normalize_scene_text(
        phrase_from_sentence(title_2_source, 7),
        TEXT_LIMITS["title_line"],
        WORD_LIMITS["title_line"],
    )
    title_3 = normalize_scene_text(
        f"Контекст: {keyword_main}",
        TEXT_LIMITS["title_line"],
        WORD_LIMITS["title_line"],
    )
    title_4 = normalize_scene_text(
        "Решение и действие",
        TEXT_LIMITS["title_line"],
        WORD_LIMITS["title_line"],
    )

    insight_base = " ".join(sentence_texts[:2]) if sentence_texts else text
    insight = normalize_scene_text(
        insight_base,
        TEXT_LIMITS["insight"],
        WORD_LIMITS["insight"],
    )

    cta_seed = sentence_texts[-1] if sentence_texts else "Сверить цифры и план действий"
    cta = normalize_scene_text(
        phrase_from_sentence(cta_seed, 8),
        TEXT_LIMITS["cta"],
        WORD_LIMITS["cta"],
    )

    steps_raw = sentence_texts[1:4] if len(sentence_texts) >= 4 else sentence_texts[:3]
    while len(steps_raw) < 3:
        steps_raw.append(f"Проверить гипотезу {len(steps_raw) + 1}")
    steps = [
        normalize_scene_text(
            phrase_from_sentence(step, 8),
            TEXT_LIMITS["step"],
            WORD_LIMITS["step"],
        )
        for step in steps_raw[:3]
    ]

    mode = "full" if idx % 2 == 0 else "mini"
    bars_labels = keywords[:4] if keywords else ["фокус", "данные", "риск", "действие"]
    while len(bars_labels) < 4:
        bars_labels.append(f"метрика {len(bars_labels) + 1}")

    return {
        "start": round(float(block.get("start", 0.0)), 2),
        "end": round(float(block.get("end", 0.0)), 2),
        "mode": mode,
        "titleLines": [title_1, title_2, title_3, title_4],
        "steps": steps,
        "insight": insight,
        "cta": cta,
        "keyword": normalize_scene_text(
            keyword_pair,
            TEXT_LIMITS["keyword"],
            WORD_LIMITS["keyword"],
        ),
        "bars": [
            {
                "label": normalize_scene_text(
                    bars_labels[0],
                    TEXT_LIMITS["bar_label"],
                    WORD_LIMITS["bar_label"],
                ),
                "value": round(hash_score(text + "1"), 2),
            },
            {
                "label": normalize_scene_text(
                    bars_labels[1],
                    TEXT_LIMITS["bar_label"],
                    WORD_LIMITS["bar_label"],
                ),
                "value": round(hash_score(text + "2"), 2),
            },
            {
                "label": normalize_scene_text(
                    bars_labels[2],
                    TEXT_LIMITS["bar_label"],
                    WORD_LIMITS["bar_label"],
                ),
                "value": round(hash_score(text + "3"), 2),
            },
            {
                "label": normalize_scene_text(
                    bars_labels[3],
                    TEXT_LIMITS["bar_label"],
                    WORD_LIMITS["bar_label"],
                ),
                "value": round(hash_score(text + "4"), 2),
            },
        ],
    }


def merge_semantic_blocks_for_scenes(
    semantic_blocks: list[dict[str, Any]], target_scenes: int
) -> list[dict[str, Any]]:
    if not semantic_blocks:
        return []
    if target_scenes <= 0 or len(semantic_blocks) <= target_scenes:
        return semantic_blocks

    base = len(semantic_blocks) // target_scenes
    remainder = len(semantic_blocks) % target_scenes
    group_sizes = [base + (1 if i < remainder else 0) for i in range(target_scenes)]

    merged: list[dict[str, Any]] = []
    cursor = 0
    for g_idx, size in enumerate(group_sizes):
        chunk = semantic_blocks[cursor : cursor + size]
        cursor += size
        if not chunk:
            continue

        sentences: list[dict[str, Any]] = []
        for block in chunk:
            sentences.extend(block.get("sentences") or [])

        merged.append(
            {
                "id": f"scene-block-{g_idx:03d}",
                "start": float(chunk[0].get("start", 0.0)),
                "end": float(chunk[-1].get("end", chunk[0].get("start", 0.0))),
                "sentence_count": sum(int(b.get("sentence_count", 0)) for b in chunk),
                "sentences": sentences,
                "text": " ".join(str(b.get("text") or "") for b in chunk).strip(),
            }
        )

    return merged


def build_fallback_scene_plan(
    utterances: list[dict[str, Any]],
    semantic_blocks: list[dict[str, Any]],
    duration: float,
    max_scenes: int,
) -> list[dict[str, Any]]:
    if not utterances:
        return [
            {
                "start": 0.0,
                "end": round(duration, 2),
                "mode": "full",
                "titleLines": ["Сцена без транскрипта", "Проверьте источник", "Проверьте язык", "Повторите запуск"],
                "steps": ["1. Проверить звук", "2. Проверить речь", "3. Перезапустить транскрипт"],
                "insight": "Deepgram не вернул utterances; проверьте входной файл и язык.",
                "cta": "Перезапустить анализ речи",
                "keyword": "Диагностика",
                "bars": [
                    {"label": "Хук", "value": 0.4},
                    {"label": "Суть", "value": 0.5},
                    {"label": "Кейс", "value": 0.45},
                    {"label": "CTA", "value": 0.55},
                ],
            }
        ]

    if semantic_blocks:
        source_blocks = merge_semantic_blocks_for_scenes(semantic_blocks, max_scenes)
    else:
        source_blocks = [
            {
                "start": 0.0,
                "end": duration,
                "text": " ".join(str(u.get("text") or "") for u in utterances),
                "sentences": [],
            }
        ]

    scenes = [build_scene_from_semantic_block(block, i) for i, block in enumerate(source_blocks)]

    return normalize_scene_plan({"scenes": scenes, "_utterances": utterances}, duration)


def build_llm_prompt_payload(
    utterances: list[dict[str, Any]],
    semantic_blocks: list[dict[str, Any]],
    deepgram_payload: dict[str, Any],
    duration: float,
    max_scenes: int,
    target_scene_count: int,
    overlay_coverage_percent: int,
    script_context: str = "",
) -> dict[str, Any]:
    summary = ((deepgram_payload.get("results", {}).get("summary") or {}).get("short") or "").strip()
    topics_segments = (
        ((deepgram_payload.get("results", {}).get("topics") or {}).get("results") or {})
        .get("topics", {})
        .get("segments", [])
    )
    intents_segments = (
        ((deepgram_payload.get("results", {}).get("intents") or {}).get("results") or {})
        .get("intents", {})
        .get("segments", [])
    )

    compact_topics = []
    for seg in topics_segments[:24]:
        topics = [t.get("topic") for t in seg.get("topics", []) if t.get("topic")]
        compact_topics.append(
            {
                "text": (seg.get("text") or "")[:180],
                "topics": topics[:4],
            }
        )

    compact_intents = []
    for seg in intents_segments[:24]:
        intents = [t.get("intent") for t in seg.get("intents", []) if t.get("intent")]
        compact_intents.append(
            {
                "text": (seg.get("text") or "")[:180],
                "intents": intents[:4],
            }
        )

    compact_utterances = [
        {
            "start": round(float(u["start"]), 2),
            "end": round(float(u["end"]), 2),
            "text": normalize_scene_text(str(u["text"]), TEXT_LIMITS["utterance"]),
        }
        for u in utterances
    ]

    compact_semantic_blocks = [
        {
            "start": round(float(b.get("start", 0.0)), 2),
            "end": round(float(b.get("end", 0.0)), 2),
            "sentence_count": int(b.get("sentence_count", 0)),
            "summary_hint": normalize_scene_text(str(b.get("text", "")), TEXT_LIMITS["semantic_summary"]),
            "sentences": [
                normalize_scene_text(str(s.get("text", "")), TEXT_LIMITS["semantic_sentence"])
                for s in (b.get("sentences") or [])[:10]
            ],
        }
        for b in semantic_blocks[: max_scenes + 3]
    ]

    return {
        "goal": "Действуй как профессиональный режиссер монтажа и смысловой редактор. Твоя задача — извлечь из речи спикера конкретные смысловые beats для вертикального экспертного видео. Каждый beat должен быть привязан к реальным словам из транскрипта и иметь ясный заголовок, подзаголовок и визуальную метафору для иллюстрации.",
        "reference_adaptation_rule": "Не придумывай новую тему. Повтори суть референса/речи своими словами в нашем экспертном стиле: конкретно, резко, без копирования формулировок и без добавления чужой предметной области.",
        "philosophy": {
            "KEEP_SIDE": "Используй для блоков ХУК и КОНТЕКСТ. Лицо диктора должно быть открыто. Это моменты установления контакта.",
            "KEEP_FULL": "Используй для блоков АНАЛИЗ, РИСКИ, РЕШЕНИЕ. Это 'мясо' ролика. Перекрывай диктора полностью, чтобы зритель впился глазами в цифры и инфографику.",
            "CUT_VISUAL": "Если в тексте видишь повторы, запинки или слова-паразиты — не ставь туда сцену. Оставляй чистое видео диктора.",
            "TRANSITION": "Сцены должны начинаться на начале сильной фразы и заканчиваться ровно на финальной точке мысли."
        },
        "constraints": {
            "duration_seconds": duration,
            "max_scenes": max_scenes,
            "overlay_coverage_percent": overlay_coverage_percent,
            "target_scene_count": target_scene_count,
            "target_scenes": f"Верни ровно {target_scene_count} scenes, если в речи есть столько отдельных мыслей. Процент перебивок задан пользователем: {overlay_coverage_percent}%. Не возвращай меньше сцен без крайней причины.",
            "scene_min_seconds": 2.0,
            "scene_max_seconds": 5.5,
            "visual_density": "Карточка должна появляться на сильной фразе, а не закрывать весь ролик.",
            "timing_anchor_rule": "Карточка должна появляться за 0.1-0.3 сек до первого слова новой темы. Не ставь start после того, как смысловой блок уже начался.",
            "block_names": ["ПРОБЛЕМА", "ПРИЧИНА", "ПОВОРОТ", "ДЕЙСТВИЕ", "РИСК", "ВЫВОД"],
            "editorial_strategy": {
                "philosophy": "МЕНЬШЕ — ЭТО БОЛЬШЕ. Аватар должен быть виден 70% времени. Плашка — это акцент, а не фон.",
                "selection_criteria": "Выбирай только САМЫЕ важные моменты: факты, цифры, ключевые инсайты. Пропускай вводные слова, шутки, воду и общие рассуждения.",
                "max_scenes": "8-12 сцен на весь ролик. НЕ БОЛЬШЕ.",
                "pacing": "Между плашками должен быть огромный разрыв — 10-20 секунд чистого аватара.",
                "layout_choice": {
                    "side": "Для заголовков разделов и ключевых мыслей (максимум 2-3 слова).",
                    "full": "ТОЛЬКО если есть данные, цифры или нужно визуализировать сложный процесс."
                }
            },
            "pacing_rules": {
                "breathing_room": "ОБЯЗАТЕЛЬНО оставляй разрыв 4-6 секунд между сценами. Пример: если Сцена 1 закончилась на 15.0с, то Сцена 2 должна начаться НЕ РАНЬШЕ 19.0с.",
                "no_consecutive": "Запрещено ставить сцены встык. Между ними всегда должно быть чистое видео с диктором.",
                "max_consecutive_full_screen": "12 секунд. Каждая плашка — это короткий инсайт, а не бесконечная простыня текста."
            },
            "bars_count": 4,
            "title_lines_count": 4,
            "rewrite_rules": {
                "expert_tone": "Используй терминологию только из исходного транскрипта и semantic_blocks. Не добавляй чужую предметную область.",
                "no_verbatim_transcript": True,
                "focus_on_essence": True,
                "news_editorial_copy": "Пиши как живой редактор новостного YouTube: title = человеческий крючок, а не цитата и не рубрика. Title должен назвать конкретную ставку для зрителя: деньги, штраф, отказ, заморозка, дедлайн, лишний шаг, что потеряет или что может вернуть. Subtitle объясняет механизм: почему, кому, когда, чем грозит, что проверить.",
                "title_role": "title: 2-4 слова, короткий человеческий заголовок. Не повторяй речь дословно. Избегай канцелярита и абстракций вроде 'контроль стал нормой', 'статус решает выплату', 'главное условие'. Лучше конкретно: 'СЧЕТ МОГУТ ЗАМОРОЗИТЬ', 'ВЫЧЕТ ДАДУТ НЕ ВСЕМ', 'ВТОРАЯ МАШИНА МЕШАЕТ'.",
                "subtitle_role": "subtitle: 5-8 слов, простое пояснение без лозунга. Он должен добавлять фактуру к title: условие, риск, срок, документ, действие или последствие. Не пересказывает title другими словами.",
                "no_generic_titles": "Запрещены общие заголовки вроде 'ГЛАВНЫЙ РИСК', 'ЧТО МЕНЯЕТСЯ', 'ФОКУС НА ГЛАВНОМ', если в них нет конкретного смысла из речи.",
                "anchor_required": "Каждый beat обязан иметь 2-5 anchorWords — точные слова или короткие фразы из транскрипта, по которым понятно, почему этот beat существует.",
                "visual_required": "Каждый beat обязан иметь visualIdea и visualElements. visualIdea — это конкретный кадр с субъектом, местом, объектами и конфликтом/действием, а не тема или список существительных.",
                "hook_required": "Первая scene обязана иметь hookText и hookPromise для первых 1-3 секунд. Hook — это не пересказ, а scroll-stopper: конфликт, боль или сильное обещание, основанные на речи.",
                "visual_text_policy": "Для обычных иллюстраций и метафор не проси текст внутри картинки. Для реалистичных интерфейсов, документов, писем, таблиц и чек-листов короткий текст внутри изображения разрешен, если он является частью объекта."
            },
        },
        "required_output_json_shape": {
            "scenes": [
                {
                    "start": 0.0,
                    "end": 3.8,
                    "blockName": "ПРОБЛЕМА",
                    "mode": "full",
                    "anchorWords": ["точные слова из транскрипта", "еще одна якорная фраза"],
                    "sourceText": "короткая цитата/пересказ фразы из этого окна",
                    "referenceEssence": "какую суть референса этот beat повторяет своими словами",
                    "hookText": "сильная фраза для первых секунд, только для первой сцены",
                    "hookPromise": "что зритель поймет или избежит, только для первой сцены",
                    "title": "КОНКРЕТНЫЙ ЗАГОЛОВОК",
                    "subtitle": "ясное объяснение смысла в 5-10 слов",
                    "opener": "короткий триггер 3-5 слов",
                    "insight": "почему этот момент важен",
                    "visualIdea": "конкретный кадр: субъект + место + объекты + конфликт/действие",
                    "visualType": "illustration | realistic_interface | realistic_document | realistic_screenshot",
                    "visualElements": ["объект 1", "объект 2", "действие/конфликт"]
                }
            ]
        },
        "transcript_summary": summary,
        "script_context": normalize_scene_text(script_context, 3200, 520),
        "topics_segments": compact_topics,
        "intents_segments": compact_intents,
        "semantic_blocks": compact_semantic_blocks,
        "utterances": compact_utterances,
    }


def generate_scene_plan_llm(
    utterances: list[dict[str, Any]],
    semantic_blocks: list[dict[str, Any]],
    deepgram_payload: dict[str, Any],
    duration: float,
    max_scenes: int,
    target_scene_count: int,
    overlay_coverage_percent: int,
    llm_model: str,
    timeout_sec: int,
    script_context: str = "",
    repair_feedback: str = "",
    attempt: int = 1,
) -> dict[str, Any]:
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    api_key = openrouter_key or os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY")
    if not api_key:
        raise RuntimeError("LLM API key is missing. Set OPENROUTER_API_KEY, OPENAI_API_KEY or LLM_API_KEY.")
    default_base = "https://openrouter.ai/api/v1" if openrouter_key else "https://api.openai.com/v1"
    base_url = (os.environ.get("LLM_BASE_URL") or default_base).rstrip("/")
    url = f"{base_url}/chat/completions"

    prompt_payload = build_llm_prompt_payload(
        utterances=utterances,
        semantic_blocks=semantic_blocks,
        deepgram_payload=deepgram_payload,
        duration=duration,
        max_scenes=max_scenes,
        target_scene_count=target_scene_count,
        overlay_coverage_percent=overlay_coverage_percent,
        script_context=script_context,
    )
    if repair_feedback:
        prompt_payload["previous_quality_gate_error"] = normalize_scene_text(repair_feedback, 1800, 260)
        prompt_payload["repair_instruction"] = (
            "Исправь только причину ошибки quality gate. Особенно важно: все title должны быть "
            "уникальными, предметными, 2-5 слов, без общих формулировок и повторов. "
            "Title и subtitle должны выполнять разные редакторские роли: title дает конфликт/суть, "
            "subtitle добавляет условие, риск, срок, документ, действие или последствие."
        )

    system_prompt = """
Ты — элитный смысловой редактор и режиссер монтажа. Верни монтажный план как набор конкретных смысловых beats, строго основанных на транскрипте.

ЖЕСТКИЕ ПРАВИЛА:
1. Каждый scene — один отдельный смысл: проблема, причина, поворот, действие, риск или вывод.
2. Верни количество scenes, заданное в constraints.target_scene_count. Это число рассчитано из пользовательской настройки процента перебивок. Не склеивай весь ролик в слишком малое количество сцен.
3. start/end должны попадать в реальный момент речи, где звучат anchorWords. start ставь на начало фразы или за 0.1-0.3 сек до первого anchorWord, чтобы плашка сопровождала новую тему сразу, как в новостях. Длительность сцены 2.0-5.5 секунд.
4. title: 2-4 слова, как в новостях и retention-роликах: не цитата, а человеческий крючок. Назови конкретную ставку для зрителя: деньги, штраф, отказ, заморозка, дедлайн, лишний шаг, что потеряет или что может вернуть. Хорошо: "СЧЕТ МОГУТ ЗАМОРОЗИТЬ", "ВЫЧЕТ ДАДУТ НЕ ВСЕМ", "ВТОРАЯ МАШИНА МЕШАЕТ", "НДС ПОПРОСЯТ ЗАРАНЕЕ". Плохо: "СТАТУС РЕШАЕТ ВЫПЛАТУ", "КОНТРОЛЬ СТАЛ НОРМОЙ", "ГЛАВНОЕ УСЛОВИЕ". Не копируй сырую речь и не начинай с вводных: "с одной стороны", "вроде как", "получается", "то есть", "вам".
5. subtitle: 5-8 слов, объясняет механику крючка простыми словами: почему важно, кому грозит, какой риск, какое условие, срок, документ, действие или последствие. Не повторяй title и не пересказывай его теми же словами.
6. anchorWords: 2-5 точных слов/коротких фраз из транскрипта. Это якоря, которые доказывают, что сцена привязана к речи.
7. Первая scene обязана иметь hookText и hookPromise. Это первые 1-3 секунды: боль, конфликт или сильное обещание, чтобы зритель не свайпнул.
8. referenceEssence: коротко объясни, какую суть исходной речи/референса ты повторяешь своими словами. Не копируй формулировку, сохраняй смысл.
9. visualIdea: конкретный кадр для KIE-иллюстрации, минимум 8 слов: субъект + место + 2-3 объекта + конфликт/действие. Нельзя возвращать тему, категорию или список существительных.
10. visualType: "illustration" для обычных метафор; "realistic_interface", "realistic_document" или "realistic_screenshot", если нужен реалистичный скрин/документ.
11. visualElements: 3-6 конкретных объектов/персонажей/действий, которые можно нарисовать. Не используй графики, если речь не про данные/проценты.
12. Для обычной illustration запрещен текст внутри картинки. Для realistic_interface/document/screenshot разрешены короткие UI/document labels как часть объекта.
13. Не добавляй чужую предметную область. Если в речи нет проливов, танкеров, стран, флагов, санкций, портов или войны — не упоминай их.
14. Если в payload есть script_context, считай его авторитетным сценарием видео. Используй его для тематики, текста карточек и visualIdea; Deepgram нужен для таймингов.
15. Все title должны быть уникальными. Если тема повторяется, назови новый аспект: срок, документ, риск, действие, исключение или результат.
16. Если payload содержит previous_quality_gate_error, исправь эту ошибку в новой версии плана.
17. Хорошая пара title/subtitle:
    title: "ВОЗВРАТ НЕ ДЛЯ ВСЕХ"
    subtitle: "решают статус, документы и срок подачи"
    Плохая пара:
    title: "СТОРОНЫ ВАМ ГОТОВЫ"
    subtitle: "с одной стороны, вам готовы вернуть часть налогов"
18. Ответ — только валидный JSON. Никакого Markdown.

ПРИМЕРЫ visualIdea:
Плохо: "документы, подтверждающие гражданство"
Хорошо: "крупный план официальных документов с печатями, паспортом и красной предупреждающей меткой на столе"
Плохо: "новые правила"
Хорошо: "человек перед закрытой стойкой регистрации держит папку документов, рядом горит красный сигнал проверки"

ФОРМАТ:
{
  "scenes": [
    {
      "start": 0.0,
      "end": 3.8,
      "blockName": "ПРОБЛЕМА",
      "mode": "full",
      "anchorWords": ["убыточна", "не масштабируется"],
      "sourceText": "фраза из транскрипта, на которой основан beat",
      "referenceEssence": "спикер объясняет, что старую модель нельзя чинить косметикой",
      "hookText": "НЕ ЧИНИ ТО, ЧТО НЕ МАСШТАБИРУЕТСЯ",
      "hookPromise": "за 20 секунд поймете, где теряется рост",
      "title": "МОДЕЛЬ НЕ СХОДИТСЯ",
      "subtitle": "цифры показывают, что система не работает",
      "opener": "цифры уже говорят",
      "insight": "если модель не масштабируется, ее нельзя чинить косметикой",
      "visualIdea": "сломанный бизнес-механизм с красной трещиной и человеком перед выбором",
      "visualType": "illustration",
      "visualElements": ["сломанный механизм", "красная трещина", "предприниматель", "таблица с убытком без текста"]
    }
  ]
}
"""
    user_prompt = json.dumps(prompt_payload, ensure_ascii=False)

    req_payload: dict[str, Any] = {
        "model": llm_model,
        "temperature": min(0.45, 0.2 + max(0, attempt - 1) * 0.08),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    gemini_provider = os.environ.get("OPENROUTER_GEMINI_PROVIDER", "google-vertex/global").strip()
    if openrouter_key and "gemini" in llm_model.lower() and gemini_provider:
        req_payload["provider"] = {
            "order": [gemini_provider],
            "only": [gemini_provider],
            "allow_fallbacks": False,
        }
    # response_format is not universally supported by OpenRouter upstream models.
    if "openrouter.ai" not in base_url:
        req_payload["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if "openrouter.ai" in base_url:
        headers["HTTP-Referer"] = os.environ.get("OPENROUTER_SITE_URL", "https://local.hyperframes")
        headers["X-Title"] = os.environ.get("OPENROUTER_APP_NAME", "hyperframes-smart-montage")
    raw = http_post_json(url, req_payload, headers, timeout=timeout_sec)
    choices = raw.get("choices") or []
    if not choices:
        raise RuntimeError(f"LLM response has no choices: {raw}")
    content = ((choices[0].get("message") or {}).get("content") or "").strip()
    if not content:
        raise RuntimeError(f"LLM returned empty content: {raw}")

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(content[start : end + 1])


def _norm_bars(raw_bars: Any) -> list[dict[str, Any]]:
    bars = raw_bars if isinstance(raw_bars, list) else []
    out: list[dict[str, Any]] = []
    for i in range(4):
        candidate = bars[i] if i < len(bars) and isinstance(bars[i], dict) else {}
        label = normalize_scene_text(
            str(candidate.get("label") or f"Показатель {i + 1}"),
            TEXT_LIMITS["bar_label"],
            WORD_LIMITS["bar_label"],
        )
        try:
            value = float(candidate.get("value", 0.55))
        except (TypeError, ValueError):
            value = 0.55
        value = max(0.15, min(1.0, value))
        out.append({"label": label, "value": round(value, 2)})
    return out


GENERIC_SCENE_TEXTS = {
    "смысловой блок",
    "ключевая мысль",
    "важный момент",
    "важная мысль",
    "тема",
    "хук",
    "контекст",
    "анализ",
    "итог",
    "фокус",
    "сфокусируйтесь на важном",
    "hook",
    "context",
    "analysis",
}


def _is_generic_scene_text(value: str) -> bool:
    text = normalize_plain_text(value).lower()
    if not text:
        return True
    compact = re.sub(r"[^a-zа-яё0-9]+", " ", text).strip()
    if compact in GENERIC_SCENE_TEXTS:
        return True
    if "смыслов" in compact and "блок" in compact:
        return True
    if re.fullmatch(r"шаг\s*\d+", compact):
        return True
    if re.fullmatch(r"показатель\s*\d+", compact):
        return True
    if compact.startswith("глубокая аналитическая мысль"):
        return True
    if "сфокус" in compact and "важн" in compact:
        return True
    return False


def _is_weak_visual_idea(value: str) -> bool:
    text = normalize_plain_text(value).lower()
    if _is_generic_scene_text(text):
        return True
    words = text.split()
    if len(words) < 6:
        return True

    action_markers = (
        "держ",
        "стоит",
        "сидит",
        "смотр",
        "лежит",
        "горит",
        "виден",
        "видна",
        "сравнив",
        "открыт",
        "закрыт",
        "показыв",
        "сталкива",
        "выдел",
        "перечерк",
    )
    scene_markers = (
        "крупный план",
        "на столе",
        "перед",
        "рядом",
        "в центре",
        "на экране",
        "за столом",
        "у стойки",
        "в кабинете",
        "сигнал",
        "метка",
        "барьер",
    )
    has_action = any(marker in text for marker in action_markers)
    has_scene = any(marker in text for marker in scene_markers)
    if len(words) < 8 and not (has_action or has_scene):
        return True

    noun_list_hint = "," in text and not has_action and not has_scene
    if noun_list_hint:
        return True
    return False


def _scene_title_token_count(value: str) -> int:
    return len(re.findall(r"[A-Za-zА-Яа-яЁё0-9]{3,}", normalize_plain_text(value)))


def _meaningful_editorial_words(value: str) -> list[str]:
    words = re.findall(r"[A-Za-zА-Яа-яЁё0-9-]{4,}", normalize_plain_text(value).lower())
    return [word for word in words if word not in STOPWORDS_RU]


def _text_overlap_ratio(left: str, right: str) -> float:
    left_words = _meaningful_editorial_words(left)
    right_words = set(_meaningful_editorial_words(right))
    if not left_words or not right_words:
        return 0.0
    return len([word for word in left_words if word in right_words]) / len(left_words)


def _title_subtitle_overlap_ratio(title: str, subtitle: str) -> float:
    return max(_text_overlap_ratio(title, subtitle), _text_overlap_ratio(subtitle, title))


def _has_editorial_noise(value: str) -> bool:
    text = normalize_plain_text(value).lower()
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in EDITORIAL_NOISE_PATTERNS)


def _is_title_subtitle_duplicate(title: str, subtitle: str) -> bool:
    clean_title = normalize_plain_text(title).lower()
    clean_subtitle = normalize_plain_text(subtitle).lower()
    if not clean_title or not clean_subtitle:
        return False
    if clean_title == clean_subtitle:
        return True
    if len(clean_title) >= 10 and clean_title in clean_subtitle:
        return True
    if len(clean_subtitle) >= 10 and clean_subtitle in clean_title:
        return True
    return _title_subtitle_overlap_ratio(clean_title, clean_subtitle) >= 0.58


def _scene_window_text(utterances: list[dict[str, Any]], start: float, end: float) -> str:
    if not utterances:
        return ""
    parts: list[str] = []
    for utt in utterances:
        try:
            u_start = float(utt.get("start", 0.0))
            u_end = float(utt.get("end", u_start))
        except (TypeError, ValueError):
            continue
        if u_end <= start or u_start >= end:
            continue
        text = normalize_plain_text(str(utt.get("text") or ""))
        if text:
            parts.append(text)
    return normalize_plain_text(" ".join(parts))


def _build_semantic_fallback(window_text: str, block_name: str) -> dict[str, Any]:
    source = normalize_plain_text(window_text)
    if not source:
        source = f"{block_name} ключевой тезис и практический вывод"
    sentences = split_sentences(source) or [source]
    keywords = extract_keywords(source, 4)
    keyword_text = " ".join(keywords[:2]) if keywords else phrase_from_sentence(sentences[0], 3)

    title = normalize_scene_text(phrase_from_sentence(sentences[0], 6), 40, 6)
    insight = normalize_scene_text(" ".join(sentences[:2]), TEXT_LIMITS["insight"], WORD_LIMITS["insight"])
    cta = normalize_scene_text(phrase_from_sentence(sentences[-1], 8), TEXT_LIMITS["cta"], WORD_LIMITS["cta"])
    keyword = normalize_scene_text(keyword_text, TEXT_LIMITS["keyword"], WORD_LIMITS["keyword"])

    steps_raw = sentences[:3]
    while len(steps_raw) < 3:
        steps_raw.append(sentences[-1])
    steps = [
        normalize_scene_text(phrase_from_sentence(step, 8), TEXT_LIMITS["step"], WORD_LIMITS["step"])
        for step in steps_raw[:3]
    ]
    facts = [
        normalize_scene_text(phrase_from_sentence(step, 10), 80, 12)
        for step in steps_raw[:3]
    ]
    return {
        "title": title,
        "insight": insight,
        "cta": cta,
        "keyword": keyword,
        "steps": steps,
        "facts": facts,
    }


def _default_chapter_title(block_name: str) -> str:
    upper = normalize_plain_text(block_name).upper()
    if "ХУК" in upper or "HOOK" in upper:
        return "О чем это видео"
    if "КОНТЕКСТ" in upper or "CONTEXT" in upper or "SETUP" in upper:
        return "Что происходит на рынке"
    if "АНАЛИЗ" in upper or "ANALYSIS" in upper:
        return "Ключевой разбор"
    if "РИСК" in upper or "RISK" in upper:
        return "Главные риски"
    if "РЕШЕН" in upper or "SOLUTION" in upper:
        return "Практическое решение"
    if "ИТОГ" in upper or "SUMMARY" in upper:
        return "Главный вывод"
    return "Новая глава"


def _build_chapter_meta(scene: dict[str, Any]) -> tuple[str, str]:
    block_name = str(scene.get("blockName") or "")

    title_candidates = [
        str(scene.get("title") or ""),
        str(scene.get("keyword") or ""),
        " ".join([str(x) for x in (scene.get("titleLines") or []) if str(x).strip()]),
        _default_chapter_title(block_name),
    ]
    chapter_title = ""
    for candidate in title_candidates:
        text = normalize_scene_text(candidate, 56, 8)
        if text and not _is_generic_scene_text(text):
            chapter_title = text
            break
    if not chapter_title:
        chapter_title = _default_chapter_title(block_name)

    subtitle_candidates = [
        str(scene.get("insight") or ""),
        " ".join([str(x) for x in (scene.get("facts") or []) if str(x).strip()][:1]),
        " ".join([str(x) for x in (scene.get("steps") or []) if str(x).strip()][:1]),
        str(scene.get("cta") or ""),
    ]
    chapter_subtitle = ""
    for candidate in subtitle_candidates:
        text = normalize_scene_text(candidate, 88, 14)
        if text and not _is_generic_scene_text(text):
            chapter_subtitle = text
            break
    if not chapter_subtitle:
        chapter_subtitle = "Смотрите ключевую мысль блока."

    return chapter_title, chapter_subtitle


def _normalize_opener_text(value: str) -> str:
    candidate = normalize_plain_text(value)
    if not candidate:
        return ""
    candidate = re.sub(r"[\"'«»]+", "", candidate).strip()
    opener = normalize_scene_text(candidate, TEXT_LIMITS["opener"], WORD_LIMITS["opener"])
    if _is_generic_scene_text(opener):
        return ""
    return opener


def _build_scene_opener(
    *,
    raw_item: dict[str, Any],
    title: str,
    keyword: str,
    block_name: str,
    semantic_fallback: dict[str, Any],
    window_text: str,
) -> str:
    title_lines = raw_item.get("titleLines") if isinstance(raw_item.get("titleLines"), list) else []
    title_lines_text = " ".join(str(x) for x in title_lines if str(x).strip())
    window_phrase = phrase_from_sentence(window_text, WORD_LIMITS["opener"])
    candidates = [
        str(raw_item.get("opener") or ""),
        title,
        keyword,
        title_lines_text,
        str(semantic_fallback.get("title") or ""),
        window_phrase,
        _default_chapter_title(block_name),
    ]
    for candidate in candidates:
        opener = _normalize_opener_text(str(candidate or ""))
        if opener:
            return opener
    return _normalize_opener_text(_default_chapter_title(block_name)) or "Ключевая мысль"


def _norm_string_list(value: Any, *, max_items: int, max_chars: int, max_words: int | None = None) -> list[str]:
    items = value if isinstance(value, list) else []
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        text = normalize_scene_text(str(raw), max_chars, max_words)
        if _is_generic_scene_text(text):
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= max_items:
            break
    return out


def _derive_anchor_words_from_text(text: str, limit: int = 4) -> list[str]:
    source = normalize_plain_text(text)
    if not source:
        return []

    anchors: list[str] = []
    seen: set[str] = set()

    for sentence in split_sentences(source):
        phrase = phrase_from_sentence(sentence, 4)
        if phrase and not _is_generic_scene_text(phrase):
            key = phrase.lower()
            if key not in seen:
                seen.add(key)
                anchors.append(normalize_scene_text(phrase, 40, 5))
                if len(anchors) >= limit:
                    return anchors

    for keyword in extract_keywords(source, limit * 2):
        key = keyword.lower()
        if key in seen:
            continue
        seen.add(key)
        anchors.append(normalize_scene_text(keyword, 40, 5))
        if len(anchors) >= limit:
            break

    return anchors


def _anchor_phrase_tokens(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", normalize_plain_text(text).lower().replace("ё", "е"))
        if token
    ]


def _find_anchor_phrase_start(
    words: list[dict[str, Any]],
    phrase: str,
    *,
    start: float,
    end: float,
    max_lookback: float = 8.0,
    max_lookahead: float = 2.5,
) -> float | None:
    phrase_tokens = _anchor_phrase_tokens(phrase)
    if not phrase_tokens or not words:
        return None

    window_start = max(0.0, start - max_lookback)
    window_end = end + max_lookahead
    tokens = [str(word.get("_token") or _anchor_token(str(word.get("text") or ""))) for word in words]
    candidates: list[tuple[float, float]] = []

    phrase_len = len(phrase_tokens)
    if phrase_len > 1:
        for idx in range(0, max(0, len(tokens) - phrase_len + 1)):
            if tokens[idx : idx + phrase_len] != phrase_tokens:
                continue
            try:
                match_start = float(words[idx].get("start", 0.0))
            except (TypeError, ValueError):
                continue
            if match_start < window_start or match_start > window_end:
                continue
            distance = abs(match_start - start)
            if match_start <= start + 0.2:
                distance *= 0.65
            candidates.append((distance, match_start))
    else:
        # Single-word anchors are useful only when they are distinctive in this window.
        token = phrase_tokens[0]
        if len(token) < 4:
            return None
        matches: list[float] = []
        for idx, current in enumerate(tokens):
            if current != token:
                continue
            try:
                match_start = float(words[idx].get("start", 0.0))
            except (TypeError, ValueError):
                continue
            if window_start <= match_start <= window_end:
                matches.append(match_start)
        if len(matches) == 1:
            candidates.append((abs(matches[0] - start), matches[0]))
        else:
            nearby = [t for t in matches if abs(t - start) <= 2.0]
            for match_start in nearby[:2]:
                candidates.append((abs(match_start - start), match_start))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][1]


def _semantic_sentence_start_near(
    semantic_blocks: list[dict[str, Any]],
    target_time: float,
    *,
    max_shift_back: float = 5.0,
) -> float | None:
    for block in semantic_blocks:
        sentences = block.get("sentences") if isinstance(block.get("sentences"), list) else []
        for sentence in sentences:
            try:
                sent_start = float(sentence.get("start", 0.0))
                sent_end = float(sentence.get("end", sent_start))
            except (TypeError, ValueError):
                continue
            if sent_start <= target_time <= sent_end and target_time - sent_start <= max_shift_back:
                return sent_start
    return None


def _semantic_block_anchor_start(
    semantic_blocks: list[dict[str, Any]],
    anchor_candidates: list[str],
    *,
    start: float,
    end: float,
    max_lookback: float = 8.0,
    max_lookahead: float = 2.5,
) -> float | None:
    if not semantic_blocks or not anchor_candidates:
        return None
    window_start = max(0.0, start - max_lookback)
    window_end = end + max_lookahead
    normalized_anchors = [
        normalize_plain_text(anchor).lower().replace("ё", "е")
        for anchor in anchor_candidates
        if normalize_plain_text(anchor)
    ]
    for block in semantic_blocks:
        try:
            block_start = float(block.get("start", 0.0))
            block_end = float(block.get("end", block_start))
        except (TypeError, ValueError):
            continue
        if block_end < window_start or block_start > window_end:
            continue
        block_text = normalize_plain_text(str(block.get("text") or "")).lower().replace("ё", "е")
        if any(anchor and anchor in block_text for anchor in normalized_anchors):
            return max(0.0, block_start)
    return None


def _snap_scene_timing_to_anchor(
    *,
    item: dict[str, Any],
    words: list[dict[str, Any]],
    semantic_blocks: list[dict[str, Any]],
    start: float,
    end: float,
    total_duration: float,
) -> tuple[float, float]:
    raw_anchors = item.get("anchorWords") if isinstance(item.get("anchorWords"), list) else []
    anchor_candidates = [
        str(anchor)
        for anchor in raw_anchors
        if normalize_plain_text(str(anchor))
    ]
    source_text = normalize_plain_text(str(item.get("sourceText") or ""))
    if source_text:
        anchor_candidates.extend(_derive_anchor_words_from_text(source_text, limit=3))
    if not anchor_candidates:
        return start, end

    max_lookback = 8.0
    max_lookahead = 2.5
    anchor_starts: list[float] = []
    for anchor in anchor_candidates:
        anchor_start = _find_anchor_phrase_start(
            words,
            anchor,
            start=start,
            end=end,
            max_lookback=max_lookback,
            max_lookahead=max_lookahead,
        )
        if anchor_start is not None:
            anchor_starts.append(anchor_start)

    if anchor_starts:
        # Prefer the first anchor that already happened before the planned card.
        past_or_now = [t for t in anchor_starts if t <= start + 0.25]
        anchor_start = min(past_or_now) if past_or_now else min(anchor_starts, key=lambda t: abs(t - start))
    else:
        semantic_start = _semantic_block_anchor_start(
            semantic_blocks,
            anchor_candidates,
            start=start,
            end=end,
            max_lookback=max_lookback,
            max_lookahead=max_lookahead,
        )
        if semantic_start is None:
            return start, end
        anchor_start = semantic_start

    sentence_start = _semantic_sentence_start_near(semantic_blocks, anchor_start)
    if sentence_start is not None and 0.0 <= anchor_start - sentence_start <= 5.0:
        anchor_start = sentence_start

    if anchor_start < start - max_lookback or anchor_start > end + max_lookahead:
        return start, end

    preroll = 0.18
    snapped_start = max(0.0, round(anchor_start - preroll, 2))
    if abs(snapped_start - start) < 0.12:
        return start, end

    original_duration = max(1.2, end - start)
    max_duration = 7.0
    if snapped_start < start:
        snapped_end = min(total_duration, max(end, snapped_start + original_duration), snapped_start + max_duration)
    else:
        snapped_end = min(total_duration, snapped_start + original_duration)
    if snapped_end - snapped_start < 1.2:
        snapped_end = min(total_duration, snapped_start + 1.2)
    return snapped_start, round(snapped_end, 2)


def _derive_visual_elements_from_text(text: str, title: str = "", limit: int = 6) -> list[str]:
    source = normalize_plain_text(" ".join([text, title]))
    keywords = [
        normalize_scene_text(keyword, 80, 8)
        for keyword in extract_keywords(source, limit * 2)
        if not _is_generic_scene_text(keyword)
    ]

    lower = source.lower()
    elements: list[str] = []

    def add(item: str) -> None:
        cleaned = normalize_scene_text(item, 80, 8)
        if not cleaned:
            return
        if cleaned.lower() in {existing.lower() for existing in elements}:
            return
        elements.append(cleaned)

    if any(token in lower for token in ("документ", "паспорт", "гражданств", "закон", "правил")):
        add("официальные документы с печатями")
        add("паспорт или удостоверение")
        add("красная предупреждающая метка")
    if any(token in lower for token in ("деньг", "налог", "штраф", "выплат", "сумм", "рубл")):
        add("пачка документов с расчетами")
        add("красный финансовый маркер")
        add("человек у стола с бумагами")
    if any(token in lower for token in ("срок", "июн", "июл", "месяц", "дата", "календар")):
        add("календарь с выделенной датой")
        add("настольные часы")
    if any(token in lower for token in ("провер", "риск", "отказ", "запрет", "ошиб")):
        add("красный сигнал проверки")
        add("закрытая дверь или барьер")

    for keyword in keywords:
        add(keyword)
        if len(elements) >= limit:
            break

    defaults = [
        "человек в момент выбора",
        "папка с важными бумагами",
        "контрастный свет на главном объекте",
        "визуальный конфликт в центре кадра",
    ]
    for item in defaults:
        if len(elements) >= 3:
            break
        add(item)

    return elements[:limit]


def _build_concrete_visual_idea(scene: dict[str, Any], window_text: str, source_text: str) -> str:
    title = normalize_plain_text(str(scene.get("title") or ""))
    subtitle = normalize_plain_text(str(scene.get("subtitle") or ""))
    source = normalize_plain_text(" ".join([source_text, window_text, title, subtitle]))
    lower = source.lower()
    elements = _derive_visual_elements_from_text(source, title, limit=4)

    if any(token in lower for token in ("документ", "паспорт", "гражданств", "закон", "правил")):
        idea = "крупный план официальных документов с печатями, паспортом и красной предупреждающей меткой на столе"
    elif any(token in lower for token in ("срок", "июн", "июл", "месяц", "дата", "календар")):
        idea = "человек держит папку документов перед календарем с выделенной датой и красным сигналом дедлайна"
    elif any(token in lower for token in ("деньг", "налог", "штраф", "выплат", "сумм", "рубл")):
        idea = "человек за столом сравнивает финансовые бумаги, рядом красная метка риска и пачка счетов"
    elif any(token in lower for token in ("провер", "риск", "отказ", "запрет", "ошиб")):
        idea = "человек стоит перед закрытым барьером проверки, держа папку, рядом горит красный предупреждающий сигнал"
    else:
        seed = ", ".join(elements[:3]) if elements else normalize_scene_text(source, 120, 14)
        idea = f"конкретная экспертная сцена: человек сталкивается с выбором, вокруг {seed}, в центре виден конфликт решения"

    return normalize_scene_text(idea, 220, 28)


def _scene_editorial_source(scene: dict[str, Any], window_text: str) -> str:
    anchors = scene.get("anchorWords") if isinstance(scene.get("anchorWords"), list) else []
    return normalize_plain_text(
        " ".join(
            [
                str(scene.get("sourceText") or ""),
                window_text,
                str(scene.get("referenceEssence") or ""),
                str(scene.get("insight") or ""),
                str(scene.get("subtitle") or ""),
                " ".join(str(x) for x in anchors if str(x).strip()),
            ]
        )
    )


def _scene_editorial_concepts(scene: dict[str, Any], source: str, limit: int = 8) -> list[str]:
    anchors = scene.get("anchorWords") if isinstance(scene.get("anchorWords"), list) else []
    raw_items: list[str] = [str(x) for x in anchors if normalize_plain_text(str(x))]
    raw_items.extend(extract_keywords(source, limit * 3))

    concepts: list[str] = []
    seen: set[str] = set()
    for raw in raw_items:
        cleaned = strip_editorial_noise(raw)
        if not cleaned:
            continue
        words = [
            word
            for word in re.findall(r"[A-Za-zА-Яа-яЁё0-9-]{3,}", cleaned.lower())
            if word not in STOPWORDS_RU and word not in RAW_TITLE_WORDS
        ]
        if not words:
            continue
        candidate = normalize_scene_text(" ".join(words[:3]), 36, 3)
        key = normalize_plain_text(candidate).lower()
        if not key or key in seen or _is_generic_scene_text(candidate):
            continue
        seen.add(key)
        concepts.append(candidate)
        if len(concepts) >= limit:
            break
    return concepts


def _title_looks_like_raw_transcript(title: str) -> bool:
    clean = normalize_plain_text(title).lower()
    if not clean:
        return True
    words = re.findall(r"[A-Za-zА-Яа-яЁё0-9-]+", clean)
    if not words:
        return True
    if words[-1] in TRAILING_WEAK_TITLE_WORDS:
        return True
    if any(word in RAW_TITLE_WORDS for word in words):
        return True
    if _has_editorial_noise(title):
        return True
    return False


def _copy_has_raw_transcript_words(value: str) -> bool:
    words = re.findall(r"[A-Za-zА-Яа-яЁё0-9-]+", normalize_plain_text(value).lower())
    return any(word in RAW_TITLE_WORDS for word in words)


def _source_has_any(source: str, needles: tuple[str, ...]) -> bool:
    lower = source.lower()
    return any(needle in lower for needle in needles)


def _editorial_title_candidates(scene: dict[str, Any], source: str, index: int) -> list[str]:
    concepts = _scene_editorial_concepts(scene, source, limit=8)
    primary = concepts[0].upper() if concepts else ""
    secondary = concepts[1].upper() if len(concepts) > 1 else ""
    block = normalize_plain_text(str(scene.get("blockName") or "")).upper()
    lower = source.lower()

    candidates: list[str] = []

    if _source_has_any(lower, ("июн", "новых правил", "новые правила")) and _source_has_any(lower, ("штраф", "стоить", "дорого", "закон")):
        candidates.extend(["В ИЮНЕ МОГУТ ОШТРАФОВАТЬ", "ПРАВИЛА УДАРЯТ ПО ДЕНЬГАМ"])
    if _source_has_any(lower, ("вычет", "сем", "ребен", "ндфл")):
        candidates.extend(["ВЫЧЕТ ДАДУТ НЕ ВСЕМ", "ДЕНЬГИ ВЕРНУТ НЕ ВСЕМ"])
    if _source_has_any(lower, ("6%", "6 %", "шесть", "льготн")) and _source_has_any(lower, ("ндфл", "ставк", "возврат", "вернут")):
        candidates.extend(["6% МОЖНО ВЕРНУТЬ", "РАЗНИЦУ МОГУТ ДОПЛАТИТЬ"])
    if _source_has_any(lower, ("доход", "прожиточ", "минимум", "лимит")):
        candidates.extend(["ЛИМИТ ДОХОДА ЖЕСТКИЙ", "ЛИШНИЕ РУБЛИ ОТРЕЖУТ ВЫПЛАТУ"])
    if _source_has_any(lower, ("официальн", "гражданств", "резидент", "183", "ста")):
        candidates.extend(["БЕЛАЯ РАБОТА ОБЯЗАТЕЛЬНА", "БЕЗ СТАТУСА НЕ ВЕРНУТ"])
    if _source_has_any(lower, ("автомоб", "машин", "квартир", "имуществ")):
        candidates.extend(["ВТОРАЯ МАШИНА МЕШАЕТ", "ИМУЩЕСТВО ТОЖЕ ПРОВЕРЯТ"])
    if _source_has_any(lower, ("зарубеж", "счет")) and _source_has_any(lower, ("1 июня", "отчит", "движен")):
        candidates.extend(["ДО 1 ИЮНЯ ОТЧИТАЙТЕСЬ", "СЧЕТА ЗА ГРАНИЦЕЙ ПРОВЕРЯТ"])
    if _source_has_any(lower, ("115", "блокиров", "банк", "счет")):
        candidates.extend(["СЧЕТ МОГУТ ЗАМОРОЗИТЬ", "БАНК ДАСТ СУТКИ"])
    if _source_has_any(lower, ("патент", "усн", "упрощен")):
        candidates.extend(["ПАТЕНТ ЕЩЕ МОЖНО СПАСТИ", "УСН МОЖНО ВЕРНУТЬ"])
    if _source_has_any(lower, ("ндс", "акциз", "импорт", "импортер")):
        candidates.extend(["НДС ПОПРОСЯТ ЗАРАНЕЕ", "ИМПОРТ СТАНЕТ ДОРОЖЕ"])
    if _source_has_any(lower, ("маркетплейс", "покупател", "потребител", "чек")):
        candidates.extend(["ЗАПЛАТИТ ПОКУПАТЕЛЬ", "ЦЕНА УЙДЕТ В ЧЕК"])
    if _source_has_any(lower, ("контроль", "гайки", "провер", "схем")):
        candidates.extend(["СТАРЫЕ СХЕМЫ НЕ ПРОЙДУТ", "ПРОВЕРКИ СТАНУТ ОБЫЧНЫМИ"])

    if _source_has_any(lower, ("код", "кода")) and _source_has_any(lower, ("фур", "границ", "тамож")):
        candidates.extend(["БЕЗ КОДА НЕ ПРОПУСТЯТ", "КОД РЕШАЕТ ПРОХОД"])
    if _source_has_any(lower, ("заявлен", "заявк", "подат", "подач")):
        candidates.extend(["ЗАЯВЛЕНИЕ НЕ ГАРАНТИЯ", "ПОДАЧА РЕШАЕТ СРОК"])
    if _source_has_any(lower, ("налог", "деньг", "возврат", "сумм", "выплат")):
        candidates.extend(["ВОЗВРАТ НЕ ДЛЯ ВСЕХ", "ДЕНЬГИ ВЕРНУТ ПО УСЛОВИЯМ"])
    if _source_has_any(lower, ("документ", "паспорт", "справк", "подтвержд", "бумаг")):
        candidates.extend(["ДОКУМЕНТ РЕШАЕТ ИСХОД", "БЕЗ БУМАГ НЕ ПРИМУТ"])
    if _source_has_any(lower, ("срок", "дедлайн", "дат", "месяц", "июн", "июл")):
        candidates.extend(["СРОК РЕШАЕТ ИСХОД", "ДЕДЛАЙН ЛОМАЕТ ПЛАН"])
    if _source_has_any(lower, ("провер", "отказ", "риск", "ошиб", "запрет", "нельзя")):
        candidates.extend(["РИСК ВСКРОЕТ ПРОВЕРКА", "ОШИБКА СТОИТ ДОРОГО"])

    if "РИСК" in block:
        candidates.extend(["РИСК НЕ ВИДЕН СРАЗУ", "ОШИБКА СТОИТ ДОРОГО"])
    elif "ПРОБЛ" in block:
        candidates.extend(["ГДЕ ЛОМАЕТСЯ СХЕМА", "ПРОБЛЕМА В УСЛОВИЯХ"])
    elif "ПРИЧ" in block:
        candidates.extend(["ПРИЧИНА В ДЕТАЛЯХ", "СИСТЕМА ЛОМАЕТСЯ ЗДЕСЬ"])
    elif "ДЕЙСТ" in block or "РЕШЕН" in block:
        candidates.extend(["ЧТО ДЕЛАТЬ СЕЙЧАС", "ШАГ НЕЛЬЗЯ ПРОПУСТИТЬ"])
    elif "ВЫВ" in block or "ИТОГ" in block:
        candidates.extend(["ИТОГ РЕШАЕТ ПОРЯДОК", "ГЛАВНОЕ В СЛЕДУЮЩЕМ ШАГЕ"])

    if primary and secondary:
        candidates.append(f"{primary}: В ЧЕМ РИСК")
        candidates.append(f"{primary} РЕШАЕТ {secondary}")
    if primary:
        candidates.append(f"{primary}: ГЛАВНОЕ УСЛОВИЕ")
        candidates.append(f"{primary} МЕНЯЕТ ИСХОД")

    for sentence in split_sentences(source):
        phrase = normalize_scene_text(phrase_from_sentence(sentence, 5), 40, 6)
        if phrase:
            candidates.append(phrase.upper())

    candidates.append(f"НОВЫЙ АСПЕКТ {index + 1}")
    return candidates


def _editorial_subtitle_candidates(scene: dict[str, Any], source: str, title: str) -> list[str]:
    lower = source.lower()
    candidates: list[str] = []

    for sentence in split_sentences(source):
        cleaned = normalize_scene_text(sentence, 90, 12)
        if len(cleaned.split()) < 5:
            continue
        if _is_generic_scene_text(cleaned) or _copy_has_raw_transcript_words(cleaned) or _is_title_subtitle_duplicate(title, cleaned):
            continue
        candidates.append(cleaned)

    if _source_has_any(lower, ("код", "кода")) and _source_has_any(lower, ("фур", "границ", "тамож")):
        candidates.append("без нужного кода фуру остановят на границе")
    if _source_has_any(lower, ("вычет", "сем", "ребен", "ндфл")):
        candidates.append("вернут деньги только при совпадении условий")
    if _source_has_any(lower, ("6%", "6 %", "шесть", "льготн")) and _source_has_any(lower, ("ндфл", "ставк", "возврат", "вернут")):
        candidates.append("Соцфонд доплатит разницу после проверки")
    if _source_has_any(lower, ("доход", "прожиточ", "минимум", "лимит")):
        candidates.append("лишние рубли могут забрать всю выплату")
    if _source_has_any(lower, ("официальн", "гражданств", "резидент", "183", "ста")):
        candidates.append("без статуса и стажа возврата не будет")
    if _source_has_any(lower, ("автомоб", "машин", "квартир", "имуществ")):
        candidates.append("имущество семьи тоже проверят")
    if _source_has_any(lower, ("зарубеж", "счет")) and _source_has_any(lower, ("1 июня", "отчит", "движен")):
        candidates.append("по зарубежным счетам ждут движение денег")
    if _source_has_any(lower, ("115", "блокиров", "банк", "счет")):
        candidates.append("на ответ по 115-ФЗ всего сутки")
    if _source_has_any(lower, ("патент", "усн", "упрощен")):
        candidates.append("УСН разрешат оформить задним числом")
    if _source_has_any(lower, ("ндс", "акциз", "импорт", "импортер")):
        candidates.append("импортер платит до продажи товара")
    if _source_has_any(lower, ("маркетплейс", "покупател", "потребител", "чек")):
        candidates.append("маркетплейсы переложат издержки в чек")
    if _source_has_any(lower, ("контроль", "гайки", "провер", "схем")):
        candidates.append("контроль стал частью обычной работы")
    if _source_has_any(lower, ("заявлен", "заявк", "подат", "подач")):
        candidates.append("важны основание, срок и точность подачи")
    if _source_has_any(lower, ("налог", "деньг", "возврат", "сумм", "выплат")):
        candidates.append("сумма зависит от основания и проверки")
    if _source_has_any(lower, ("документ", "паспорт", "справк", "подтвержд", "бумаг")):
        candidates.append("решают подтверждения, сроки и точность данных")
    if _source_has_any(lower, ("срок", "дедлайн", "дат", "месяц", "июн", "июл")):
        candidates.append("после дедлайна сценарий становится дороже")
    if _source_has_any(lower, ("провер", "отказ", "риск", "ошиб", "запрет", "нельзя")):
        candidates.append("ошибка проявится уже на проверке")

    candidates.extend(
        [
            "важны условия, сроки и следующий шаг",
            "здесь решает не обещание, а подтверждение",
            "сначала проверьте основание и порядок действий",
        ]
    )
    return candidates


def _repair_scene_plan_editorial_copy(scenes: list[dict[str, Any]], utterances: list[dict[str, Any]]) -> None:
    seen_titles: set[str] = set()
    repaired: list[str] = []

    for index, scene in enumerate(scenes):
        try:
            start = float(scene.get("start", 0.0))
            end = float(scene.get("end", start))
        except (TypeError, ValueError):
            start = 0.0
            end = 0.0

        window_text = _scene_window_text(utterances, start, end)
        source = _scene_editorial_source(scene, window_text)
        title = normalize_scene_text(str(scene.get("title") or ""), 40, 6).upper()
        subtitle = normalize_scene_text(str(scene.get("subtitle") or ""), 90, 12)
        scene["title"] = title
        scene["subtitle"] = subtitle
        title_key = normalize_plain_text(title).lower()

        needs_title = (
            _is_generic_scene_text(title)
            or _scene_title_token_count(title) < 2
            or title_key in seen_titles
            or _title_looks_like_raw_transcript(title)
        )
        if needs_title:
            for candidate in _editorial_title_candidates(scene, source, index):
                candidate = normalize_scene_text(candidate, 40, 6).upper()
                candidate_key = normalize_plain_text(candidate).lower()
                if not candidate_key or candidate_key in seen_titles:
                    continue
                if _is_generic_scene_text(candidate) or _scene_title_token_count(candidate) < 2:
                    continue
                if _title_looks_like_raw_transcript(candidate):
                    continue
                title = candidate
                title_key = candidate_key
                scene["title"] = title
                scene["titleLines"] = [title]
                scene["opener"] = title
                scene["keyword"] = normalize_scene_text(title, TEXT_LIMITS["keyword"], WORD_LIMITS["keyword"])
                repaired.append(f"{index}:title")
                break

        seen_titles.add(title_key)

        needs_subtitle = (
            _is_generic_scene_text(subtitle)
            or len(subtitle.split()) < 4
            or _has_editorial_noise(subtitle)
            or _copy_has_raw_transcript_words(subtitle)
            or _is_title_subtitle_duplicate(title, subtitle)
        )
        if needs_subtitle:
            for candidate in _editorial_subtitle_candidates(scene, source, title):
                candidate = normalize_scene_text(candidate, 90, 12)
                if len(candidate.split()) < 4:
                    continue
                if _is_generic_scene_text(candidate) or _has_editorial_noise(candidate):
                    continue
                if _is_title_subtitle_duplicate(title, candidate):
                    continue
                scene["subtitle"] = candidate
                if not scene.get("insight") or _is_generic_scene_text(str(scene.get("insight"))):
                    scene["insight"] = candidate
                repaired.append(f"{index}:subtitle")
                break

    if repaired:
        eprint("Repaired editorial title/subtitle copy before quality gate: " + "; ".join(repaired[:16]))


def _repair_scene_plan_metadata(scenes: list[dict[str, Any]], utterances: list[dict[str, Any]]) -> None:
    for index, scene in enumerate(scenes):
        try:
            start = float(scene.get("start", 0.0))
            end = float(scene.get("end", start))
        except (TypeError, ValueError):
            continue

        window_text = _scene_window_text(utterances, start, end)
        source_text = normalize_plain_text(str(scene.get("sourceText") or "")) or window_text
        repair_source = normalize_plain_text(" ".join([source_text, window_text]))

        anchors = scene.get("anchorWords") if isinstance(scene.get("anchorWords"), list) else []
        clean_anchors = _norm_string_list(anchors, max_items=5, max_chars=40, max_words=5)
        if len(clean_anchors) < 2:
            for anchor in _derive_anchor_words_from_text(repair_source, limit=5):
                if anchor.lower() not in {x.lower() for x in clean_anchors}:
                    clean_anchors.append(anchor)
                if len(clean_anchors) >= 2:
                    break
        scene["anchorWords"] = clean_anchors[:5]

        subtitle = normalize_scene_text(str(scene.get("subtitle") or ""), 90, 12)
        scene["subtitle"] = subtitle
        if _is_generic_scene_text(subtitle) or len(subtitle.split()) < 4:
            sentences = split_sentences(source_text or window_text)
            replacement = ""
            for sentence in sentences:
                candidate = normalize_scene_text(sentence, 90, 12)
                if candidate and not _is_generic_scene_text(candidate) and len(candidate.split()) >= 4:
                    replacement = candidate
                    break
            if replacement:
                scene["subtitle"] = replacement

        visual_idea = normalize_scene_text(str(scene.get("visualIdea") or ""), 220, 28)
        if _is_weak_visual_idea(visual_idea):
            visual_idea = _build_concrete_visual_idea(scene, window_text, source_text)
        scene["visualIdea"] = visual_idea

        visual_elements = _norm_string_list(
            scene.get("visualElements"),
            max_items=6,
            max_chars=80,
            max_words=10,
        )
        if len(visual_elements) < 3:
            for element in _derive_visual_elements_from_text(repair_source, str(scene.get("title") or ""), limit=6):
                if element.lower() not in {x.lower() for x in visual_elements}:
                    visual_elements.append(element)
                if len(visual_elements) >= 3:
                    break
        scene["visualElements"] = visual_elements[:6]

        if index == 0:
            hook_text = normalize_scene_text(str(scene.get("hookText") or ""), 64, 8)
            if _is_generic_scene_text(hook_text) or len(hook_text.split()) < 2:
                scene["hookText"] = normalize_scene_text(
                    str(scene.get("title") or scene.get("opener") or scene.get("subtitle") or ""),
                    64,
                    8,
                )
            hook_promise = normalize_scene_text(str(scene.get("hookPromise") or ""), 96, 12)
            if _is_generic_scene_text(hook_promise) or len(hook_promise.split()) < 4:
                scene["hookPromise"] = normalize_scene_text(
                    str(scene.get("subtitle") or scene.get("insight") or source_text or window_text),
                    96,
                    12,
                )


def _candidate_scene_titles(scene: dict[str, Any], window_text: str) -> list[str]:
    current_title = normalize_plain_text(str(scene.get("title") or ""))
    source = normalize_plain_text(
        " ".join(
            [
                str(scene.get("sourceText") or ""),
                str(scene.get("subtitle") or ""),
                str(scene.get("referenceEssence") or ""),
                str(scene.get("insight") or ""),
                window_text,
            ]
        )
    )
    anchors = scene.get("anchorWords") if isinstance(scene.get("anchorWords"), list) else []
    clean_anchors = [
        normalize_scene_text(str(anchor), 40, 5)
        for anchor in anchors
        if normalize_plain_text(str(anchor))
    ]
    candidates: list[str] = []

    for anchor in clean_anchors:
        if current_title and anchor.lower() not in current_title.lower():
            candidates.append(f"{current_title} {anchor}")

    for i in range(len(clean_anchors) - 1):
        candidates.append(f"{clean_anchors[i]} {clean_anchors[i + 1]}")

    for sentence in split_sentences(source):
        candidates.append(phrase_from_sentence(sentence, 5))

    keywords = extract_keywords(source, 10)
    for i in range(0, max(0, len(keywords) - 1), 2):
        candidates.append(f"{keywords[i]} {keywords[i + 1]}")

    if current_title:
        candidates.append(current_title)
    return candidates


def _repair_scene_plan_titles(scenes: list[dict[str, Any]], utterances: list[dict[str, Any]]) -> None:
    seen_titles: set[str] = set()
    repaired: list[str] = []

    for index, scene in enumerate(scenes):
        title = normalize_scene_text(str(scene.get("title") or ""), 40, 6)
        title_key = normalize_plain_text(title).lower()
        needs_repair = (
            _is_generic_scene_text(title)
            or _scene_title_token_count(title) < 2
            or title_key in seen_titles
        )
        if not needs_repair:
            seen_titles.add(title_key)
            continue

        try:
            start = float(scene.get("start", 0.0))
            end = float(scene.get("end", start))
        except (TypeError, ValueError):
            start = 0.0
            end = 0.0
        window_text = _scene_window_text(utterances, start, end)
        candidates = _candidate_scene_titles(scene, window_text)
        candidates.append(f"АСПЕКТ ВИДЕО {index + 1}")

        replacement = ""
        for candidate in candidates:
            candidate = normalize_scene_text(candidate, 40, 6).upper()
            candidate_key = normalize_plain_text(candidate).lower()
            if not candidate_key or candidate_key in seen_titles:
                continue
            if _is_generic_scene_text(candidate) or _scene_title_token_count(candidate) < 2:
                continue
            replacement = candidate
            break

        if replacement:
            previous = title or "<empty>"
            scene["title"] = replacement
            scene["titleLines"] = [replacement]
            scene["opener"] = replacement
            scene["keyword"] = normalize_scene_text(replacement, TEXT_LIMITS["keyword"], WORD_LIMITS["keyword"])
            title_key = normalize_plain_text(replacement).lower()
            repaired.append(f"{index}:{previous}->{replacement}")
        seen_titles.add(title_key)

    if repaired:
        eprint("Repaired scene titles before quality gate: " + "; ".join(repaired[:12]))


def validate_scene_plan_quality(
    scenes: list[dict[str, Any]],
    duration: float,
    *,
    require_visuals: bool = True,
) -> None:
    if not scenes:
        raise RuntimeError("LLM scene-plan is empty; refusing to render fallback cards")

    min_required = 1
    min_required = _min_required_scene_count(duration)
    if len(scenes) < min_required:
        raise RuntimeError(
            f"LLM scene-plan returned only {len(scenes)} scene(s); expected at least {min_required} for duration={duration}s"
        )

    errors: list[str] = []
    seen_titles: set[str] = set()
    for idx, scene in enumerate(scenes):
        label = f"scene[{idx}]"
        title = normalize_plain_text(str(scene.get("title") or ""))
        subtitle = normalize_plain_text(str(scene.get("subtitle") or ""))
        visual_idea = normalize_plain_text(str(scene.get("visualIdea") or ""))
        anchor_words = scene.get("anchorWords") if isinstance(scene.get("anchorWords"), list) else []
        visual_elements = scene.get("visualElements") if isinstance(scene.get("visualElements"), list) else []

        if _is_generic_scene_text(title) or _scene_title_token_count(title) < 2:
            errors.append(f"{label} has weak title: {title!r}")
        if _has_editorial_noise(title) or _title_looks_like_raw_transcript(title):
            errors.append(f"{label} has raw-transcript title: {title!r}")
        if title.lower() in seen_titles:
            errors.append(f"{label} repeats title: {title!r}")
        seen_titles.add(title.lower())
        if _is_generic_scene_text(subtitle) or len(subtitle.split()) < 4:
            errors.append(f"{label} has weak subtitle: {subtitle!r}")
        if _has_editorial_noise(subtitle) or _copy_has_raw_transcript_words(subtitle):
            errors.append(f"{label} has raw-transcript subtitle: {subtitle!r}")
        if _is_title_subtitle_duplicate(title, subtitle):
            errors.append(f"{label} title/subtitle duplicate each other: {title!r} / {subtitle!r}")
        if len([x for x in anchor_words if normalize_plain_text(str(x))]) < 2:
            errors.append(f"{label} needs at least 2 anchorWords")
        if require_visuals:
            if _is_weak_visual_idea(visual_idea):
                errors.append(f"{label} has weak visualIdea: {visual_idea!r}")
            if len([x for x in visual_elements if normalize_plain_text(str(x))]) < 3:
                errors.append(f"{label} needs at least 3 visualElements")
        if idx == 0:
            hook_text = normalize_plain_text(str(scene.get("hookText") or ""))
            hook_promise = normalize_plain_text(str(scene.get("hookPromise") or ""))
            if _is_generic_scene_text(hook_text) or len(hook_text.split()) < 2:
                errors.append(f"{label} has weak hookText: {hook_text!r}")
            if _is_generic_scene_text(hook_promise) or len(hook_promise.split()) < 4:
                errors.append(f"{label} has weak hookPromise: {hook_promise!r}")

    if errors:
        raise RuntimeError("LLM scene-plan failed quality gate: " + " | ".join(errors[:12]))


def _base_min_required_scene_count(duration: float) -> int:
    if duration <= 35:
        return 4
    if duration <= 75:
        return 5
    return 1


def _min_required_scene_count(duration: float, target_scene_count: int | None = None) -> int:
    base = _base_min_required_scene_count(duration)
    if target_scene_count and target_scene_count > 0:
        return max(base, int(target_scene_count))
    return base


def _target_scene_count_from_coverage(duration: float, overlay_coverage_percent: int, max_scenes: int) -> int:
    coverage = max(0, min(100, int(overlay_coverage_percent)))
    if coverage <= 0:
        return 0
    target_overlay_seconds = duration * (coverage / 100.0)
    # Cards usually hold 3.5-4.5 seconds. Use 4.1s as the planning average.
    estimated = int(math.ceil(target_overlay_seconds / 4.1))
    base = _base_min_required_scene_count(duration)
    upper = max(1, int(max_scenes or 8))
    return max(1, min(upper, max(base, estimated)))


def _scene_overlaps_existing(start: float, end: float, scenes: list[dict[str, Any]]) -> bool:
    for scene in scenes:
        try:
            cur_start = float(scene.get("start", 0.0))
            cur_end = float(scene.get("end", cur_start))
        except (TypeError, ValueError):
            continue
        if max(start, cur_start) < min(end, cur_end):
            return True
    return False


def _build_repair_scene_from_utterance(utterance: dict[str, Any], index: int, duration: float) -> dict[str, Any] | None:
    text = normalize_plain_text(str(utterance.get("text") or ""))
    if not text:
        return None
    try:
        start = float(utterance.get("start", 0.0))
        end = float(utterance.get("end", start + 4.0))
    except (TypeError, ValueError):
        return None
    if end <= start:
        end = start + 4.0
    end = min(duration, max(start + 2.0, end))
    if end <= start:
        return None

    keywords = extract_keywords(text, 5)
    title_source = phrase_from_sentence(text, 5)
    title = normalize_scene_text(title_source, 40, 6)
    subtitle = normalize_scene_text(text, 90, 12)
    visual_seed = " ".join(keywords[:3]) if keywords else title
    visual_elements = keywords[:4] or [title, "человек", "выбор"]
    while len(visual_elements) < 3:
        visual_elements.append(["человек", "документ", "решение"][len(visual_elements)])

    return {
        "start": round(start, 2),
        "end": round(end, 2),
        "blockName": "ДОПОЛНЕНИЕ",
        "mode": "full" if index % 2 == 0 else "mini",
        "title": title,
        "subtitle": subtitle,
        "value": None,
        "unit": "%",
        "facts": [subtitle],
        "anchorWords": _derive_anchor_words_from_text(text, limit=5),
        "sourceText": normalize_scene_text(text, 220, 28),
        "referenceEssence": normalize_scene_text(text, 180, 24),
        "hookText": "",
        "hookPromise": "",
        "visualIdea": normalize_scene_text(
            f"Реалистичная экспертная иллюстрация про {visual_seed}: человек сталкивается с выбором и видит последствие решения",
            220,
            28,
        ),
        "visualType": "illustration",
        "visualElements": visual_elements[:6],
        "titleLines": [title],
        "steps": [subtitle],
        "insight": subtitle,
        "cta": "",
        "keyword": normalize_scene_text(" ".join(keywords[:2]) or title, TEXT_LIMITS["keyword"], WORD_LIMITS["keyword"]),
        "opener": title,
        "bars": _norm_bars([]),
    }


def _ensure_min_scene_count(
    scenes: list[dict[str, Any]],
    utterances: list[dict[str, Any]],
    duration: float,
    target_scene_count: int | None = None,
) -> None:
    min_required = _min_required_scene_count(duration, target_scene_count)
    if len(scenes) >= min_required or not utterances:
        return

    candidates = sorted(
        utterances,
        key=lambda item: len(normalize_plain_text(str(item.get("text") or ""))),
        reverse=True,
    )
    for utterance in candidates:
        if len(scenes) >= min_required:
            break
        scene = _build_repair_scene_from_utterance(utterance, len(scenes), duration)
        if not scene:
            continue
        if _scene_overlaps_existing(float(scene["start"]), float(scene["end"]), scenes):
            continue
        seen_titles = {
            normalize_plain_text(str(existing.get("title") or "")).lower()
            for existing in scenes
        }
        title_key = normalize_plain_text(str(scene.get("title") or "")).lower()
        if title_key in seen_titles:
            anchors = _derive_anchor_words_from_text(str(scene.get("sourceText") or ""), limit=3)
            replacement = " ".join(anchors[:2]) if len(anchors) >= 2 else ""
            scene["title"] = normalize_scene_text(
                replacement or f"Новый аспект {len(scenes) + 1}",
                40,
                6,
            )
            if normalize_plain_text(str(scene.get("title") or "")).lower() in seen_titles:
                scene["title"] = normalize_scene_text(f"Новый аспект {len(scenes) + 1}", 40, 6)
            scene["titleLines"] = [scene["title"]]
            scene["opener"] = scene["title"]
        scenes.append(scene)

    scenes.sort(key=lambda item: float(item.get("start", 0.0)))


def normalize_scene_plan(
    raw: dict[str, Any],
    duration: float,
    *,
    require_visuals: bool = True,
) -> list[dict[str, Any]]:
    raw_scenes = raw.get("scenes")
    if not isinstance(raw_scenes, list):
        raw_scenes = []

    utterances_for_norm = raw.get("_utterances")
    if not isinstance(utterances_for_norm, list):
        utterances_for_norm = []
    transcript_words_for_norm = raw.get("_transcript_words")
    if not isinstance(transcript_words_for_norm, list):
        transcript_words_for_norm = []
    semantic_blocks_for_norm = raw.get("_semantic_blocks")
    if not isinstance(semantic_blocks_for_norm, list):
        semantic_blocks_for_norm = []
    try:
        target_scene_count = int(raw.get("_target_scene_count") or 0)
    except (TypeError, ValueError):
        target_scene_count = 0

    norm: list[dict[str, Any]] = []
    for i, item in enumerate(raw_scenes):
        if not isinstance(item, dict):
            continue
        try:
            start = float(item.get("start", 0.0))
            end = float(item.get("end", start + 5.0))
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue

        block_name = str(item.get("blockName") or "АНАЛИЗ").upper()
        is_hook = "ХУК" in block_name or "HOOK" in block_name
        is_context = "КОНТЕКСТ" in block_name or "CONTEXT" in block_name or "SETUP" in block_name
        is_cta = "CTA" in block_name or "ПРИЗЫВ" in block_name

        # Mode normalization for production preset: only mini/full are allowed.
        raw_mode = str(item.get("mode") or "full").lower().strip()
        if raw_mode in {"mini", "lower-third", "lower_third", "overlay", "side"}:
            mode = "mini"
        elif raw_mode in {"full", "insight", "chart", "clean", "face"}:
            mode = "full"
        else:
            mode = "full"
        if is_hook or is_context or is_cta:
            mode = "mini"  # Hooks and CTAs are always mini accents

        # SMART WORD SNAPPING
        def find_best_start(target_time: float, utterances: list[dict]) -> float:
            for utt in utterances:
                utt_start = utt.get("start", 0)
                if abs(utt_start - target_time) < 1.5:
                    return utt_start
            return target_time

        anchored_start, anchored_end = _snap_scene_timing_to_anchor(
            item=item,
            words=transcript_words_for_norm,
            semantic_blocks=semantic_blocks_for_norm,
            start=start,
            end=end,
            total_duration=duration,
        )
        if anchored_start != start or anchored_end != end:
            start, end = anchored_start, anchored_end
        else:
            start = find_best_start(start, utterances_for_norm)
        window_text = _scene_window_text(utterances_for_norm, start, end)
        semantic_fallback = _build_semantic_fallback(window_text, block_name)
        
        title_from_raw = str(item.get("title") or "").strip()
        title = title_from_raw

        if start >= duration:
            continue
        if end > duration:
            end = duration
        if end <= start:
            continue

        title_lines = item.get("titleLines") if isinstance(item.get("titleLines"), list) else []
        title_lines = [
            normalize_scene_text(str(x), TEXT_LIMITS["title_line"], WORD_LIMITS["title_line"])
            for x in title_lines
            if str(x).strip() and str(x) != "Смысловой блок"
        ][:2]

        steps = item.get("steps") if isinstance(item.get("steps"), list) else []
        steps = [
            normalize_scene_text(str(x), TEXT_LIMITS["step"], WORD_LIMITS["step"])
            for x in steps
            if str(x).strip() and "Уточнить" not in str(x) and "Объяснить" not in str(x)
        ][:3]

        # Extract new schema fields
        title = normalize_scene_text(title, 40, 6)
        # Primary numeric value for BIG_NUMBER
        raw_value = item.get("value")
        try:
            chart_value = float(raw_value) if raw_value is not None else None
        except (TypeError, ValueError):
            chart_value = None
        unit = str(item.get("unit") or "%")

        # Facts (synthesized statements, not quotes)
        raw_facts = item.get("facts") or []
        if not isinstance(raw_facts, list):
            raw_facts = []
        facts = [
            normalize_scene_text(str(f), 80, 12)
            for f in raw_facts
            if str(f).strip()
        ][:3]
        anchor_words = _norm_string_list(
            item.get("anchorWords"),
            max_items=5,
            max_chars=40,
            max_words=5,
        )
        visual_elements = _norm_string_list(
            item.get("visualElements"),
            max_items=6,
            max_chars=80,
            max_words=10,
        )
        visual_idea = normalize_scene_text(
            str(item.get("visualIdea") or ""), 220, 28
        )
        visual_type_raw = normalize_plain_text(str(item.get("visualType") or "illustration")).lower()
        visual_type = visual_type_raw if visual_type_raw in {
            "illustration",
            "realistic_interface",
            "realistic_document",
            "realistic_screenshot",
        } else "illustration"
        reference_essence = normalize_scene_text(
            str(item.get("referenceEssence") or ""), 180, 24
        )
        hook_text = normalize_scene_text(
            str(item.get("hookText") or ""), 64, 8
        )
        hook_promise = normalize_scene_text(
            str(item.get("hookPromise") or ""), 96, 12
        )
        source_text = normalize_scene_text(
            str(item.get("sourceText") or window_text or ""), 220, 28
        )
        subtitle = normalize_scene_text(
            str(item.get("subtitle") or ""), 90, 12
        )

        insight = normalize_scene_text(
            str(item.get("insight") or ""), TEXT_LIMITS["insight"], WORD_LIMITS["insight"]
        )
        cta = normalize_scene_text(
            str(item.get("cta") or ""), TEXT_LIMITS["cta"], WORD_LIMITS["cta"]
        )
        keyword = normalize_scene_text(
            str(item.get("keyword") or title or ""), TEXT_LIMITS["keyword"], WORD_LIMITS["keyword"]
        )
        opener = _build_scene_opener(
            raw_item=item,
            title=title,
            keyword=keyword,
            block_name=block_name,
            semantic_fallback=semantic_fallback,
            window_text=window_text,
        )

        # Legacy fields — kept for backward compatibility
        title_lines = item.get("titleLines") if isinstance(item.get("titleLines"), list) else []
        title_lines = [
            normalize_scene_text(str(x), TEXT_LIMITS["title_line"], WORD_LIMITS["title_line"])
            for x in title_lines
            if not _is_generic_scene_text(str(x))
        ][:2] or [title]

        steps = item.get("steps") if isinstance(item.get("steps"), list) else []
        steps = [
            normalize_scene_text(str(x), TEXT_LIMITS["step"], WORD_LIMITS["step"])
            for x in steps
            if str(x).strip()
            and "Уточнить" not in str(x)
            and "Объяснить" not in str(x)
            and not _is_generic_scene_text(str(x))
        ][:3]
        scene = {
            "start": round(start, 2),
            "end": round(end, 2),
            "blockName": str(item.get("blockName") or "АНАЛИЗ"),
            "mode": mode,
            "title": title,
            "subtitle": subtitle,
            "value": chart_value,
            "unit": unit,
            "facts": facts,
            "anchorWords": anchor_words,
            "sourceText": source_text,
            "referenceEssence": reference_essence,
            "hookText": hook_text,
            "hookPromise": hook_promise,
            "visualIdea": visual_idea,
            "visualType": visual_type,
            "visualElements": visual_elements,
            # Legacy fields
            "titleLines": title_lines,
            "steps": steps,
            "insight": insight,
            "cta": cta,
            "keyword": keyword,
            "opener": opener,
            "bars": _norm_bars(item.get("bars")),
            "_i": i,
        }
        norm.append(scene)

    norm.sort(key=lambda x: (x["start"], x["_i"]))
    if not norm:
        raise RuntimeError("LLM returned no valid scenes after normalization")

    fixed: list[dict[str, Any]] = []
    for scene in norm:
        start = max(0.0, scene["start"])
        end = max(start + 1.2, scene["end"])
        end = min(duration, end)
        if end - start < 1.2:
            continue
        clean = dict(scene)
        clean["start"] = round(start, 2)
        clean["end"] = round(end, 2)
        clean.pop("_i", None)
        fixed.append(clean)

    if not fixed:
        raise RuntimeError("LLM returned scenes, but none survived timing normalization")

    _ensure_min_scene_count(fixed, utterances_for_norm, duration, target_scene_count)
    _repair_scene_plan_metadata(fixed, utterances_for_norm)
    _repair_scene_plan_titles(fixed, utterances_for_norm)
    _repair_scene_plan_editorial_copy(fixed, utterances_for_norm)
    validate_scene_plan_quality(fixed, duration, require_visuals=require_visuals)

    # Build chapter metadata so viewer always sees topic context.
    chapter_idx = 0
    active_block = ""
    active_title = ""
    active_subtitle = ""
    active_opener = ""
    for i, scene in enumerate(fixed):
        block = normalize_plain_text(str(scene.get("blockName") or "")).upper()
        mode = normalize_plain_text(str(scene.get("mode") or "")).lower()
        prev_start = float(fixed[i - 1].get("start", 0.0)) if i > 0 else 0.0
        cur_start = float(scene.get("start", 0.0))
        is_new_chapter = (
            i == 0
            or (block and block != active_block)
            or (mode == "full" and (cur_start - prev_start) >= 20.0)
        )
        if is_new_chapter:
            chapter_idx += 1
            active_block = block
            active_title, active_subtitle = _build_chapter_meta(scene)
            active_opener = _normalize_opener_text(str(scene.get("opener") or active_title))
            if not active_opener:
                active_opener = _normalize_opener_text(active_title) or "Ключевая мысль"
        scene["chapterIndex"] = chapter_idx
        scene["chapterTitle"] = active_title
        scene["chapterSubtitle"] = active_subtitle
        scene["opener"] = _normalize_opener_text(str(scene.get("opener") or "")) or active_opener
        scene["chapterOpener"] = active_opener

    return fixed


def scene_plan_uses_fallback_copy(scenes: list[dict[str, Any]]) -> bool:
    if not scenes:
        return True
    weak = 0
    for scene in scenes:
        title = str(scene.get("title") or "")
        insight = str(scene.get("insight") or "")
        facts = scene.get("facts") if isinstance(scene.get("facts"), list) else []
        steps = scene.get("steps") if isinstance(scene.get("steps"), list) else []
        bars = scene.get("bars") if isinstance(scene.get("bars"), list) else []
        generic_facts = not facts or all(_is_generic_scene_text(str(f)) for f in facts)
        generic_steps = not steps or all(_is_generic_scene_text(str(s)) for s in steps)
        generic_bars = not bars or all(_is_generic_scene_text(str((b or {}).get("label") if isinstance(b, dict) else b)) for b in bars)
        if _is_generic_scene_text(title) and (_is_generic_scene_text(insight) or generic_facts) and (generic_steps or generic_bars):
            weak += 1
    return weak >= max(1, math.ceil(len(scenes) * 0.5))


def inject_scene_plan_into_index(index_path: Path, scenes: list[dict[str, Any]]) -> None:
    html = index_path.read_text(encoding="utf-8")
    plan_json = json.dumps(scenes, ensure_ascii=False, indent=2)
    indented = "\n".join(f"      {line}" for line in plan_json.splitlines())
    repl = f'<script id="scene-plan" type="application/json">\n{indented}\n    </script>'
    pattern = r'<script id="scene-plan" type="application/json">[\s\S]*?</script>'
    updated, count = re.subn(pattern, repl, html, count=1)
    if count != 1:
        raise RuntimeError("Cannot find <script id=\"scene-plan\" type=\"application/json\"> in index.html")
    index_path.write_text(updated, encoding="utf-8")


def extract_word_cues(transcript_payload: dict[str, Any], scenes: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    channels = (transcript_payload.get("results") or {}).get("channels") or []
    alternatives = channels[0].get("alternatives") if channels else []
    words = alternatives[0].get("words") if alternatives else []
    if not isinstance(words, list):
        words = []

    cues_by_scene: list[list[dict[str, Any]]] = []
    for scene in scenes:
        start = float(scene.get("start", 0.0))
        end = float(scene.get("end", 0.0))
        scene_cues: list[dict[str, Any]] = []
        for word in words:
            word_start = word.get("start")
            if word_start is None:
                continue
            try:
                word_start_f = float(word_start)
            except (TypeError, ValueError):
                continue
            if word_start_f < start or word_start_f >= end:
                continue

            text = (word.get("punctuated_word") or word.get("word") or "").strip()
            if not text:
                continue
            scene_cues.append({"time": round(word_start_f, 3), "text": text})
        cues_by_scene.append(scene_cues)
    return cues_by_scene


def inject_scene_word_cues_into_index(index_path: Path, scene_word_cues: list[list[dict[str, Any]]]) -> None:
    html = index_path.read_text(encoding="utf-8")
    cues_json = json.dumps(scene_word_cues, ensure_ascii=False, indent=2)
    indented = "\n".join(f"      {line}" for line in cues_json.splitlines())
    repl = f'<script id="scene-word-cues" type="application/json">\n{indented}\n    </script>'
    pattern = r'<script id="scene-word-cues" type="application/json">[\s\S]*?</script>'
    updated, count = re.subn(pattern, repl, html, count=1)
    if count != 1:
        raise RuntimeError("Cannot find <script id=\"scene-word-cues\" type=\"application/json\"> in index.html")
    index_path.write_text(updated, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate semantic scene-plan from Deepgram transcript and inject to HyperFrames HTML")
    parser.add_argument("--video", required=True, help="Path to local source video/audio")
    parser.add_argument("--index", default="index.html", help="Path to HyperFrames composition html")
    parser.add_argument("--language", default="ru", help="BCP-47 language (default: ru)")
    parser.add_argument("--deepgram-model", default="nova-3", help="Deepgram model (default: nova-3)")
    parser.add_argument("--llm-model", default=os.environ.get("LLM_MODEL", "gpt-4o-mini"), help="LLM model")
    parser.add_argument(
        "--llm-plan-attempts",
        type=int,
        default=int(os.environ.get("HYPERFRAMES_SCENE_PLAN_MAX_ATTEMPTS", "4") or 4),
        help="Maximum LLM scene-plan attempts after quality-gate failures (default: 4)",
    )
    parser.add_argument("--max-scenes", type=int, default=8, help="Upper bound on scenes count")
    parser.add_argument(
        "--overlay-coverage-percent",
        type=int,
        default=int(os.environ.get("HYPERFRAMES_OVERLAY_COVERAGE_PERCENT", "50") or 50),
        help="Target cutaway coverage percent used to choose scene count (default: 50)",
    )
    parser.add_argument("--duration", type=float, default=0.0, help="Force composition duration (seconds)")
    parser.add_argument("--timeout", type=int, default=1800, help="HTTP timeout in seconds")
    parser.add_argument("--utt-split", type=float, default=0.65, help="Deepgram utterance split in seconds")
    parser.add_argument(
        "--block-min-sentences",
        type=int,
        default=5,
        help="Minimum sentences per semantic block (default: 5)",
    )
    parser.add_argument(
        "--block-max-sentences",
        type=int,
        default=10,
        help="Maximum sentences per semantic block (default: 10)",
    )
    parser.add_argument(
        "--deepgram-intelligence",
        action="store_true",
        help="Enable Deepgram extras (topics/intents/sentiment/summarize). May fail for some languages/models.",
    )
    parser.add_argument("--skip-llm", action="store_true", help="Use deterministic fallback planner, no LLM call")
    parser.add_argument("--strict-llm", action="store_true", help="Fail if LLM generation fails")
    parser.add_argument("--reuse-transcript", default="", help="Path to existing Deepgram JSON, skip new transcription")
    parser.add_argument(
        "--script-text-file",
        default="",
        help="Path to scenario/script text used as semantic context and transcript fallback",
    )
    parser.add_argument("--out-transcript", default="data/deepgram_transcript.json", help="Output Deepgram JSON path")
    parser.add_argument(
        "--out-semantic-blocks",
        default="data/semantic-blocks.generated.json",
        help="Output semantic blocks JSON path",
    )
    parser.add_argument("--out-plan", default="data/scene-plan.generated.json", help="Output scene plan JSON path")
    parser.add_argument(
        "--out-word-cues",
        default="",
        help="Output scene word cues JSON path (default: derive from --out-plan)",
    )
    parser.add_argument(
        "--plan-target",
        choices=["hyperframes", "remotion"],
        default="hyperframes",
        help="Renderer target. Remotion horizontal uses text-only opener cards and does not require image visuals.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path.cwd()
    dotenv = find_dotenv(root)
    if dotenv:
        load_dotenv(dotenv)

    video_path = Path(args.video)
    index_path = Path(args.index)
    out_transcript = Path(args.out_transcript)
    out_semantic_blocks = Path(args.out_semantic_blocks)
    out_plan = Path(args.out_plan)
    if args.out_word_cues:
        out_word_cues = Path(args.out_word_cues)
    else:
        out_word_cues_name = out_plan.name.replace("scene-plan", "scene-word-cues")
        out_word_cues = out_plan.with_name(out_word_cues_name)
    script_context = ""
    if args.script_text_file:
        script_path = Path(args.script_text_file)
        if script_path.exists():
            script_context = normalize_plain_text(script_path.read_text(encoding="utf-8"))
        else:
            eprint(f"Warning: script text file not found: {script_path}")
    out_transcript.parent.mkdir(parents=True, exist_ok=True)
    out_semantic_blocks.parent.mkdir(parents=True, exist_ok=True)
    out_plan.parent.mkdir(parents=True, exist_ok=True)
    out_word_cues.parent.mkdir(parents=True, exist_ok=True)

    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")
    if not index_path.exists():
        raise FileNotFoundError(f"Index file not found: {index_path}")

    if args.reuse_transcript:
        transcript_payload = json.loads(Path(args.reuse_transcript).read_text(encoding="utf-8"))
        eprint(f"Loaded existing transcript: {args.reuse_transcript}")
    else:
        deepgram_key = os.environ.get("DEEPGRAM_API_KEY")
        if not deepgram_key:
            raise RuntimeError("DEEPGRAM_API_KEY is missing. Put it in environment or .env")
        eprint(f"Transcribing with Deepgram model={args.deepgram_model}, language={args.language} ...")
        transcript_payload = deepgram_transcribe(
            video_path=video_path,
            api_key=deepgram_key,
            language=args.language,
            model=args.deepgram_model,
            timeout_sec=args.timeout,
            include_intelligence=args.deepgram_intelligence,
            utt_split=args.utt_split,
        )
        out_transcript.write_text(json.dumps(transcript_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        eprint(f"Saved transcript JSON: {out_transcript}")

    utterances = extract_utterances(transcript_payload)
    transcript_words = extract_transcript_words(transcript_payload)
    if len(utterances) <= 1:
        synthesized = synthesize_utterances_from_words(transcript_payload, split_sec=args.utt_split)
        if len(synthesized) > len(utterances):
            utterances = synthesized
            eprint(f"Utterances were sparse; synthesized {len(utterances)} segments from words.")
    dg_duration = float((transcript_payload.get("metadata") or {}).get("duration") or 0.0)
    duration = args.duration if args.duration > 0 else dg_duration
    if duration <= 0:
        duration = max((float(u["end"]) for u in utterances), default=45.0)
    duration = round(duration, 2)
    if not utterances and script_context:
        utterances = synthesize_utterances_from_script_text(script_context, duration, max_segments=args.max_scenes * 4)
        if utterances:
            eprint(f"Deepgram returned no utterances; synthesized {len(utterances)} segments from scenario script.")
    if not utterances:
        eprint("Warning: no utterances found in transcript response.")
    eprint(f"Duration used for scene plan: {duration}s")

    sentences = extract_sentences(transcript_payload, utterances)
    overlay_coverage_percent = max(0, min(100, int(args.overlay_coverage_percent or 0)))
    target_scene_count = _target_scene_count_from_coverage(
        duration=duration,
        overlay_coverage_percent=overlay_coverage_percent,
        max_scenes=args.max_scenes,
    )
    eprint(
        f"Target scene count from coverage: {target_scene_count} "
        f"(coverage={overlay_coverage_percent}%, max={args.max_scenes})"
    )
    block_min_sentences = args.block_min_sentences
    block_max_sentences = args.block_max_sentences
    if duration <= 35 and len(sentences) >= 4 and args.block_min_sentences == 5 and args.block_max_sentences == 10:
        block_min_sentences = 1
        block_max_sentences = 2
    elif (
        target_scene_count > 0
        and len(sentences) >= target_scene_count
        and args.block_min_sentences == 5
        and args.block_max_sentences == 10
    ):
        block_min_sentences = 1
        block_max_sentences = max(2, math.ceil(len(sentences) / target_scene_count))

    semantic_blocks = build_semantic_blocks(
        sentences=sentences,
        min_sentences=block_min_sentences,
        max_sentences=block_max_sentences,
        max_blocks=args.max_scenes,
    )
    out_semantic_blocks.write_text(json.dumps(semantic_blocks, ensure_ascii=False, indent=2), encoding="utf-8")
    eprint(
        f"Built semantic blocks: {len(semantic_blocks)} "
        f"(sentences={len(sentences)}, size={block_min_sentences}-{block_max_sentences})"
    )
    eprint(f"Saved semantic blocks: {out_semantic_blocks}")

    if args.skip_llm:
        eprint("Generating deterministic scene-plan because --skip-llm was explicitly requested ...")
        scenes = build_fallback_scene_plan(utterances, semantic_blocks, duration, args.max_scenes)
    else:
        plan_attempts = max(1, int(args.llm_plan_attempts or 1))
        last_error = ""
        scenes = []
        for attempt in range(1, plan_attempts + 1):
            eprint(f"Generating strict LLM scene-plan with model={args.llm_model} (attempt {attempt}/{plan_attempts}) ...")
            try:
                raw_plan = generate_scene_plan_llm(
                    utterances=utterances,
                    semantic_blocks=semantic_blocks,
                    deepgram_payload=transcript_payload,
                    duration=duration,
                    max_scenes=args.max_scenes,
                    target_scene_count=target_scene_count,
                    overlay_coverage_percent=overlay_coverage_percent,
                    llm_model=args.llm_model,
                    timeout_sec=args.timeout,
                    script_context=script_context,
                    repair_feedback=last_error,
                    attempt=attempt,
                )
                if isinstance(raw_plan, dict):
                    raw_plan["_utterances"] = utterances
                    raw_plan["_transcript_words"] = transcript_words
                    raw_plan["_semantic_blocks"] = semantic_blocks
                    raw_plan["_target_scene_count"] = target_scene_count
                scenes = normalize_scene_plan(
                    raw_plan,
                    duration,
                    require_visuals=args.plan_target != "remotion",
                )
                if scene_plan_uses_fallback_copy(scenes):
                    raise RuntimeError("LLM scene-plan used generic copy; refusing to render fallback cards")
                break
            except Exception as err:
                last_error = str(err)
                if attempt >= plan_attempts:
                    raise
                eprint(
                    "Scene-plan quality gate failed; retrying LLM with feedback: "
                    + normalize_scene_text(last_error, 1200, 180)
                )

    out_plan.write_text(json.dumps(scenes, ensure_ascii=False, indent=2), encoding="utf-8")
    scene_word_cues = extract_word_cues(transcript_payload, scenes)
    out_word_cues.write_text(json.dumps(scene_word_cues, ensure_ascii=False, indent=2), encoding="utf-8")
    inject_scene_plan_into_index(index_path, scenes)
    inject_scene_word_cues_into_index(index_path, scene_word_cues)
    eprint(f"Saved scene plan: {out_plan}")
    eprint(f"Saved scene word cues: {out_word_cues}")
    eprint(f"Injected scene-plan into: {index_path}")
    eprint(f"Injected scene-word-cues into: {index_path}")

    # Auto-sync to hyperframes-auto/assets/input/ so Hyperframes preview picks it up immediately.
    hyperframes_public = Path(__file__).parent.parent.parent / "hyperframes-auto" / "assets" / "input"
    if hyperframes_public.exists():
        import shutil
        dest_plan = hyperframes_public / "scene-plan.generated.json"
        dest_word_cues = hyperframes_public / "scene-word-cues.generated.json"
        shutil.copy2(out_plan, dest_plan)
        shutil.copy2(out_word_cues, dest_word_cues)
        eprint(f"Synced to Hyperframes: {dest_plan}")
        eprint(f"Synced word cues to Hyperframes: {dest_word_cues}")
    else:
        eprint(f"Note: hyperframes-auto/assets/input not found at {hyperframes_public}, skipping sync.")

    print(
        json.dumps(
            {
                "ok": True,
                "scenes": len(scenes),
                "duration": duration,
                "transcript_path": str(out_transcript),
                "semantic_blocks_path": str(out_semantic_blocks),
                "semantic_blocks": len(semantic_blocks),
                "plan_path": str(out_plan),
                "index_path": str(index_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
