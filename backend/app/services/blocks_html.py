"""HTML design system for block-based carousel slides.

One call builds one self-contained HTML document sized exactly to the output
canvas (carousel 1080x1350 or story 1080x1920). Every text field is escaped;
all type sizes are multiplied by a per-slide --fit factor that the embedded
script shrinks until the content fits, so words are never cut off.
"""

import base64
import html
from pathlib import Path
from typing import Any

TRANSPARENT_AVATAR = "data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs="

_LOGO_PATH = Path(__file__).resolve().parents[1] / "assets" / "logo.png"
_LOGO_CACHE: str | None = None


def logo_data_uri() -> str:
    """Brand logo (embedded, self-contained) used instead of account avatars."""
    global _LOGO_CACHE
    if _LOGO_CACHE is None:
        try:
            raw = base64.b64encode(_LOGO_PATH.read_bytes()).decode("ascii")
            _LOGO_CACHE = f"data:image/png;base64,{raw}"
        except OSError:
            _LOGO_CACHE = TRANSPARENT_AVATAR
    return _LOGO_CACHE

DEFAULT_THEME = {
    "bg": "#17110B",
    "surface": "#251C12",
    "ink": "#F4EBD9",
    "muted": "#B4A488",
    "accent": "#D8AF5F",
    "accent-ink": "#1B140A",
    "accent-grad": "linear-gradient(135deg, #F0D28A 0%, #C69A4B 100%)",
    "line": "#3D3326",
    "font": 'Inter, "Liberation Sans", "DejaVu Sans", -apple-system, "Segoe UI", Roboto, Arial, sans-serif',
}

_BASE_CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { width: WIDTHpx; height: HEIGHTpx; background: var(--bg); }
body { font-family: var(--font); color: var(--ink);
       -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility; }
.slide { position: relative; width: WIDTHpx; height: HEIGHTpx; padding: PADYpx 84px; --fit: 1; }
.inner { display: flex; flex-direction: column; height: 100%; }
.fit { flex: 1; display: flex; flex-direction: column; justify-content: center;
       gap: calc(30px * var(--fit)); }
.foot { margin-top: auto; padding-top: calc(28px * var(--fit));
        border-top: 1px solid var(--line);
        display: flex; align-items: center; justify-content: space-between; }
.author { display: flex; align-items: center; gap: 14px; min-width: 0; }
.author img { width: 48px; height: 48px; border-radius: 50%; object-fit: cover;
              border: 2px solid var(--line); flex: none; }
.author span { font-size: 22px; color: var(--muted); white-space: nowrap;
               overflow: hidden; text-overflow: ellipsis; }
.page { font-size: 22px; color: var(--muted); flex: none; margin-left: 20px; }

.kicker { align-self: flex-start; background: var(--accent-grad); color: var(--accent-ink);
          font-size: calc(21px * var(--fit)); font-weight: 800; letter-spacing: 0.14em;
          text-transform: uppercase; padding: 12px 24px; border-radius: 999px; }
.title { font-size: calc(44px * var(--fit)); line-height: 1.14; font-weight: 800;
         letter-spacing: -0.01em; text-wrap: balance; }
.body { font-size: calc(27px * var(--fit)); line-height: 1.55; color: var(--ink);
        text-wrap: pretty; }

.type-cover .fit { flex: 1; justify-content: center; gap: calc(34px * var(--fit)); }
.type-cover .title { font-size: calc(64px * var(--fit)); line-height: 1.08; }
.type-cover .subtitle { font-size: calc(29px * var(--fit)); line-height: 1.45; color: var(--muted); }

.type-cta .fit { flex: 1; justify-content: center; align-items: center; gap: calc(44px * var(--fit)); }
.type-cta .cta-chip { display: flex; flex-direction: column; align-items: center; gap: 34px; }
.type-cta .cta-logo { width: calc(170px * var(--fit)); height: calc(170px * var(--fit));
                      border-radius: 50%; object-fit: cover; }
.type-cta .cta-pill { background: var(--accent-grad); color: var(--accent-ink);
                      font-size: calc(50px * var(--fit)); font-weight: 800; line-height: 1.2;
                      padding: 32px 58px; border-radius: 999px; text-align: center;
                      max-width: 100%; text-wrap: balance;
                      box-shadow: 0 18px 60px rgba(216, 175, 95, 0.22); }
.type-cta .handle { display: flex; align-items: center; gap: 16px; color: var(--ink);
                    font-size: calc(27px * var(--fit)); font-weight: 600; }

.list { display: flex; flex-direction: column; gap: calc(18px * var(--fit)); }
.list .item { display: flex; align-items: flex-start; gap: 20px; }
.list .badge { flex: none; width: calc(42px * var(--fit)); height: calc(42px * var(--fit));
               border-radius: 50%; background: var(--accent-grad); color: var(--accent-ink);
               font-size: calc(24px * var(--fit)); font-weight: 800;
               display: flex; align-items: center; justify-content: center; }
.list .item p { font-size: calc(27px * var(--fit)); line-height: 1.4; padding-top: 6px; }

.type-steps .item .badge { border-radius: 50%; }
.type-steps .item { align-items: center; }

.table { width: 100%; border-collapse: collapse; }
.table th { background: var(--accent-grad); color: var(--accent-ink); text-align: left;
            font-size: calc(24px * var(--fit)); font-weight: 700;
            padding: calc(18px * var(--fit)) calc(22px * var(--fit)); }
.table th:first-child { border-radius: 18px 0 0 0; }
.table th:last-child { border-radius: 0 18px 0 0; }
.table td { font-size: calc(25px * var(--fit)); line-height: 1.35;
            padding: calc(18px * var(--fit)) calc(22px * var(--fit));
            border-bottom: 1px solid var(--line); vertical-align: top; }
.table tr:nth-child(even) td { background: var(--surface); }

.compare { display: grid; grid-template-columns: 1fr 1fr; gap: calc(22px * var(--fit)); }
.compare .card { background: var(--surface); border: 1px solid var(--line);
                 border-radius: 26px; padding: calc(26px * var(--fit)); }
.compare .card .side { font-size: calc(26px * var(--fit)); font-weight: 800; margin-bottom: calc(16px * var(--fit)); }
.compare .card.bad .side { color: var(--muted); }
.compare .card.good { border-top: 6px solid var(--accent); }
.compare .card.bad { border-top: 6px solid var(--line); }
.compare .card ul { list-style: none; display: flex; flex-direction: column;
                    gap: calc(14px * var(--fit)); }
.compare .card li { font-size: calc(24px * var(--fit)); line-height: 1.35;
                    display: flex; gap: 12px; }
.compare .card.good li::before { content: "✓"; color: var(--accent); font-weight: 800; flex: none; }
.compare .card.bad li::before { content: "—"; color: var(--muted); font-weight: 800; flex: none; }

.qa { display: flex; flex-direction: column; gap: calc(24px * var(--fit)); }
.qa .q { font-size: calc(27px * var(--fit)); line-height: 1.35; font-weight: 800; }
.qa .q::before { content: "? "; color: var(--accent); font-weight: 800; }
.qa .a { font-size: calc(25px * var(--fit)); line-height: 1.45; color: var(--muted); }

.type-text.variant-b .body { background: var(--surface); border-left: 6px solid var(--accent);
                             border-radius: 22px; padding: calc(26px * var(--fit)) calc(30px * var(--fit)); }
.type-checklist.variant-b .item { background: var(--surface); border: 1px solid var(--line);
                                  border-radius: 20px; padding: calc(16px * var(--fit)) calc(20px * var(--fit)); }

.type-stat .value { font-size: calc(140px * var(--fit)); line-height: 1.05; font-weight: 800;
                    color: var(--accent); letter-spacing: -0.02em; text-wrap: balance;
                    text-shadow: 0 12px 48px rgba(216, 175, 95, 0.25); }
.type-stat .caption { font-size: calc(28px * var(--fit)); line-height: 1.45; color: var(--muted); }

.type-quote .mark { font-size: calc(120px * var(--fit)); line-height: 0.6; font-weight: 800;
                    color: var(--accent); }
.type-quote .qtext { font-size: calc(36px * var(--fit)); line-height: 1.4; font-weight: 600;
                     text-wrap: pretty; }
.type-quote .qauthor { font-size: calc(24px * var(--fit)); color: var(--muted); }
"""

_FIT_SCRIPT = """
(function () {
  var overflow = false;
  document.querySelectorAll('.slide').forEach(function (slide) {
    var inner = slide.querySelector('.inner');
    var fit = 1.0;
    while (inner.scrollHeight > inner.clientHeight + 1 && fit > 0.58) {
      fit = Math.round((fit - 0.06) * 100) / 100;
      slide.style.setProperty('--fit', fit);
    }
    var ok = inner.scrollHeight <= inner.clientHeight + 1;
    slide.dataset.fit = ok ? 'ok' : 'overflow';
    if (!ok) { overflow = true; }
  });
  document.documentElement.dataset.fitStatus = overflow ? 'overflow' : 'ok';
})();
"""


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _title_block(slide: dict, class_name: str = "title") -> str:
    title = slide.get("title")
    return f'<h2 class="{class_name}">{_esc(title)}</h2>' if title else ""


def _slide_body(slide: dict) -> str:
    slide_type = slide["type"]
    if slide_type == "cover":
        parts = []
        if slide.get("kicker"):
            parts.append(f'<div class="kicker">{_esc(slide["kicker"])}</div>')
        parts.append(f'<h1 class="title">{_esc(slide["title"])}</h1>')
        if slide.get("subtitle"):
            parts.append(f'<p class="subtitle">{_esc(slide["subtitle"])}</p>')
        return "".join(parts)
    if slide_type == "text":
        return _title_block(slide) + f'<p class="body">{_esc(slide["body"])}</p>'
    if slide_type in ("checklist", "steps"):
        marker = "✓" if slide_type == "checklist" else ""
        items = "".join(
            f'<div class="item"><span class="badge">{marker}{index + 1 if slide_type == "steps" else ""}</span>'
            f"<p>{_esc(item)}</p></div>"
            for index, item in enumerate(slide["items"])
        )
        return _title_block(slide) + f'<div class="list">{items}</div>'
    if slide_type == "table":
        head = "".join(f"<th>{_esc(column)}</th>" for column in slide["columns"])
        rows = "".join(
            "<tr>" + "".join(f"<td>{_esc(cell)}</td>" for cell in row) + "</tr>"
            for row in slide["rows"]
        )
        return _title_block(slide) + f'<table class="table"><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>'
    if slide_type == "comparison":
        def card(kind: str, title: str, items: list) -> str:
            lis = "".join(f"<li>{_esc(item)}</li>" for item in items)
            return (f'<div class="card {kind}"><div class="side">{_esc(title)}</div>'
                    f"<ul>{lis}</ul></div>")
        compare = (card("good", slide["left_title"], slide["left_items"])
                   + card("bad", slide["right_title"], slide["right_items"]))
        return _title_block(slide) + f'<div class="compare">{compare}</div>'
    if slide_type == "stat":
        parts = [_title_block(slide),
                 f'<div class="value">{_esc(slide["value"])}</div>',
                 f'<p class="caption">{_esc(slide["caption"])}</p>']
        if slide.get("body"):
            parts.append(f'<p class="body">{_esc(slide["body"])}</p>')
        return "".join(parts)
    if slide_type == "qa":
        pairs = "".join(
            f'<div class="pair"><p class="q">{_esc(pair["q"])}</p><p class="a">{_esc(pair["a"])}</p></div>'
            for pair in slide["pairs"]
        )
        return _title_block(slide) + f'<div class="qa">{pairs}</div>'
    if slide_type == "quote":
        author = f'<div class="qauthor">— {_esc(slide["author"])}</div>' if slide.get("author") else ""
        return (f'<div class="mark">«</div>'
                + f'<p class="qtext">{_esc(slide["text"])}</p>' + author)
    if slide_type == "cta":
        handle = f'<div class="handle"><span>{_esc(slide.get("author") or "")}</span></div>' if slide.get("author") else ""
        return (f'<div class="cta-chip">'
                f'<img class="cta-logo" src="{logo_data_uri()}" alt="">'
                + handle +
                f'<div class="cta-pill">{_esc(slide["cta"])}</div></div>')
    raise ValueError(f"Неизвестный тип слайда: {slide_type}")


def build_slide_html(
    deck: list[dict],
    index: int,
    *,
    width: int,
    height: int,
    author: str = "",
    avatar_url: str = "",
    cta: str = "",
    theme: dict | None = None,
) -> str:
    slides = list(deck or [])
    if not slides or not (0 <= index < len(slides)):
        raise ValueError("Индекс слайда вне деки")
    slide = dict(slides[index])
    if slide.get("type") == "cta":
        slide["cta"] = str(slide.get("cta") or cta or "").strip()
        slide["author"] = author
        slide["avatar_url"] = avatar_url
    merged = dict(DEFAULT_THEME)
    merged.update(theme or {})
    css_vars = "; ".join(f"--{name}: {value}" for name, value in merged.items())
    css = (_BASE_CSS
           .replace("WIDTH", str(int(width)))
           .replace("HEIGHT", str(int(height)))
           .replace("PADY", "96" if height > width else "72"))
    avatar = logo_data_uri()
    author_html = ""
    if author:
        author_html = f'<div class="author"><img src="{avatar}" alt=""><span>{_esc(author)}</span></div>'
    page = f'<div class="page">{index + 1} / {len(slides)}</div>'
    return (
        "<!DOCTYPE html><html lang=\"ru\"><head><meta charset=\"utf-8\">"
        f"<style>:root {{{css_vars}}}{css}</style></head><body>"
        f"<section class=\"slide type-{_esc(slide['type'])} variant-{'b' if index % 2 else 'a'}\" data-index=\"{index}\">"
        f'<div class="inner"><div class="fit">{_slide_body(slide)}</div>'
        f"<footer class=\"foot\">{author_html}{page}</footer></div></section>"
        f"<script>{_FIT_SCRIPT}</script></body></html>"
    )
