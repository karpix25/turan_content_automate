def should_request_thumbnail_review(
    *,
    review_enabled: bool,
    auto_approve_enabled: bool,
    telegram_chat_id: str | None,
) -> bool:
    return (
        review_enabled
        and not auto_approve_enabled
        and bool((telegram_chat_id or "").strip())
    )
