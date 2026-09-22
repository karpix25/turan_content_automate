"""End-to-end run of the block carousel engine with real services.

Mirrors the production generate_carousel_task path: CTA stripping -> Russian
check -> LLM deck per platform -> strict validation -> Chromium render of
carousel (1080x1350) and story (1080x1920) PNGs. Publishing to PostMyPost is
NOT part of this script: it only produces the media the publisher consumes.

Usage:
  OPENROUTER_API_KEY=sk-or-... python3 scripts/run_blocks_smoke.py
  python3 scripts/run_blocks_smoke.py --fallback          # deterministic deck, no LLM
  python3 scripts/run_blocks_smoke.py --text-file text.txt --out /tmp/run1
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.blocks_pipeline import generate_blocks_outputs  # noqa: E402
from app.integrations.llm import LLMClient  # noqa: E402
from app.services.carousel_blocks import build_fallback_deck  # noqa: E402
from app.services.carousel_copy import is_russian_text, strip_source_cta  # noqa: E402
from app.services.carousel_pipeline import suggest_slide_count  # noqa: E402

DEFAULT_TEXT = (
    "Тендерная практика меняется быстрее, чем успевают поставщики. Заказчики стали "
    "чаще отказывать на первом этапе, ещё до сравнения цен. Причина простая: описание "
    "объекта закупки читают буквально, и одна неточная фраза отправляет заявку в отказ. "
    "• Проверяйте наименование объекта закупки по техническому заданию заказчика "
    "• Сверяйте сроки поставки с графиком исполнения контракта "
    "• Готовьте обеспечение заявки заранее, а не в день дедлайна "
    "• Храните актуальные сертификаты под одну дату подачи "
    "По статистике закупок 72% отклонённых заявок спотыкаются именно на описании: "
    "поставщик копирует формулировку из прошлой закупки, а заказчик за это время сменил "
    "требования. Перед подачей откройте техзадание и сверьте первые две строки описания — "
    "именно там расхождение стоит дешевле всего исправить."
)

PLATFORMS = {"instagram": [1], "telegram": [7]}
HANDLES = {"instagram": {1: "@turan_pro"}, "telegram": {7: "@turan_pro"}}
CTAS = {"instagram": "Подпишись", "telegram": "Забирай чек-лист в профиле"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fallback", action="store_true", help="детерминированная дека без LLM")
    parser.add_argument("--text", help="мастер-текст напрямую")
    parser.add_argument("--text-file", help="файл с мастер-текстом")
    parser.add_argument("--out", default=str(Path(__file__).parent / "smoke_blocks_output"))
    args = parser.parse_args()

    master_text = args.text or (Path(args.text_file).read_text() if args.text_file else DEFAULT_TEXT)
    text = strip_source_cta(master_text)
    if not is_russian_text(text):
        print("FAIL: текст содержит латиницу — как и в проде, генерация остановлена")
        return 2
    slide_count = suggest_slide_count(text, "carousel")

    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if args.fallback:
        llm = None
        mode = "fallback (без LLM)"
    elif not api_key:
        print("FAIL: не задан OPENROUTER_API_KEY — реальный LLM-шаг невозможен.")
        print("Повтори с ключом: OPENROUTER_API_KEY=sk-or-... python3 scripts/run_blocks_smoke.py")
        print("Или запусти детерминированный режим: python3 scripts/run_blocks_smoke.py --fallback")
        return 2
    else:
        llm = LLMClient(api_key=api_key,
                        model_id=os.getenv("OPENROUTER_MODEL_ID", "google/gemini-2.5-pro-latest"))
        mode = f"real LLM ({llm.model_id})"

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    print(f"Режим: {mode}")
    print(f"Мастер-текст: {len(text.split())} слов -> целевых слайдов: {slide_count}")
    print(f"Платформы: {sorted(PLATFORMS)}; вывод: {out}")

    started = time.time()
    if llm is None:
        carousel, story, texts = _fallback_run(text, slide_count, out)
    else:
        carousel, story, texts = generate_blocks_outputs(
            llm, text, PLATFORMS, HANDLES, {}, CTAS, out,
        )
    elapsed = time.time() - started

    payload = texts["instagram"]["carousel"]
    deck = payload.get("slides", []) if isinstance(payload, dict) else payload
    (out / "editorial.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "deck.json").write_text(json.dumps(deck, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "mode": mode,
        "master_words": len(text.split()),
        "slide_count": slide_count,
        "deck_slides": [slide.get("type") for slide in deck],
        "elapsed_seconds": round(elapsed, 1),
        "carousel_png": {k: len(v) for k, v in carousel.items()},
        "story_png": {k: len(v) for k, v in story.items()},
    }
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Готово за {elapsed:.1f} c: {out}/deck.json, {out}/report.json, {len(list(out.glob('*.png')))} PNG")
    return 0


def _fallback_run(text: str, slide_count: int, out: Path):
    """Renders the deterministic deck through the same renderer as production."""
    from app.blocks_pipeline import OUTPUT_FORMATS
    from app.services.blocks_html import build_slide_html
    from app.integrations.html_slide_renderer import HtmlSlideRenderer

    carousel: dict[str, list[str]] = {}
    story: dict[str, list[str]] = {}
    texts: dict[str, dict] = {}
    with HtmlSlideRenderer() as renderer:
        for platform, accounts in PLATFORMS.items():
            cta = CTAS[platform]
            deck = build_fallback_deck(text, slide_count, cta)
            texts[platform] = {"carousel": list(deck), "story": list(deck)}
            for account_id in accounts:
                for design_format, target in (("carousel", carousel), ("story", story)):
                    width, height = OUTPUT_FORMATS[design_format]
                    paths = []
                    for index in range(len(deck)):
                        html = build_slide_html(deck, index, width=width, height=height,
                                                author=HANDLES[platform][account_id], cta=cta)
                        path = out / f"{design_format}-{platform}-{account_id}-{index + 1}.png"
                        renderer.render_html(html, str(path), width, height)
                        paths.append(str(path))
                    target[platform] = paths
    return carousel, story, texts


if __name__ == "__main__":
    raise SystemExit(main())
