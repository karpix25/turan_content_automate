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
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as err:
        eprint(f"urllib failed for {url}: {err}. Falling back to curl ...")
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
            raise RuntimeError(f"curl failed ({run.returncode}): {run.stderr.strip()}") from err
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
    cleaned = strip_filler_phrases(text)
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
        "goal": "Действуй как профессиональный режиссер монтажа. Твоя задача — составить 'Edit Plan' (монтажный план) для бизнес-видео. Ты должен определить, где контент заслуживает полноэкранного визуала (KEEP + Full), где достаточно боковой панели (KEEP + Side), а где графика будет мешать (например, на фальстартах или запинках).",
        "philosophy": {
            "KEEP_SIDE": "Используй для блоков ХУК и КОНТЕКСТ. Лицо диктора должно быть открыто. Это моменты установления контакта.",
            "KEEP_FULL": "Используй для блоков АНАЛИЗ, РИСКИ, РЕШЕНИЕ. Это 'мясо' ролика. Перекрывай диктора полностью, чтобы зритель впился глазами в цифры и инфографику.",
            "CUT_VISUAL": "Если в тексте видишь повторы, запинки или слова-паразиты — не ставь туда сцену. Оставляй чистое видео диктора.",
            "TRANSITION": "Сцены должны начинаться на начале сильной фразы и заканчиваться ровно на финальной точке мысли."
        },
        "constraints": {
            "duration_seconds": duration,
            "max_scenes": max_scenes,
            "scene_min_seconds": 6.5,
            "scene_max_seconds": 25.0,
            "visual_density": "60-70%",
            "block_names": ["ХУК", "КОНТЕКСТ", "АНАЛИЗ", "РИСКИ", "РЕШЕНИЕ", "ИТОГ"],
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
                "expert_tone": "Используй терминологию тендеров и бизнеса (ФЗ-44/223, маржинальность, дебиторка, тендерная документация).",
                "no_verbatim_transcript": True,
                "focus_on_essence": True,
            },
        },
        "required_output_json_shape": {
            "scenes": [
                {
                    "start": 0.0,
                    "end": 8.5,
                    "blockName": "ХУК",
                    "reason": "Вводная часть, устанавливаем контакт (Layout: Side)",
                    "mode": "mini",
                    "opener": "Тезис блока в 3-6 слов",
                    "titleLines": ["Заголовок 1", "Заголовок 2", "Заголовок 3", "Заголовок 4"],
                    "steps": ["Шаг 1", "Шаг 2", "Шаг 3"],
                    "insight": "Глубокая аналитическая мысль"
                }
            ]
        },
        "transcript_summary": summary,
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
    llm_model: str,
    timeout_sec: int,
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
    )

    system_prompt = """
Ты — элитный контент-мейкер и режиссер монтажа. Твоя задача — превратить разговорное видео в серию "ударных" текстовых графических сцен (слайдов и плашек). То время, где нет сцен, остается чистым видео со спикером.

ГЛАВНЫЕ ПРАВИЛА ТАЙМИНГА И РЕЖИМОВ (mode):
1. ЧИСТЫЙ ХУК: Строго запрещено ставить любые сцены в первые 10-15 секунд видео. Спикер должен смотреть в глаза зрителю и произнести хук без графики. Первая сцена может начаться только после 15 секунды.
2. Используй ТОЛЬКО два режима: "full" (крупная плашка) и "mini" (маленькая плашка).
3. СТАРТ БЛОКА = mode "full": новая тема/глава должна начинаться крупной плашкой на 2-4 секунды.
4. ЦИФРЫ И ФАКТЫ = mode "mini": важные цифры и факты внутри блока — маленькой плашкой, не перекрывая лицо.

ПРАВИЛА ТЕКСТА:
- ТЕКСТ (title): Строго 3-6 слов. Это заголовок, который можно прочитать за 2 секунды. "бьет в лоб".
- OPENER: Строго 3-6 слов. Это короткий триггер смыслового блока, переформулируй мысль, не копируй первое предложение дословно.
- subtitle НЕ использовать вообще.
- INSIGHT: Глубокая мысль или конкретная цифра для mini/full.

ОТБОР МОМЕНТОВ:
- Выбирай только самые эмоциональные или фактологические пики.
- Сцена должна длиться 3-6 секунд.
- Между сценами — МИНИМУМ 10-15 секунд чистого видео (без сцен), чтобы зритель отдыхал и смотрел на спикера.

ФОРМАТ ОТВЕТА — только валидный JSON:
{
  "scenes": [
    {
      "start": 15.0,
      "end": 19.0,
      "blockName": "КРИТИЧНО",
      "mode": "full",
      "title": "ФНС ЗАКРЫВАЕТ СХЕМЫ",
      "opener": "VPN БОЛЬШЕ НЕ СПАСАЕТ"
    },
    {
      "start": 35.0,
      "end": 40.0,
      "blockName": "ШТРАФЫ",
      "mode": "mini",
      "title": "ШТРАФ ДО 40%",
      "opener": "ШТРАФЫ УЖЕ ПРИЛЕТАЮТ",
      "insight": "Доказано в 90% судов"
    }
  ]
}
"""
    user_prompt = json.dumps(prompt_payload, ensure_ascii=False)

    req_payload: dict[str, Any] = {
        "model": llm_model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
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
    "тема",
    "хук",
    "контекст",
    "анализ",
    "итог",
    "фокус",
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
    return False


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


def normalize_scene_plan(raw: dict[str, Any], duration: float) -> list[dict[str, Any]]:
    raw_scenes = raw.get("scenes")
    if not isinstance(raw_scenes, list):
        raw_scenes = []

    utterances_for_norm = raw.get("_utterances")
    if not isinstance(utterances_for_norm, list):
        utterances_for_norm = []

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

        start = find_best_start(start, utterances_for_norm)
        window_text = _scene_window_text(utterances_for_norm, start, end)
        semantic_fallback = _build_semantic_fallback(window_text, block_name)
        
        # ГАРАНТИРОВАННЫЙ БУФЕР: Первый слайд не раньше 4-й секунды
        if not norm:
            if start < 4.0:
                start = 4.0
        else:
            prev_end = norm[-1]["end"]
            if start < prev_end + 8.0:
                start = prev_end + 8.0

        # FALLBACK ДАННЫХ: если LLM вернула шаблон, берём осмысленный текст из окна utterances.
        title_from_raw = str(item.get("title") or "").strip()
        title = title_from_raw
        if _is_generic_scene_text(title):
            t_lines = item.get("titleLines") or []
            if t_lines and isinstance(t_lines, list):
                title = " ".join([str(x) for x in t_lines if str(x) != "Смысловой блок"]).strip()
        if _is_generic_scene_text(title):
            title = str(item.get("keyword") or "").strip()
        if _is_generic_scene_text(title):
            title = semantic_fallback["title"]

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
        if not facts:
            facts = semantic_fallback["facts"][:2]

        insight = normalize_scene_text(
            str(item.get("insight") or ""), TEXT_LIMITS["insight"], WORD_LIMITS["insight"]
        )
        if _is_generic_scene_text(insight):
            insight = semantic_fallback["insight"]
        cta = normalize_scene_text(
            str(item.get("cta") or ""), TEXT_LIMITS["cta"], WORD_LIMITS["cta"]
        )
        if _is_generic_scene_text(cta):
            cta = semantic_fallback["cta"]
        keyword = normalize_scene_text(
            str(item.get("keyword") or title or ""), TEXT_LIMITS["keyword"], WORD_LIMITS["keyword"]
        )
        if _is_generic_scene_text(keyword):
            keyword = semantic_fallback["keyword"]
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
        # Supplement steps from facts if empty
        if not steps and facts:
            steps = facts[:2]
        if not steps:
            steps = semantic_fallback["steps"][:2]

        scene = {
            "start": round(start, 2),
            "end": round(end, 2),
            "blockName": str(item.get("blockName") or "АНАЛИЗ"),
            "mode": mode,
            "title": title,
            "value": chart_value,
            "unit": unit,
            "facts": facts,
            # Legacy fields
            "titleLines": title_lines,
            "steps": steps,
            "insight": insight,
            "cta": cta or semantic_fallback["cta"],
            "keyword": keyword or semantic_fallback["keyword"],
            "opener": opener,
            "bars": _norm_bars(item.get("bars")),
            "_i": i,
        }
        norm.append(scene)

    norm.sort(key=lambda x: (x["start"], x["_i"]))
    if not norm:
        return [
            {
                "start": 0.0,
                "end": round(duration, 2),
                "mode": "full",
                "opener": "Проверка сценария",
                "titleLines": ["Сцена пустая", "Проверьте LLM", "Проверьте модель", "Повторите запуск"],
                "steps": ["1. Проверить ключ", "2. Проверить модель", "3. Повторить запуск"],
                "insight": "LLM вернул пустой scene-plan.",
                "cta": "Проверьте конфиг и перезапустите",
                "keyword": "диагностика",
                "bars": [
                    {"label": "Хук", "value": 0.4},
                    {"label": "Суть", "value": 0.5},
                    {"label": "Кейс", "value": 0.45},
                    {"label": "CTA", "value": 0.6},
                ],
            }
        ]

    fixed: list[dict[str, Any]] = []
    cursor = 0.0
    for scene in norm:
        start = max(cursor, scene["start"])
        end = max(start + 1.2, scene["end"])
        end = min(duration, end)
        if end - start < 1.2:
            continue
        clean = dict(scene)
        clean["start"] = round(start, 2)
        clean["end"] = round(end, 2)
        clean.pop("_i", None)
        fixed.append(clean)
        cursor = end
        if cursor >= duration - 0.01:
            break

    if not fixed:
        fixed = [
            {
                "start": 0.0,
                "end": round(duration, 2),
                "mode": "full",
                "opener": "Проверка таймингов",
                "titleLines": ["Сцена пустая", "Проверьте JSON", "Проверьте тайминг", "Повторите запуск"],
                "steps": ["1. Проверить JSON", "2. Проверить тайминги", "3. Повторить запуск"],
                "insight": "После нормализации не осталось валидных сцен.",
                "cta": "Перезапустить pipeline",
                "keyword": "структура",
                "bars": [
                    {"label": "Хук", "value": 0.4},
                    {"label": "Суть", "value": 0.5},
                    {"label": "Кейс", "value": 0.45},
                    {"label": "CTA", "value": 0.6},
                ],
            }
        ]

    fixed[0]["start"] = 0.0
    fixed[-1]["end"] = round(duration, 2)

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
    parser.add_argument("--max-scenes", type=int, default=8, help="Upper bound on scenes count")
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
    if len(utterances) <= 1:
        synthesized = synthesize_utterances_from_words(transcript_payload, split_sec=args.utt_split)
        if len(synthesized) > len(utterances):
            utterances = synthesized
            eprint(f"Utterances were sparse; synthesized {len(utterances)} segments from words.")
    if not utterances:
        eprint("Warning: no utterances found in transcript response.")
    dg_duration = float((transcript_payload.get("metadata") or {}).get("duration") or 0.0)
    duration = args.duration if args.duration > 0 else dg_duration
    if duration <= 0:
        duration = max((float(u["end"]) for u in utterances), default=45.0)
    duration = round(duration, 2)
    eprint(f"Duration used for scene plan: {duration}s")

    sentences = extract_sentences(transcript_payload, utterances)
    semantic_blocks = build_semantic_blocks(
        sentences=sentences,
        min_sentences=args.block_min_sentences,
        max_sentences=args.block_max_sentences,
        max_blocks=args.max_scenes,
    )
    out_semantic_blocks.write_text(json.dumps(semantic_blocks, ensure_ascii=False, indent=2), encoding="utf-8")
    eprint(
        f"Built semantic blocks: {len(semantic_blocks)} "
        f"(sentences={len(sentences)}, size={args.block_min_sentences}-{args.block_max_sentences})"
    )
    eprint(f"Saved semantic blocks: {out_semantic_blocks}")

    if args.skip_llm:
        eprint("Generating fallback scene-plan (LLM skipped) ...")
        scenes = build_fallback_scene_plan(utterances, semantic_blocks, duration, args.max_scenes)
    else:
        try:
            eprint(f"Generating LLM scene-plan with model={args.llm_model} ...")
            raw_plan = generate_scene_plan_llm(
                utterances=utterances,
                semantic_blocks=semantic_blocks,
                deepgram_payload=transcript_payload,
                duration=duration,
                max_scenes=args.max_scenes,
                llm_model=args.llm_model,
                timeout_sec=args.timeout,
            )
            if isinstance(raw_plan, dict):
                raw_plan["_utterances"] = utterances
            scenes = normalize_scene_plan(raw_plan, duration)
        except Exception as err:
            if args.strict_llm:
                raise
            eprint(f"LLM generation failed ({err}). Falling back to deterministic planner ...")
            scenes = build_fallback_scene_plan(utterances, semantic_blocks, duration, args.max_scenes)

    out_plan.write_text(json.dumps(scenes, ensure_ascii=False, indent=2), encoding="utf-8")
    scene_word_cues = extract_word_cues(transcript_payload, scenes)
    out_word_cues.write_text(json.dumps(scene_word_cues, ensure_ascii=False, indent=2), encoding="utf-8")
    inject_scene_plan_into_index(index_path, scenes)
    inject_scene_word_cues_into_index(index_path, scene_word_cues)
    eprint(f"Saved scene plan: {out_plan}")
    eprint(f"Saved scene word cues: {out_word_cues}")
    eprint(f"Injected scene-plan into: {index_path}")
    eprint(f"Injected scene-word-cues into: {index_path}")

    # Auto-sync to remotion-auto/public/input/ so Remotion Studio picks it up immediately
    remotion_public = Path(__file__).parent.parent.parent / "remotion-auto" / "public" / "input"
    if remotion_public.exists():
        import shutil
        dest_plan = remotion_public / "scene-plan.generated.json"
        dest_word_cues = remotion_public / "scene-word-cues.generated.json"
        shutil.copy2(out_plan, dest_plan)
        shutil.copy2(out_word_cues, dest_word_cues)
        eprint(f"Synced to Remotion: {dest_plan}")
        eprint(f"Synced word cues to Remotion: {dest_word_cues}")
    else:
        eprint(f"Note: remotion-auto/public/input not found at {remotion_public}, skipping sync.")

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
