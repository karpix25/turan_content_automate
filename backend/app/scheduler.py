import datetime
import logging
import os
from typing import List

from dotenv import load_dotenv

from .database import SessionLocal
from . import models
from .integrations.postmypost import PostMyPostClient
from .telegram_progress import update_task_status_message
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
    "avatar_shorts",
}
pmp_client = PostMyPostClient(api_key=os.getenv("POSTMYPOST_API_KEY", ""))


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


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


def _build_publication_content(clip_title: str | None, account_description: str | None) -> str:
    title = (clip_title or "").strip()
    description = (account_description or "").strip()
    if title and description:
        return f"{title}\n\n{description}"
    return title or description


def _normalize_post_at(value: datetime.datetime | None, force_now: bool) -> datetime.datetime:
    if force_now or value is None:
        return datetime.datetime.now(datetime.timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(datetime.timezone.utc)


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


@celery_app.task(name="rescue_stale_content_tasks")
def rescue_stale_content_tasks():
    pending_after_minutes = _env_int("TASK_REQUEUE_PENDING_AFTER_MINUTES", 5)
    processing_after_minutes = _env_int("TASK_REQUEUE_PROCESSING_AFTER_MINUTES", 240)
    cooldown_minutes = _env_int("TASK_REQUEUE_COOLDOWN_MINUTES", 15)
    now = datetime.datetime.utcnow()
    pending_cutoff = now - datetime.timedelta(minutes=pending_after_minutes)
    processing_cutoff = now - datetime.timedelta(minutes=processing_after_minutes)
    cooldown_cutoff = now - datetime.timedelta(minutes=cooldown_minutes)

    db = SessionLocal()
    try:
        candidates = (
            db.query(models.VideoTask)
            .filter(
                models.VideoTask.status.in_(["pending", "processing"]),
                models.VideoTask.created_at <= pending_cutoff,
            )
            .order_by(models.VideoTask.created_at.asc())
            .limit(25)
            .all()
        )

        rescued = 0
        for task in candidates:
            updated_at = task.updated_at or task.created_at
            if task.status == "processing" and updated_at > processing_cutoff:
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


@celery_app.task(name="sync_publication_task")
def sync_publication_task(task_id: int, force_now: bool = False):
    db = SessionLocal()
    try:
        task = db.query(models.VideoTask).get(task_id)
        if not task:
            return
        if task.status != "completed":
            logger.info(f"Task {task_id} is not completed yet, skipping publication sync")
            return

        if task.type in AVATAR_TASK_TYPES:
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
        vizard_title = (getattr(task, "source_title", None) or "").strip()
        content_by_account = {
            account_id: _build_publication_content(vizard_title, account_descriptions.get(account_id))
            for account_id in account_ids
            if vizard_title or account_id in account_descriptions
        }
        logger.info(
            "Task %s publication payload: user_id=%s telegram_id=%s account_ids=%s account_descriptions=%s vizard_title=%s",
            task_id,
            user.id,
            getattr(user, "telegram_id", None),
            account_ids,
            list(account_descriptions.keys()),
            bool(vizard_title),
        )
        project_id = _get_project_id()
        post_at = _normalize_post_at(task.publish_at, force_now)
        target_platform = (getattr(task, "target_platform", "") or "").lower()

        missing_description_account_ids = [
            account_id for account_id in account_ids if account_id not in account_descriptions
        ]
        if missing_description_account_ids:
            logger.warning(
                "Task %s has no publication description for account_ids=%s; using Vizard title only when available",
                task_id,
                missing_description_account_ids,
            )

        content = ""
        # Prepare account-specific titles
        title_by_account: dict[int, str] = {}

        # Determine publication type (1: Post, 4: Reels/Shorts/Clips)
        # We use 4 for YouTube, Instagram, and TikTok for these clipping tasks.
        pub_type = 1
        if target_platform in {"youtube", "instagram", "tiktok"}:
            pub_type = 4

        # For YouTube, we MUST have a title.
        # We populate it for any account identified as 'youtube' or if task.target_platform is 'youtube'.
        if vizard_title:
            account_platform_map = _get_account_platform_map(account_ids)
            for account_id in account_ids:
                acc_platform = account_platform_map.get(account_id, "universal")
                if acc_platform == "youtube" or target_platform == "youtube":
                    title_by_account[account_id] = vizard_title

        file_id = task.postmypost_file_id
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
        logger.info(f"Task {task_id} synced to PostMyPost publication {task.postmypost_id}")
    except Exception as e:
        logger.error(f"Failed to sync publication for task {task_id}: {e}")
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
    finally:
        db.close()


@celery_app.task(name="publish_video_task")
def publish_video_task(task_id: int):
    sync_publication_task(task_id=task_id, force_now=True)


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
