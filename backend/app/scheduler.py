import datetime
import logging
import os
import subprocess
from typing import List

import httpx
from dotenv import load_dotenv

from .database import SessionLocal
from . import models
from .integrations.postmypost import PostMyPostClient
from .publish_planner import get_min_publish_lead_delta, plan_next_publish_times
from .telegram_progress import (
    send_publication_batch_report_message,
    update_task_status_message,
)
from .utils.platform_utils import _get_account_platform_map
from .worker import celery_app

load_dotenv()

logger = logging.getLogger(__name__)
AVATAR_TASK_TYPES = {
    "avatar_heygen",
    "avatar_horizontal",
    "avatar_vertical",
    "avatar_youtube",
    "avatar_instagram",
    "avatar_instagram_post_5s",
    "avatar_shorts",
}
INSTAGRAM_POST_FIVE_SECOND_TASK_TYPES = {"avatar_instagram_post_5s"}
pmp_client = PostMyPostClient(api_key=os.getenv("POSTMYPOST_API_KEY", ""))

PMP_PENDING_PUBLICATION_STATUS = 5
DEFAULT_PMP_PUBLISHED_STATUS_CODES = "6"
DEFAULT_PMP_FAILED_STATUS_CODES = ""
PMP_STATUS_SYNC_DEFAULT_LIMIT = 50
PMP_STATUS_SYNC_DEFAULT_LOOKAHEAD_MINUTES = 30
PMP_STATUS_UNAVAILABLE = "status_unavailable"


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _env_int_set(name: str, default: str = "") -> set[int]:
    raw = os.getenv(name, default)
    result: set[int] = set()
    for part in raw.split(","):
        value = part.strip()
        if not value:
            continue
        try:
            result.add(int(value))
        except ValueError:
            logger.warning("Skipping invalid integer in %s: %s", name, value)
    return result


def _parse_env_account_ids(raw: str) -> List[int]:
    result: List[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            result.append(int(part))
        except ValueError:
            logger.warning(f"Skipping invalid account id in env: {part}")
    return result


def _get_project_id() -> int:
    project_id_raw = os.getenv("POSTMYPOST_PROJECT_ID", "").strip()
    project_id = int(project_id_raw) if project_id_raw else None
    return pmp_client.ensure_project_id(project_id)


def _get_enabled_account_ids(db, user_id: int) -> List[int]:
    rows = db.query(models.UserPublishChannel).filter(
        models.UserPublishChannel.user_id == user_id,
    ).order_by(models.UserPublishChannel.account_id.asc()).all()
    if rows:
        ids = [item.account_id for item in rows if item.enabled]
        if ids:
            return ids
        raise RuntimeError("No enabled PostMyPost accounts found")

    env_ids = _parse_env_account_ids(os.getenv("POSTMYPOST_CHANNEL_IDS", ""))
    if env_ids:
        return env_ids

    raise RuntimeError("No enabled PostMyPost accounts found")

def _get_account_ids_for_unschedule(db, task: models.VideoTask) -> List[int]:
    if task.target_account_id is not None:
        return [int(task.target_account_id)]

    try:
        return _get_enabled_account_ids(db, task.user_id)
    except Exception:
        pass

    if task.postmypost_id:
        try:
            publication = pmp_client.get_publication(int(task.postmypost_id))
            publication_accounts = publication.get("account_ids", []) if isinstance(publication, dict) else []
            ids = [int(item) for item in publication_accounts if item is not None]
            if ids:
                return ids
        except Exception as e:
            logger.warning(f"Failed to fetch account ids from publication {task.postmypost_id}: {e}")

    env_ids = _parse_env_account_ids(os.getenv("POSTMYPOST_CHANNEL_IDS", ""))
    if env_ids:
        return env_ids
    raise RuntimeError("Cannot determine account ids for unschedule")


def _get_task_account_ids(db, task: models.VideoTask, user_id: int) -> List[int]:
    if task.target_account_id is not None:
        return [int(task.target_account_id)]
    return _get_enabled_account_ids(db, user_id)


def _get_account_descriptions(db, user_id: int) -> dict[int, str]:
    rows = db.query(models.UserPublishChannel).filter(
        models.UserPublishChannel.user_id == user_id
    ).all()
    result: dict[int, str] = {}
    for row in rows:
        text_value = (row.publication_description or "").strip()
        if text_value:
            result[int(row.account_id)] = text_value
    return result


def _get_instagram_post_5s_description(task: models.VideoTask) -> str:
    try:
        post_meta = dict((task.script_meta or {}).get("instagram_post_5s") or {})
    except Exception:
        post_meta = {}
    return (
        (post_meta.get("rewritten_description") or "")
        or (task.script_text or "")
        or (task.source_title or "")
    ).strip()


def _build_publication_content(account_description: str | None, task: models.VideoTask | None = None) -> str:
    template = (account_description or "").strip()
    if task and task.type in INSTAGRAM_POST_FIVE_SECOND_TASK_TYPES:
        base_description = _get_instagram_post_5s_description(task)
        return "\n\n".join(part for part in [base_description, template] if part)
    return template


def _normalize_post_at(value: datetime.datetime | None, force_now: bool) -> datetime.datetime:
    if force_now or value is None:
        return datetime.datetime.now(datetime.timezone.utc)
    if value.tzinfo is None:
        post_at = value.replace(tzinfo=datetime.timezone.utc)
    else:
        post_at = value.astimezone(datetime.timezone.utc)

    min_post_at = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0) + get_min_publish_lead_delta()
    if post_at <= min_post_at:
        logger.warning(
            "PostMyPost schedule time %s is too close or in the past; moving to %s",
            post_at,
            min_post_at,
        )
        return min_post_at
    return post_at


def _resolve_publication_post_at(db, user: models.User, task: models.VideoTask, force_now: bool) -> datetime.datetime:
    post_at = _normalize_post_at(task.publish_at, force_now)
    if (
        force_now
        or task.type not in INSTAGRAM_POST_FIVE_SECOND_TASK_TYPES
        or not bool(getattr(user, "auto_schedule_enabled", False))
        or task.postmypost_id
    ):
        return post_at

    try:
        planned = plan_next_publish_times(db, user, 1, exclude_task_ids={task.id})
    except Exception as error:
        logger.warning("Task %s: failed to recheck 5s publish slot before PostMyPost sync: %s", task.id, error)
        return post_at

    if not planned:
        return post_at

    candidate = _normalize_post_at(planned[0], force_now=False)
    if task.publish_at is None or candidate < post_at - datetime.timedelta(minutes=1):
        logger.info(
            "Task %s: adjusted 5s PostMyPost schedule from %s to %s after final slot recheck",
            task.id,
            post_at,
            candidate,
        )
        return candidate
    return post_at


def _resolve_task_output_path(output_path: str | None) -> str | None:
    value = (output_path or "").strip()
    if not value:
        return None
    if os.path.isfile(value):
        return value
    normalized = value.lstrip("./")
    fallback_candidates = [
        os.path.join("/app", normalized),
        os.path.join("/app/database/media/output", os.path.basename(normalized)),
    ]
    for candidate in fallback_candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def _generate_local_preview_url(task_id: int, video_path: str | None) -> str | None:
    resolved_video_path = _resolve_task_output_path(video_path)
    if not resolved_video_path:
        return None

    previews_dir = os.path.join("/app/database/media", "previews")
    os.makedirs(previews_dir, exist_ok=True)
    preview_filename = f"task_{task_id}.jpg"
    preview_path = os.path.join(previews_dir, preview_filename)

    command = [
        "ffmpeg",
        "-y",
        "-ss",
        "1",
        "-i",
        resolved_video_path,
        "-frames:v",
        "1",
        "-vf",
        "scale=480:-2",
        "-q:v",
        "3",
        preview_path,
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=45)
    except Exception as exc:
        logger.warning("Failed to generate local preview for task %s: %s", task_id, exc)
        return None

    if not os.path.isfile(preview_path):
        return None
    return f"/media/previews/{preview_filename}"


def _cleanup_local_output(task: models.VideoTask) -> None:
    cleanup_enabled = os.getenv("DELETE_LOCAL_OUTPUT_AFTER_SYNC", "1").strip() not in {"0", "false", "False"}
    if not cleanup_enabled:
        return
    path = _resolve_task_output_path(task.output_path)
    if not path:
        task.output_path = None
        return
    try:
        os.remove(path)
        logger.info("Removed local output file after sync: %s", path)
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.warning("Failed to remove local output file %s: %s", path, e)
        return
    task.output_path = None


def _extract_status_summary(payload) -> dict:
    summary = {
        "publication_status": None,
        "status": None,
        "state": None,
        "detail_statuses": [],
    }
    detail_statuses = []

    def remember_detail(value) -> None:
        if value is None:
            return
        if value not in detail_statuses:
            detail_statuses.append(value)

    if not isinstance(payload, dict):
        return summary

    summary["publication_status"] = payload.get("publication_status") or payload.get("publicationStatus")
    summary["status"] = payload.get("status")
    summary["state"] = payload.get("state")

    def collect_nested_statuses(node) -> None:
        if isinstance(node, list):
            for item in node:
                collect_nested_statuses(item)
            return
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            key_text = str(key).lower()
            if key_text in {"publication_status", "publicationstatus", "status", "state"}:
                remember_detail(value)
            elif isinstance(value, (dict, list)):
                collect_nested_statuses(value)

    details = payload.get("details")
    if isinstance(details, list):
        for item in details:
            if not isinstance(item, dict):
                continue
            remember_detail(item.get("publication_status") or item.get("publicationStatus"))
            remember_detail(item.get("status"))
            remember_detail(item.get("state"))

    collect_nested_statuses(details)

    publications = payload.get("publications")
    if isinstance(publications, list):
        for item in publications:
            if not isinstance(item, dict):
                continue
            remember_detail(item.get("publication_status") or item.get("publicationStatus"))
            remember_detail(item.get("status"))
            remember_detail(item.get("state"))

    collect_nested_statuses(publications)

    summary["detail_statuses"] = detail_statuses
    return summary


def _status_values_for_classification(status_summary: dict) -> list:
    values = [
        status_summary.get("publication_status"),
        status_summary.get("status"),
        status_summary.get("state"),
    ]
    values.extend(status_summary.get("detail_statuses") or [])
    return [value for value in values if value is not None]


def _classify_postmypost_status(status_summary: dict) -> str | None:
    values = _status_values_for_classification(status_summary)
    published_codes = _env_int_set("POSTMYPOST_PUBLISHED_STATUS_CODES", DEFAULT_PMP_PUBLISHED_STATUS_CODES)
    failed_codes = _env_int_set("POSTMYPOST_FAILED_STATUS_CODES", DEFAULT_PMP_FAILED_STATUS_CODES)
    published_words = {
        "published",
        "publish",
        "posted",
        "post_done",
        "done",
        "completed",
        "complete",
        "success",
        "successful",
    }
    failed_words = {
        "failed",
        "fail",
        "error",
        "errored",
        "rejected",
        "canceled",
        "cancelled",
        "declined",
    }

    has_pending = False
    has_published = False
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, int) or (isinstance(value, str) and value.strip().isdigit()):
            numeric_value = int(value)
            if numeric_value in failed_codes:
                return "failed"
            if numeric_value in published_codes:
                has_published = True
            elif numeric_value == PMP_PENDING_PUBLICATION_STATUS:
                has_pending = True
            continue

        normalized = str(value).strip().lower().replace("-", "_").replace(" ", "_")
        if normalized in failed_words:
            return "failed"
        if normalized in published_words:
            has_published = True
            continue
        if "fail" in normalized or "error" in normalized or "reject" in normalized:
            return "failed"
        if "publish" in normalized and not any(token in normalized for token in ("pending", "wait", "progress", "schedule")):
            has_published = True
            continue
        if any(token in normalized for token in ("pending", "wait", "progress", "schedule")):
            has_pending = True

    if has_published and not has_pending:
        return "published"
    if has_pending:
        return None
    return None


def _update_postmypost_sync_meta(task: models.VideoTask, status_summary: dict, sync_status: str | None, error: str | None = None) -> None:
    meta = dict(task.script_meta or {})
    sync_meta = {
        "checked_at": datetime.datetime.utcnow().isoformat(),
        "publication_id": task.postmypost_id,
        "status_summary": status_summary,
    }
    if sync_status:
        sync_meta["mapped_status"] = sync_status
    if error:
        sync_meta["error"] = error[:500]
    meta["postmypost_status_sync"] = sync_meta
    task.script_meta = meta


def _is_postmypost_missing_publication_status_error(exc: Exception) -> bool:
    if not isinstance(exc, httpx.HTTPStatusError):
        return False
    response = exc.response
    if response is None or response.status_code != 422:
        return False
    try:
        body = response.text or ""
    except Exception:
        body = ""
    normalized = body.lower()
    return "publication_status" in normalized and "required property" in normalized


def _get_publication_batch_meta(task: models.VideoTask) -> dict:
    meta = dict(getattr(task, "script_meta", None) or {})
    batch_meta = meta.get("publication_batch_report")
    return dict(batch_meta or {}) if isinstance(batch_meta, dict) else {}


def _is_publication_batch_terminal(task: models.VideoTask) -> bool:
    status = (getattr(task, "publishing_status", None) or "").strip()
    if status in {"scheduled", "in_progress", "published", "failed"}:
        return True
    return bool(getattr(task, "postmypost_id", None))


def _publication_batch_sort_key(task: models.VideoTask) -> tuple:
    return (
        getattr(task, "publish_at", None) or datetime.datetime.max,
        getattr(task, "target_account_id", None) or 0,
        getattr(task, "id", 0) or 0,
    )


def _maybe_send_publication_batch_report(db, task: models.VideoTask) -> None:
    batch_meta = _get_publication_batch_meta(task)
    batch_id = (batch_meta.get("batch_id") or "").strip()
    if not batch_id or batch_meta.get("sent_at"):
        return

    expected_publications = int(batch_meta.get("expected_publications") or 0)
    if expected_publications < 1:
        return

    query = db.query(models.VideoTask).filter(
        models.VideoTask.user_id == task.user_id,
        models.VideoTask.telegram_status_message_id == task.telegram_status_message_id,
    )
    if task.vizard_project_id:
        query = query.filter(models.VideoTask.vizard_project_id == task.vizard_project_id)

    batch_tasks = []
    already_sent = False
    for candidate in query.all():
        candidate_batch_meta = _get_publication_batch_meta(candidate)
        if (candidate_batch_meta.get("batch_id") or "").strip() != batch_id:
            continue
        if candidate_batch_meta.get("sent_at"):
            already_sent = True
            break
        if (getattr(candidate, "publishing_status", None) or "").strip() != "not_published":
            batch_tasks.append(candidate)

    if already_sent:
        return
    if len(batch_tasks) < expected_publications:
        return
    if not all(_is_publication_batch_terminal(item) for item in batch_tasks):
        return

    batch_tasks = sorted(batch_tasks, key=_publication_batch_sort_key)
    if not send_publication_batch_report_message(batch_tasks, batch_meta):
        return

    sent_at = datetime.datetime.utcnow().isoformat()
    for item in batch_tasks:
        item_meta = dict(item.script_meta or {})
        item_batch_meta = dict(item_meta.get("publication_batch_report") or {})
        if (item_batch_meta.get("batch_id") or "").strip() != batch_id:
            continue
        item_batch_meta["sent_at"] = sent_at
        item_batch_meta["sent_by_task_id"] = task.id
        item_meta["publication_batch_report"] = item_batch_meta
        item.script_meta = item_meta
    db.commit()


def _complete_vizard_parent_with_existing_outputs(db, task: models.VideoTask, now: datetime.datetime) -> bool:
    if not task.vizard_project_id:
        return False

    child_count = db.query(models.VideoTask).filter(
        models.VideoTask.id != task.id,
        models.VideoTask.user_id == task.user_id,
        models.VideoTask.vizard_project_id == task.vizard_project_id,
        models.VideoTask.status == "completed",
        models.VideoTask.output_path.isnot(None),
    ).count()
    if child_count <= 0:
        return False

    meta = dict(task.script_meta or {})
    rescue_meta = dict(meta.get("queue_rescue") or {})
    rescue_meta.update(
        {
            "completed_without_requeue_at": now.isoformat(),
            "reason": "vizard_parent_has_child_outputs",
            "child_output_count": child_count,
        }
    )
    meta["queue_rescue"] = rescue_meta
    task.script_meta = meta
    task.status = "completed"
    db.commit()
    logger.warning(
        "Marked stale Vizard parent task id=%s project=%s completed because %s child output(s) already exist",
        task.id,
        task.vizard_project_id,
        child_count,
    )
    return True


@celery_app.task(name="rescue_stale_content_tasks")
def rescue_stale_content_tasks():
    pending_after_minutes = _env_int("TASK_REQUEUE_PENDING_AFTER_MINUTES", 5)
    processing_after_minutes = _env_int("TASK_REQUEUE_PROCESSING_AFTER_MINUTES", 720)
    cooldown_minutes = _env_int("TASK_REQUEUE_COOLDOWN_MINUTES", 15)
    max_age_hours = _env_int("TASK_REQUEUE_MAX_AGE_HOURS", 24)
    require_telegram = os.getenv("TASK_REQUEUE_REQUIRE_TELEGRAM", "1").strip().lower() not in {"0", "false", "no"}
    now = datetime.datetime.utcnow()
    pending_cutoff = now - datetime.timedelta(minutes=pending_after_minutes)
    processing_cutoff = now - datetime.timedelta(minutes=processing_after_minutes)
    cooldown_cutoff = now - datetime.timedelta(minutes=cooldown_minutes)
    oldest_allowed = now - datetime.timedelta(hours=max_age_hours)

    db = SessionLocal()
    try:
        query = db.query(models.VideoTask).filter(
            models.VideoTask.status.in_(["pending", "processing"]),
            models.VideoTask.created_at <= pending_cutoff,
            models.VideoTask.created_at >= oldest_allowed,
        )
        if require_telegram:
            query = query.filter(
                models.VideoTask.telegram_chat_id.isnot(None),
                models.VideoTask.telegram_status_message_id.isnot(None),
            )
        candidates = query.order_by(models.VideoTask.created_at.asc()).limit(10).all()

        rescued = 0
        for task in candidates:
            updated_at = task.updated_at or task.created_at
            if task.status == "processing" and updated_at > processing_cutoff:
                continue
            if _complete_vizard_parent_with_existing_outputs(db, task, now):
                continue

            meta = dict(task.script_meta or {})
            rescue_meta = dict(meta.get("queue_rescue") or {})
            last_requeued_raw = rescue_meta.get("last_requeued_at")
            if last_requeued_raw:
                try:
                    last_requeued_at = datetime.datetime.fromisoformat(str(last_requeued_raw))
                    if last_requeued_at > cooldown_cutoff:
                        continue
                except ValueError:
                    pass

            previous_status = task.status
            task.status = "pending"
            rescue_meta.update(
                {
                    "last_requeued_at": now.isoformat(),
                    "previous_status": previous_status,
                    "reason": "stale_pending_or_processing",
                }
            )
            rescue_meta["count"] = int(rescue_meta.get("count") or 0) + 1
            meta["queue_rescue"] = rescue_meta
            task.script_meta = meta
            db.commit()

            celery_app.send_task("process_content_task", args=[task.id])
            rescued += 1
            logger.warning(
                "Requeued stale content task id=%s previous_status=%s updated_at=%s",
                task.id,
                previous_status,
                updated_at,
            )

        if rescued:
            logger.warning("Rescued %s stale content task(s)", rescued)
    finally:
        db.close()


@celery_app.task(name="sync_publication_task", bind=True, max_retries=3)
def sync_publication_task(self, task_id: int, force_now: bool = False):
    db = SessionLocal()
    try:
        task = db.query(models.VideoTask).get(task_id)
        if not task:
            return
        if task.status != "completed":
            logger.info(f"Task {task_id} is not completed yet, skipping publication sync")
            return

        if task.type in AVATAR_TASK_TYPES and task.type not in INSTAGRAM_POST_FIVE_SECOND_TASK_TYPES:
            task.postmypost_id = None
            task.postmypost_file_id = None
            task.preview_url = None
            task.publish_at = None
            task.publishing_status = "not_published"
            db.commit()
            logger.info(
                "Task %s: avatar skipped PostMyPost sync (saved to Yandex.Disk in worker stage)",
                task_id,
            )
            return

        user = db.query(models.User).get(task.user_id)
        if not user:
            raise RuntimeError("Task user not found")

        account_ids = _get_task_account_ids(db, task, user.id)
        account_descriptions = _get_account_descriptions(db, user.id)
        content_by_account = {
            account_id: _build_publication_content(account_descriptions.get(account_id), task)
            for account_id in account_ids
        }
        logger.info(
            "Task %s publication payload: user_id=%s telegram_id=%s account_ids=%s account_descriptions=%s",
            task_id,
            user.id,
            getattr(user, "telegram_id", None),
            account_ids,
            list(account_descriptions.keys()),
        )
        project_id = _get_project_id()
        post_at = _resolve_publication_post_at(db, user, task, force_now)
        target_platform = (getattr(task, "target_platform", "") or "").lower()

        missing_description_account_ids = [
            account_id for account_id in account_ids if account_id not in account_descriptions
        ]
        if missing_description_account_ids:
            logger.warning(
                "Task %s has no publication description for account_ids=%s; publication content will be empty",
                task_id,
                missing_description_account_ids,
            )

        content = ""
        title_by_account: dict[int, str] = {}

        # Determine publication type (1: Post, 4: Reels/Shorts/Clips)
        # We use 4 for YouTube, Instagram, and TikTok for these clipping tasks.
        pub_type = 1
        if task.type in INSTAGRAM_POST_FIVE_SECOND_TASK_TYPES:
            pub_type = 1
        elif target_platform in {"youtube", "instagram", "tiktok"}:
            pub_type = 4

        account_platform_map = _get_account_platform_map(account_ids)
        for account_id in account_ids:
            acc_platform = account_platform_map.get(account_id, "universal")
            if task.type in INSTAGRAM_POST_FIVE_SECOND_TASK_TYPES:
                title_by_account[account_id] = (getattr(task, "source_title", None) or "").strip() or "Видео"
            elif acc_platform == "youtube" or target_platform == "youtube":
                title_by_account[account_id] = (getattr(task, "source_title", None) or "").strip() or "Видео"

        file_id = task.postmypost_file_id
        if not task.preview_url:
            task.preview_url = _generate_local_preview_url(task.id, task.output_path)
        if not file_id:
            update_task_status_message(
                db,
                task,
                stage="Публикация",
                detail="Загружаю финальный файл в PostMyPost.",
            )
            resolved_output_path = _resolve_task_output_path(task.output_path)
            if not resolved_output_path:
                raise RuntimeError("Task has no local output file and no PostMyPost file id")
            file_id = pmp_client.upload_local_file(project_id=project_id, file_path=resolved_output_path)
            task.postmypost_file_id = int(file_id)

        update_task_status_message(
            db,
            task,
            stage="Публикация",
            detail="Создаю или обновляю публикацию в PostMyPost.",
        )
        if task.postmypost_id:
            response = pmp_client.update_publication(
                publication_id=int(task.postmypost_id),
                account_ids=account_ids,
                post_at=post_at,
                file_id=int(file_id),
                content=content,
                content_by_account=content_by_account,
                title_by_account=title_by_account,
                publication_type=pub_type,
            )
        else:
            response = pmp_client.create_publication(
                project_id=project_id,
                account_ids=account_ids,
                post_at=post_at,
                file_id=int(file_id),
                content=content,
                content_by_account=content_by_account,
                title_by_account=title_by_account,
                publication_type=pub_type,
            )

        publication_id = response.get("id") if isinstance(response, dict) else None
        if publication_id:
            task.postmypost_id = str(publication_id)
        preview_url = pmp_client.extract_preview_url(response)
        if not preview_url and publication_id:
            try:
                publication_payload = pmp_client.get_publication(int(publication_id))
                preview_url = pmp_client.extract_preview_url(publication_payload)
            except Exception as preview_error:
                logger.warning("Failed to fetch publication preview for task %s: %s", task_id, preview_error)
        if preview_url:
            task.preview_url = preview_url

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        task.publishing_status = "scheduled" if post_at > now_utc else "in_progress"
        task.publish_at = post_at.replace(tzinfo=None)
        _cleanup_local_output(task)
        db.commit()
        if post_at > now_utc:
            post_label = post_at.strftime("%d.%m %H:%M UTC")
            update_task_status_message(
                db,
                task,
                stage="Запланировано",
                detail=f"Публикация поставлена на {post_label}.",
                ok=True,
            )
        else:
            update_task_status_message(
                db,
                task,
                stage="Публикация начата",
                detail="Ролик отправлен в PostMyPost.",
                ok=True,
            )
        _maybe_send_publication_batch_report(db, task)
        logger.info(f"Task {task_id} synced to PostMyPost publication {task.postmypost_id}")
    except Exception as e:
        logger.error(f"Failed to sync publication for task {task_id}: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        if self.request.retries < self.max_retries:
            delay = 60 * (self.request.retries + 1)
            logger.warning("Task %s: retrying PostMyPost sync in %ss", task_id, delay)
            raise self.retry(exc=e, countdown=delay)
        task = db.query(models.VideoTask).get(task_id)
        if task:
            task.publishing_status = "failed"
            db.commit()
            update_task_status_message(
                db,
                task,
                stage="Ошибка публикации",
                detail=f"Не удалось синхронизировать публикацию: {str(e)[:300]}",
                failed=True,
            )
            _maybe_send_publication_batch_report(db, task)
    finally:
        db.close()


@celery_app.task(name="publish_video_task")
def publish_video_task(task_id: int):
    sync_publication_task(task_id=task_id, force_now=True)


@celery_app.task(name="sync_postmypost_publication_statuses")
def sync_postmypost_publication_statuses(limit: int | None = None):
    batch_limit = limit or _env_int("POSTMYPOST_STATUS_SYNC_LIMIT", PMP_STATUS_SYNC_DEFAULT_LIMIT)
    lookahead_minutes = _env_int(
        "POSTMYPOST_STATUS_SYNC_LOOKAHEAD_MINUTES",
        PMP_STATUS_SYNC_DEFAULT_LOOKAHEAD_MINUTES,
        minimum=0,
    )
    now = datetime.datetime.utcnow()
    publish_cutoff = now + datetime.timedelta(minutes=lookahead_minutes)

    db = SessionLocal()
    updated = 0
    checked = 0
    try:
        tasks = (
            db.query(models.VideoTask)
            .filter(
                models.VideoTask.postmypost_id.isnot(None),
                models.VideoTask.publishing_status.in_(["scheduled", "in_progress"]),
                models.VideoTask.publish_at.isnot(None),
                models.VideoTask.publish_at <= publish_cutoff,
            )
            .order_by(models.VideoTask.publish_at.asc(), models.VideoTask.updated_at.asc())
            .limit(batch_limit)
            .all()
        )

        for task in tasks:
            checked += 1
            try:
                publication_payload = pmp_client.get_publication(int(task.postmypost_id))
                status_summary = _extract_status_summary(publication_payload)
                mapped_status = _classify_postmypost_status(status_summary)
                preview_url = pmp_client.extract_preview_url(publication_payload)
                if preview_url:
                    task.preview_url = preview_url

                _update_postmypost_sync_meta(task, status_summary, mapped_status)

                if mapped_status == "published" and task.publishing_status != "published":
                    task.publishing_status = "published"
                    updated += 1
                    update_task_status_message(
                        db,
                        task,
                        stage="Опубликовано",
                        detail="PostMyPost подтвердил публикацию ролика.",
                        ok=True,
                    )
                elif mapped_status == "failed" and task.publishing_status != "failed":
                    task.publishing_status = "failed"
                    updated += 1
                    update_task_status_message(
                        db,
                        task,
                        stage="Ошибка публикации",
                        detail="PostMyPost вернул ошибочный статус публикации.",
                        failed=True,
                    )
                elif task.publishing_status == "scheduled" and task.publish_at and task.publish_at <= now:
                    task.publishing_status = "in_progress"
                    updated += 1

                db.commit()
            except Exception as e:
                if _is_postmypost_missing_publication_status_error(e):
                    logger.warning(
                        "PostMyPost status unavailable for task %s publication=%s; excluding from future status sync: %s",
                        task.id,
                        task.postmypost_id,
                        e,
                    )
                    try:
                        db.rollback()
                        task.publishing_status = PMP_STATUS_UNAVAILABLE
                        _update_postmypost_sync_meta(task, {}, PMP_STATUS_UNAVAILABLE, error=str(e))
                        updated += 1
                        db.commit()
                    except Exception:
                        db.rollback()
                    continue

                logger.warning("Failed to sync PostMyPost status for task %s: %s", task.id, e)
                try:
                    db.rollback()
                    _update_postmypost_sync_meta(task, {}, None, error=str(e))
                    db.commit()
                except Exception:
                    db.rollback()

        if checked:
            logger.info("PostMyPost status sync checked=%s updated=%s", checked, updated)
        return {"checked": checked, "updated": updated}
    finally:
        db.close()


@celery_app.task(name="unschedule_publication_task")
def unschedule_publication_task(task_id: int):
    db = SessionLocal()
    try:
        task = db.query(models.VideoTask).get(task_id)
        if not task:
            return
        if not task.postmypost_id:
            task.publishing_status = "not_published"
            task.publish_at = None
            task.preview_url = None
            db.commit()
            update_task_status_message(
                db,
                task,
                stage="Снято с публикации",
                detail="Публикация убрана из очереди.",
                ok=True,
            )
            return

        user = db.query(models.User).get(task.user_id)
        if not user:
            raise RuntimeError("Task user not found")

        account_ids = _get_account_ids_for_unschedule(db, task)
        pmp_client.delete_publication(publication_id=int(task.postmypost_id), account_ids=account_ids, delete_option=3)

        task.postmypost_id = None
        task.publish_at = None
        task.preview_url = None
        task.publishing_status = "not_published"
        db.commit()
        update_task_status_message(
            db,
            task,
            stage="Снято с публикации",
            detail="Публикация удалена из PostMyPost.",
            ok=True,
        )
        logger.info(f"Task {task_id} unscheduled in PostMyPost")
    except Exception as e:
        logger.error(f"Failed to unschedule publication for task {task_id}: {e}")
        task = db.query(models.VideoTask).get(task_id)
        if task:
            task.publishing_status = "failed"
            db.commit()
            update_task_status_message(
                db,
                task,
                stage="Ошибка публикации",
                detail=f"Не удалось снять публикацию: {str(e)[:300]}",
                failed=True,
            )
    finally:
        db.close()
