import datetime
from typing import List

from .. import models
from ..publish_planner import plan_next_publish_times
from .platform_utils import _normalize_platform_code


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

        group_platforms: dict[str | int | None, list[str]] = {}
        can_share_group_slots = True
        for group_key, indices in grouped_output_indices.items():
            platforms = [_normalize_platform_code(output_platforms[index]) for index in indices]
            if len(platforms) != len(set(platforms)):
                can_share_group_slots = False
                break
            group_platforms[group_key] = platforms

        if can_share_group_slots:
            planned: list[datetime.datetime | None] = [None] * outputs_count
            platforms = sorted({platform for values in group_platforms.values() for platform in values})
            group_count = len(grouped_output_indices)
            candidate_count = max(group_count + 50, group_count * max(2, len(platforms)))
            candidates_by_platform = {
                platform: plan_next_publish_times(
                    db=db,
                    user=user,
                    count=candidate_count,
                    platform_code=platform,
                )
                for platform in platforms
            }
            reserved_by_platform: dict[str, set[datetime.datetime]] = {platform: set() for platform in platforms}

            for group_key, indices in grouped_output_indices.items():
                required_platforms = group_platforms[group_key]
                candidate_pool = sorted(
                    {
                        candidate
                        for platform in required_platforms
                        for candidate in candidates_by_platform.get(platform, [])
                    }
                )
                shared_time = None
                for candidate in candidate_pool:
                    if all(
                        candidate in candidates_by_platform.get(platform, [])
                        and candidate not in reserved_by_platform[platform]
                        for platform in required_platforms
                    ):
                        shared_time = candidate
                        break
                if shared_time is None:
                    break
                for platform in required_platforms:
                    reserved_by_platform[platform].add(shared_time)
                for index in indices:
                    planned[index] = shared_time

            if all(item is not None for item in planned):
                return planned

    planned: list[datetime.datetime | None] = [None] * outputs_count
    grouped_indices: dict[str, list[int]] = {}
    for index, platform_code in enumerate(output_platforms):
        normalized = _normalize_platform_code(platform_code)
        grouped_indices.setdefault(normalized, []).append(index)

    for platform_code, indices in grouped_indices.items():
        times = plan_next_publish_times(
            db=db,
            user=user,
            count=len(indices),
            platform_code=platform_code,
        )
        for idx, planned_time in zip(indices, times):
            planned[idx] = planned_time

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
