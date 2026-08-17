import datetime

import httpx

from . import models
from .integrations.postmypost_errors import PostMyPostApiError
from .publication_guard import PublicationVerificationError
from .publish_planner import get_min_publish_lead_delta, plan_next_publish_times_for_account_outputs


def is_missing_publication_status_error(exc: Exception) -> bool:
    if isinstance(exc, PostMyPostApiError):
        if exc.status_code != 422:
            return False
        response_text = exc.response_text or ""
    elif isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        if response is None or response.status_code != 422:
            return False
        try:
            response_text = response.text or ""
        except Exception:
            response_text = ""
    else:
        return False

    normalized = response_text.lower()
    return "required property" in normalized or "response validation error" in normalized


def is_repairable_publication_error(exc: Exception) -> bool:
    return isinstance(exc, PublicationVerificationError) or is_missing_publication_status_error(exc)


def replan_after_invalid_publication(
    db,
    user: models.User,
    task: models.VideoTask,
    post_at: datetime.datetime,
) -> datetime.datetime:
    utc = datetime.timezone.utc
    now_utc = datetime.datetime.now(utc).replace(microsecond=0)
    current_post_at = post_at if post_at.tzinfo else post_at.replace(tzinfo=utc)
    minimum_utc = max(
        current_post_at.astimezone(utc) + datetime.timedelta(minutes=1),
        now_utc + get_min_publish_lead_delta(),
    )
    if task.target_account_id is None:
        return minimum_utc

    lane = "vizard" if getattr(task, "vizard_project_id", None) else "instant"
    planned = plan_next_publish_times_for_account_outputs(
        db,
        user,
        [int(task.target_account_id)],
        lane=lane,
        project_id=getattr(task, "postmypost_project_id", None),
        exclude_task_ids={task.id},
        minimum_utc=minimum_utc,
    )
    candidate = planned[0] if planned else None
    return candidate.replace(tzinfo=utc) if candidate else minimum_utc
