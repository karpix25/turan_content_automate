import datetime
import logging

import httpx

from . import models
from .integrations.postmypost_errors import PostMyPostApiError
from .publication_guard import PublicationVerificationError, verify_publication_payload
from .publish_planner import get_min_publish_lead_delta


logger = logging.getLogger(__name__)
UTC = datetime.timezone.utc


def _is_missing_provider_publication(error: Exception) -> bool:
    if isinstance(error, PostMyPostApiError):
        status_code = error.status_code
        response_text = error.response_text or ""
    elif isinstance(error, httpx.HTTPStatusError):
        response = error.response
        status_code = response.status_code if response is not None else None
        try:
            response_text = response.text if response is not None else ""
        except Exception:
            response_text = ""
    else:
        return False

    if status_code == 404:
        return True
    return status_code == 422 and "publication_status" in response_text.lower()


def _lane(task: models.VideoTask) -> str:
    return "vizard" if getattr(task, "vizard_project_id", None) else "instant"


def _release_local_reservation(task: models.VideoTask, reason: str) -> None:
    task.postmypost_id = None
    task.publish_at = None
    task.preview_url = None
    task.publishing_status = "not_published"
    meta = dict(task.script_meta or {})
    meta["publication_reconciliation"] = {
        "status": "released",
        "reason": reason,
        "at": datetime.datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
    task.script_meta = meta


def reconcile_scheduled_publications(
    db,
    user: models.User,
    account_ids: list[int | None],
    *,
    lane: str,
    client,
) -> dict[str, int]:
    """Release local slots that are not backed by a valid PostMyPost record."""
    normalized_accounts = {int(account_id) for account_id in account_ids if account_id is not None}
    if not normalized_accounts or client is None:
        return {"checked": 0, "released": 0, "retained": 0, "errors": 0}

    tasks = db.query(models.VideoTask).filter(
        models.VideoTask.user_id == user.id,
        models.VideoTask.target_account_id.in_(sorted(normalized_accounts)),
        models.VideoTask.publish_at.isnot(None),
        models.VideoTask.publishing_status == "scheduled",
    ).all()

    result = {"checked": 0, "released": 0, "retained": 0, "errors": 0}
    now_utc = datetime.datetime.now(UTC).replace(microsecond=0)
    for task in tasks:
        if _lane(task) != ("vizard" if lane == "vizard" else "instant"):
            continue
        result["checked"] += 1
        account_id = int(task.target_account_id)
        if not task.postmypost_id:
            _release_local_reservation(task, "missing_provider_id")
            result["released"] += 1
            continue

        try:
            payload = client.get_publication(int(task.postmypost_id), account_ids=[account_id])
            verify_publication_payload(
                payload,
                expected_post_at=task.publish_at,
                now_utc=now_utc,
                minimum_lead=get_min_publish_lead_delta(),
            )
            result["retained"] += 1
        except Exception as error:
            if not _is_missing_provider_publication(error):
                if not isinstance(error, PublicationVerificationError):
                    result["errors"] += 1
                    logger.warning(
                        "Could not reconcile task=%s publication=%s; keeping local slot: %s",
                        task.id,
                        task.postmypost_id,
                        error,
                    )
                    continue

            try:
                client.delete_publication(
                    publication_id=int(task.postmypost_id),
                    account_ids=[account_id],
                )
            except Exception as delete_error:
                result["errors"] += 1
                logger.warning(
                    "Could not delete invalid publication task=%s publication=%s; keeping local slot: %s",
                    task.id,
                    task.postmypost_id,
                    delete_error,
                )
                continue

            _release_local_reservation(task, type(error).__name__)
            result["released"] += 1

    if result["released"]:
        db.commit()
        logger.info("PostMyPost reconciliation: %s", result)
    return result
