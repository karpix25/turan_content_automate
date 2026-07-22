import datetime
import logging

from sqlalchemy.orm import Session

from .. import models
from ..api.utils import _extract_video_url_for_transcript, _get_channel_videos_list


def train_user_style(
    db: Session,
    user: models.User,
    *,
    channel_url: str,
    video_count: int,
    scraper,
    llm,
) -> str:
    logging.info("Training style from channel: %s (count: %s)", channel_url, video_count)
    channel_data = scraper.get_channel_videos(channel_url)
    videos = _get_channel_videos_list(channel_data or {})
    if not videos:
        raise RuntimeError(
            "Failed to fetch channel videos (use YouTube channel URL, @handle, channelId, or a public video URL)"
        )

    transcripts: list[str] = []
    for video in videos[:video_count]:
        video_url = _extract_video_url_for_transcript(video)
        if not video_url:
            continue
        transcript_data = scraper.get_youtube_transcript(video_url)
        transcript = (transcript_data or {}).get("transcript_only_text")
        if transcript:
            transcripts.append(transcript)

    if not transcripts:
        raise RuntimeError("No transcripts found for training")

    style_profile = llm.analyze_style(transcripts)
    if not style_profile:
        raise RuntimeError("Style analysis failed")

    user.author_style_profile = style_profile
    user.training_source = channel_url
    user.style_training_status = "completed"
    user.style_training_error = None
    user.style_training_updated_at = datetime.datetime.utcnow()
    db.commit()
    return style_profile
