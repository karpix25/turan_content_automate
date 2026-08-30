import datetime
from typing import Any


def post_recency(post: Any) -> tuple[datetime.datetime, int]:
    return (
        getattr(post, "published_at", None)
        or getattr(post, "created_at", None)
        or datetime.datetime.min,
        int(getattr(post, "id", 0) or 0),
    )


def pick_latest_unused_posts(
    posts: list[Any],
    used_post_ids: set[int],
    limit: int = 3,
) -> list[Any]:
    latest_by_channel: dict[int, Any] = {}
    for post in posts:
        post_id = int(getattr(post, "id", 0) or 0)
        channel_id = int(getattr(post, "channel_id", 0) or 0)
        if not post_id or post_id in used_post_ids:
            continue
        current = latest_by_channel.get(channel_id)
        if current is None or post_recency(post) > post_recency(current):
            latest_by_channel[channel_id] = post
    return sorted(latest_by_channel.values(), key=post_recency, reverse=True)[:limit]
