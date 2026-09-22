"""Generation pipeline for block-based carousels and stories.

Builds one structured deck per platform, renders it into both aspect ratios
and returns the same shape the classic pipeline produces, so drafts,
publication scheduling and Telegram notifications stay unchanged.
"""

import logging
from pathlib import Path

from .integrations.html_slide_renderer import HtmlSlideRenderer, SlideLayoutError
from .services.blocks_html import build_slide_html
from .services.carousel_blocks import build_platform_deck, deck_to_text
from .services.carousel_editor import compose_reviewed_deck

logger = logging.getLogger(__name__)

OUTPUT_FORMATS = {"carousel": (1080, 1350), "story": (1080, 1920)}


def _variant_key(platform: str, account_ids: list[int]) -> str:
    return platform if len(account_ids) == 1 else f"{platform}:{account_ids[0]}"


def _deck_payload(deck: list[dict], frame: dict | None = None) -> dict:
    payload = {"slides": list(deck)}
    if frame:
        payload["frame"] = frame["id"]
        if frame.get("editorial_plan"):
            payload["editorial_plan"] = frame["editorial_plan"]
            payload["editorial_review"] = frame["editorial_review"]
    return payload


def _render_deck(renderer: HtmlSlideRenderer, deck: list[dict], design_format: str, platform: str,
                 account_id: int, author: str, avatar_url: str, cta: str, destination: Path) -> list[str]:
    width, height = OUTPUT_FORMATS[design_format]
    paths: list[str] = []
    for index in range(len(deck)):
        html = build_slide_html(
            deck, index, width=width, height=height,
            author=author, avatar_url=avatar_url, cta=cta,
        )
        path = destination / f"{design_format}-{platform}-{account_id}-{index + 1}.png"
        renderer.render_html(html, str(path), width, height)
        paths.append(str(path))
    return paths


def generate_blocks_outputs(
    llm_client,
    text: str,
    platform_accounts: dict,
    account_handles: dict,
    account_avatars: dict,
    ctas: dict,
    destination: Path,
    renderer_factory=HtmlSlideRenderer,
    story_ctas: dict | None = None,
) -> tuple[dict, dict, dict]:
    """Render decks for every platform/account.

    Returns (carousel_paths, story_paths, platform_texts) where platform_texts
    maps platform -> {"carousel": deck, "story": deck} for the caption builder.
    """
    carousel_paths: dict[str, list[str]] = {}
    story_paths: dict[str, list[str]] = {}
    platform_texts: dict[str, dict] = {}
    with renderer_factory() as renderer:
        for platform, account_ids_raw in (platform_accounts or {}).items():
            account_ids = [int(account_id) for account_id in account_ids_raw or []]
            if not account_ids:
                continue
            cta = str((ctas or {}).get(platform) or "")
            deck, frame = build_platform_deck(llm_client, text, platform, cta)
            if frame:
                logger.info("Copy frame for %s: %s", platform, frame["id"])
            # Retry the whole platform so all accounts, ratios and captions keep
            # the same deck even if overflow occurred on a later image.
            for attempt in range(2):
                rendered = {"carousel": {}, "story": {}}
                payloads = {}
                try:
                    for design_format in OUTPUT_FORMATS:
                        format_cta = (str(story_ctas.get(platform) or "")
                                      if design_format == "story" and story_ctas is not None else cta)
                        format_deck = [dict(slide) for slide in deck]
                        format_deck[-1]["cta"] = format_cta
                        payloads[design_format] = _deck_payload(format_deck, frame)
                        for account_id in account_ids:
                            author = account_handles.get(platform, {}).get(account_id, "")
                            avatar_url = account_avatars.get(account_id, "")
                            variant_key = platform if len(account_ids) == 1 else f"{platform}:{account_id}"
                            rendered[design_format][variant_key] = _render_deck(
                                renderer, format_deck, design_format, platform, account_id,
                                author, avatar_url, format_cta, destination,
                            )
                except SlideLayoutError as exc:
                    if attempt:
                        raise
                    logger.warning("Block rendering failed for %s (%s); rebuilding all variants", platform, exc)
                    deck, frame = compose_reviewed_deck(
                        llm_client, text, platform, cta, frame["editorial_plan"],
                        previous=deck, feedback=f"{design_format}, слайд с индексом от нуля: {exc}",
                    )
                    continue
                carousel_paths.update(rendered["carousel"])
                story_paths.update(rendered["story"])
                platform_texts[platform] = payloads
                break
    if not carousel_paths:
        raise RuntimeError("Нет поддерживаемых социальных сетей для карусели")
    return carousel_paths, story_paths, platform_texts


__all__ = ["generate_blocks_outputs", "deck_to_text"]
