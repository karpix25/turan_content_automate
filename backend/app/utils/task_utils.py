from typing import List

from .. import models
from ..publish_planner import plan_next_publish_times

IMMEDIATE_POSTMYPUBLISH_TASK_TYPES = {
    "avatar_instagram_post_5s",
    "instagram",
    "youtube",
}


def _should_publish_immediately(task_or_type) -> bool:
    task_type = getattr(task_or_type, "type", task_or_type)
    return task_type in IMMEDIATE_POSTMYPUBLISH_TASK_TYPES


def _plan_publish_times_for_outputs(
    db,
    user: models.User,
    output_platforms: list[str],
    manual_publish_at,
    output_group_keys: list[str | int | None] | None = None,
):
    outputs_count = len(output_platforms)
    if outputs_count < 1:
        return []
    if manual_publish_at is not None:
        return [manual_publish_at] * outputs_count
    if not bool(getattr(user, "auto_schedule_enabled", False)):
        return [None] * outputs_count

    if output_group_keys and len(output_group_keys) == outputs_count:
        grouped_output_indices: dict[str | int | None, list[int]] = {}
        for index, group_key in enumerate(output_group_keys):
            grouped_output_indices.setdefault(group_key, []).append(index)

        planned = [None] * outputs_count
        group_times = plan_next_publish_times(
            db=db,
            user=user,
            count=len(grouped_output_indices),
        )
        for indices, planned_time in zip(grouped_output_indices.values(), group_times):
            for index in indices:
                planned[index] = planned_time
        if all(item is not None for item in planned):
            return planned

    times = plan_next_publish_times(
        db=db,
        user=user,
        count=outputs_count,
    )
    planned = [None] * outputs_count
    for index, planned_time in enumerate(times):
        planned[index] = planned_time

    return planned


def _get_base_source_label(source_url: str) -> str:
    base = (source_url or "").split(" [slot ", 1)[0]
    base = base.split(" [variant ", 1)[0]
    base = base.split(" [clip ", 1)[0]
    base = base.split(" [account ", 1)[0]
    return base


def _resolve_publishing_status(publish_at, should_sync: bool) -> str:
    if publish_at:
        return "scheduled"
    return "in_progress" if should_sync else "not_published"


def _build_source_label(
    base_source: str,
    *,
    clip_index: int | None = None,
    slot_index: int | None = None,
    account_id: int | None = None,
) -> str:
    label = base_source
    if clip_index is not None:
        label += f" [clip {clip_index}]"
    if slot_index is not None:
        label += f" [slot {slot_index}]"
    if account_id is not None:
        label += f" [account {account_id}]"
    return label


def _upsert_variant_task(
    db,
    base_task: models.VideoTask,
    output_path: str,
    variant_index: int,
    publish_at,
    target_account_id: int | None,
    target_platform: str | None,
) -> models.VideoTask:
    base_source = _get_base_source_label(base_task.source_url)
    existing = db.query(models.VideoTask).filter(
        models.VideoTask.user_id == base_task.user_id,
        models.VideoTask.output_path == output_path,
        models.VideoTask.id != base_task.id,
    ).first()

    publishing_status = _resolve_publishing_status(publish_at, should_sync=True)

    if existing:
        existing.type = base_task.type
        existing.status = "completed"
        existing.vizard_project_id = base_task.vizard_project_id
        existing.source_url = f"{base_source} [slot {variant_index}] [account {target_account_id}]"
        existing.publish_at = publish_at
        existing.target_account_id = target_account_id
        existing.target_platform = target_platform
        existing.publishing_status = publishing_status
        db.commit()
        db.refresh(existing)
        return existing

    variant_task = models.VideoTask(
        user_id=base_task.user_id,
        source_url=f"{base_source} [slot {variant_index}] [account {target_account_id}]",
        type=base_task.type,
        status="completed",
        vizard_project_id=base_task.vizard_project_id,
        output_path=output_path,
        publish_at=publish_at,
        target_account_id=target_account_id,
        target_platform=target_platform,
        publishing_status=publishing_status,
    )
    db.add(variant_task)
    db.commit()
    db.refresh(variant_task)
    return variant_task


def _upsert_processed_task(
    db,
    base_task: models.VideoTask,
    output_path: str,
    source_label: str,
    source_title: str | None,
    publish_at,
    target_account_id: int | None,
    target_platform: str | None,
    should_sync: bool,
) -> models.VideoTask:
    existing = db.query(models.VideoTask).filter(
        models.VideoTask.user_id == base_task.user_id,
        models.VideoTask.output_path == output_path,
        models.VideoTask.id != base_task.id,
    ).first()

    publishing_status = _resolve_publishing_status(publish_at, should_sync=should_sync)

    if existing:
        already_synced = bool(
            existing.postmypost_id
            or existing.postmypost_file_id
            or existing.publishing_status in {"published", "in_progress"}
        )
        existing.type = base_task.type
        existing.status = "completed"
        existing.vizard_project_id = base_task.vizard_project_id
        existing.source_url = source_label
        existing.source_title = source_title
        existing.script_text = base_task.script_text
        existing.factual_outline = base_task.factual_outline
        existing.script_meta = base_task.script_meta
        existing.telegram_chat_id = base_task.telegram_chat_id
        existing.telegram_status_message_id = base_task.telegram_status_message_id
        existing.telegram_reply_message_id = getattr(base_task, "telegram_reply_message_id", None)
        existing.publish_at = publish_at
        existing.target_account_id = target_account_id
        existing.target_platform = target_platform
        if not already_synced:
            existing.postmypost_id = None
            existing.postmypost_file_id = None
            existing.preview_url = None
            existing.publishing_status = publishing_status
        db.commit()
        db.refresh(existing)
        return existing

    clip_task = models.VideoTask(
        user_id=base_task.user_id,
        source_url=source_label,
        type=base_task.type,
        status="completed",
        vizard_project_id=base_task.vizard_project_id,
        output_path=output_path,
        source_title=source_title,
        script_text=base_task.script_text,
        factual_outline=base_task.factual_outline,
        script_meta=base_task.script_meta,
        telegram_chat_id=base_task.telegram_chat_id,
        telegram_status_message_id=base_task.telegram_status_message_id,
        telegram_reply_message_id=getattr(base_task, "telegram_reply_message_id", None),
        publish_at=publish_at,
        target_account_id=target_account_id,
        target_platform=target_platform,
        publishing_status=publishing_status,
    )
    db.add(clip_task)
    db.commit()
    db.refresh(clip_task)
    return clip_task
