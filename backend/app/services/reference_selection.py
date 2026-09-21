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


def pick_top_viewed_posts(
    posts: list[Any],
    used_post_ids: set[int],
    per_channel: int = 3,
    limit: int = 3,
) -> list[Any]:
    """Latest `per_channel` posts of every channel, ranked by views.

    Already-used posts are excluded before the "latest" window, so a channel
    whose fresh reels are all spent does not block newer unused content from
    older positions. Final ranking is view count, recency as tiebreaker.
    """
    by_channel: dict[int, list[Any]] = {}
    for post in posts:
        post_id = int(getattr(post, "id", 0) or 0)
        if not post_id or post_id in used_post_ids:
            continue
        by_channel.setdefault(int(getattr(post, "channel_id", 0) or 0), []).append(post)
    pool: list[Any] = []
    for channel_posts in by_channel.values():
        pool.extend(sorted(channel_posts, key=post_recency, reverse=True)[:max(1, per_channel)])
    return sorted(
        pool,
        key=lambda post: (int(getattr(post, "view_count", 0) or 0), post_recency(post)),
        reverse=True,
    )[:max(1, limit)]
