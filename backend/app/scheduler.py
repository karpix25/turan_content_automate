import datetime
import logging
import os
from typing import List

from dotenv import load_dotenv

from .database import SessionLocal
from . import models
from .integrations.postmypost import PostMyPostClient
from .telegram_progress import update_task_status_message
from .worker import celery_app

load_dotenv()

logger = logging.getLogger(__name__)
pmp_client = PostMyPostClient(api_key=os.getenv("POSTMYPOST_API_KEY", ""))


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
    ids = [
        item.account_id
        for item in db.query(models.UserPublishChannel).filter(
            models.UserPublishChannel.user_id == user_id,
            models.UserPublishChannel.enabled.is_(True),
        ).all()
    ]
    if ids:
        return ids

    env_ids = _parse_env_account_ids(os.getenv("POSTMYPOST_CHANNEL_IDS", ""))
    if env_ids:
        return env_ids

    # Fallback: use all accounts from the current project when user-level
    # toggles have not been saved yet.
    try:
        project_id = _get_project_id()
        accounts = pmp_client.get_accounts(project_id=project_id)
        account_ids = sorted(
            {
                int(item["id"])
                for item in accounts
                if isinstance(item, dict) and item.get("id") is not None
            }
        )
        if account_ids:
            logger.info(
                "No explicit enabled channels for user %s, fallback to all project accounts: %s",
                user_id,
                account_ids,
            )
            return account_ids
    except Exception as e:
        logger.warning("Failed to load fallback PostMyPost account ids in scheduler: %s", e)

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

        user = db.query(models.User).get(task.user_id)
        if not user:
            raise RuntimeError("Task user not found")

        account_ids = _get_task_account_ids(db, task, user.id)
        account_descriptions = _get_account_descriptions(db, user.id)
        content_by_account = {
            account_id: account_descriptions[account_id]
            for account_id in account_ids
            if account_id in account_descriptions
        }
        logger.info(
            "Task %s publication payload: user_id=%s telegram_id=%s account_ids=%s account_descriptions=%s",
            task_id,
            user.id,
            getattr(user, "telegram_id", None),
            account_ids,
            list(content_by_account.keys()),
        )
        project_id = _get_project_id()
        post_at = _normalize_post_at(task.publish_at, force_now)

        content = f"Auto content from Content Studio\nSource: {task.source_url}"
        vizard_title = (getattr(task, "source_title", None) or "").strip()
        if (getattr(task, "target_platform", None) or "").strip().lower() == "youtube" and vizard_title:
            content = vizard_title
            for account_id in account_ids:
                content_by_account.setdefault(account_id, vizard_title)

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
            )
        else:
            response = pmp_client.create_publication(
                project_id=project_id,
                account_ids=account_ids,
                post_at=post_at,
                file_id=int(file_id),
                content=content,
                content_by_account=content_by_account,
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
