import datetime
import os
from zoneinfo import ZoneInfo

from . import models

MSK_TZ = ZoneInfo("Europe/Moscow")
UTC = datetime.timezone.utc

DEFAULT_LIMIT_PER_DAY = 3
DEFAULT_ACCOUNT_LIMIT_PER_DAY = 3
MIN_ACCOUNT_LIMIT_PER_DAY = 2
DEFAULT_START_MSK = "10:00:00"
DEFAULT_END_MSK = "22:00:00"
MINUTE_OFFSETS = (11, 17, 23, 29, 37, 41, 47, 53)
DEFAULT_MIN_LEAD_MINUTES = 60


def get_min_publish_lead_delta() -> datetime.timedelta:
    raw = (
        os.getenv("POSTMYPOST_MIN_SCHEDULE_LEAD_MINUTES")
        or os.getenv("PUBLISH_MIN_LEAD_MINUTES")
        or str(DEFAULT_MIN_LEAD_MINUTES)
    )
    try:
        minutes = max(0, int(raw))
    except (TypeError, ValueError):
        minutes = DEFAULT_MIN_LEAD_MINUTES
    return datetime.timedelta(minutes=minutes)


def parse_hhmmss(value: str, fallback: str) -> datetime.time:
    raw = (value or "").strip()
    if not raw:
        raw = fallback
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            parsed = datetime.datetime.strptime(raw, fmt).time()
            return parsed.replace(microsecond=0)
        except ValueError:
            continue
    return datetime.datetime.strptime(fallback, "%H:%M:%S").time()


def validate_schedule_settings(limit_per_day: int | None, start_msk: str | None, end_msk: str | None) -> tuple[int, str, str]:
    limit = int(limit_per_day) if limit_per_day is not None else DEFAULT_LIMIT_PER_DAY
    if limit < 1 or limit > 96:
        raise ValueError("publish_limit_per_day must be in range 1..96")

    start_t = parse_hhmmss(start_msk or DEFAULT_START_MSK, DEFAULT_START_MSK)
    end_t = parse_hhmmss(end_msk or DEFAULT_END_MSK, DEFAULT_END_MSK)
    if datetime.datetime.combine(datetime.date.today(), end_t) <= datetime.datetime.combine(datetime.date.today(), start_t):
        raise ValueError("publish_window_end_msk must be later than publish_window_start_msk")
    return limit, start_t.strftime("%H:%M:%S"), end_t.strftime("%H:%M:%S")


def validate_account_publish_limit(value: int | None) -> int:
    limit = int(value) if value is not None else DEFAULT_ACCOUNT_LIMIT_PER_DAY
    if limit < MIN_ACCOUNT_LIMIT_PER_DAY or limit > 96:
        raise ValueError("publish_limit_per_day must be in range 2..96")
    return limit


def _to_utc_naive(dt_aware: datetime.datetime) -> datetime.datetime:
    return dt_aware.astimezone(UTC).replace(tzinfo=None, microsecond=0)


def _build_daily_slots(day_msk: datetime.date, limit_per_day: int, start_msk: datetime.time, end_msk: datetime.time) -> list[datetime.datetime]:
    start_dt = datetime.datetime.combine(day_msk, start_msk, tzinfo=MSK_TZ)
    end_dt = datetime.datetime.combine(day_msk, end_msk, tzinfo=MSK_TZ)
    if limit_per_day <= 1:
        single_offset_seconds = min(17 * 60, max(60, int((end_dt - start_dt).total_seconds()) - 60))
        return [(start_dt + datetime.timedelta(seconds=single_offset_seconds)).replace(microsecond=0)]

    total_seconds = int((end_dt - start_dt).total_seconds())
    if total_seconds <= 0:
        return [start_dt]

    bucket = total_seconds / float(limit_per_day)
    slots: list[datetime.datetime] = []
    for index in range(limit_per_day):
        offset_minutes = MINUTE_OFFSETS[index % len(MINUTE_OFFSETS)]
        bucket_offset_seconds = min(offset_minutes * 60, max(60, int(bucket) - 60))
        seconds = int(round(bucket * index)) + bucket_offset_seconds
        slot = start_dt + datetime.timedelta(seconds=seconds)
        if slot >= end_dt:
            slot = end_dt - datetime.timedelta(minutes=1)
        slots.append(slot.replace(microsecond=0))
    return slots


def _publication_lane_for_task(row: models.VideoTask) -> str:
    return "vizard" if getattr(row, "vizard_project_id", None) else "instant"


def validate_account_format_limit(value: int | None, total_limit: int, field_name: str) -> int:
    limit = int(value) if value is not None else total_limit
    if limit < 1 or limit > total_limit:
        raise ValueError(f"{field_name} must be in range 1..{total_limit}")
    return limit


def get_project_format_limits(db, user: models.User | int, project_id: int | None) -> dict[str, int]:
    user_id = int(getattr(user, "id", user))
    total_limit = validate_account_publish_limit(
        getattr(user, "publish_limit_per_day", DEFAULT_ACCOUNT_LIMIT_PER_DAY)
    )
    default_vizard = max(1, min(total_limit, total_limit // 2))
    limits = {
        "total": total_limit,
        "vizard": default_vizard,
        "other": total_limit,
    }
    if project_id is None:
        return limits

    rows = db.query(models.PostMyPostProjectSetting).filter(
        models.PostMyPostProjectSetting.user_id == user_id,
        models.PostMyPostProjectSetting.project_id == int(project_id),
    ).all()
    row = rows[0] if rows else None
    if row is None:
        return limits

    total_limit = validate_account_publish_limit(
        getattr(row, "publish_limit_per_day", total_limit)
    )
    return {
        "total": total_limit,
        "vizard": validate_account_format_limit(
            getattr(row, "vizard_limit_per_day", default_vizard),
            total_limit,
            "vizard_limit_per_day",
        ),
        "other": validate_account_format_limit(
            getattr(row, "other_formats_limit_per_day", total_limit),
            total_limit,
            "other_formats_limit_per_day",
        ),
    }


def set_project_format_limits(
    db,
    user_id: int,
    project_id: int,
    total_limit: int,
    vizard_limit: int,
    other_limit: int,
) -> dict[str, int]:
    total_limit = validate_account_publish_limit(total_limit)
    vizard_limit = validate_account_format_limit(vizard_limit, total_limit, "vizard_limit_per_day")
    other_limit = validate_account_format_limit(other_limit, total_limit, "other_formats_limit_per_day")
    rows = db.query(models.PostMyPostProjectSetting).filter(
        models.PostMyPostProjectSetting.user_id == user_id,
        models.PostMyPostProjectSetting.project_id == int(project_id),
    ).all()
    row = rows[0] if rows else None
    if row is None:
        row = models.PostMyPostProjectSetting(user_id=user_id, project_id=int(project_id))
        db.add(row)
    row.publish_limit_per_day = total_limit
    row.vizard_limit_per_day = vizard_limit
    row.other_formats_limit_per_day = other_limit
    return {"total": total_limit, "vizard": vizard_limit, "other": other_limit}


def _get_account_limit_map(
    db,
    user: models.User,
    account_ids: list[int],
    project_id: int | None = None,
) -> dict[int, dict[str, int]]:
    project_limits = get_project_format_limits(db, user, project_id)
    limits: dict[int, dict[str, int]] = {}
    for account_id in account_ids:
        limits[int(account_id)] = dict(project_limits)
    return limits


def _task_publish_day_msk(publish_at: datetime.datetime) -> datetime.date:
    publish_utc = publish_at.replace(tzinfo=UTC) if publish_at.tzinfo is None else publish_at.astimezone(UTC)
    return publish_utc.astimezone(MSK_TZ).date()


def plan_next_publish_times_for_account_outputs(
    db,
    user: models.User,
    account_ids: list[int | None],
    *,
    lane: str,
    project_id: int | None = None,
    exclude_task_ids: set[int] | None = None,
    allow_immediate_if_today_slot_available: bool = False,
    minimum_utc: datetime.datetime | None = None,
) -> list[datetime.datetime | None]:
    if not account_ids:
        return []

    normalized_lane = "vizard" if lane == "vizard" else "instant"
    concrete_account_ids = [int(item) for item in account_ids if item is not None]
    if len(concrete_account_ids) != len(account_ids):
        return plan_next_publish_times(db, user, len(account_ids), exclude_task_ids=exclude_task_ids)

    _limit, start_raw, end_raw = validate_schedule_settings(
        DEFAULT_LIMIT_PER_DAY,
        getattr(user, "publish_window_start_msk", DEFAULT_START_MSK),
        getattr(user, "publish_window_end_msk", DEFAULT_END_MSK),
    )
    start_time = parse_hhmmss(start_raw, DEFAULT_START_MSK)
    end_time = parse_hhmmss(end_raw, DEFAULT_END_MSK)
    account_limits = _get_account_limit_map(
        db,
        user,
        list(dict.fromkeys(concrete_account_ids)),
        project_id=project_id,
    )

    now_utc = datetime.datetime.now(UTC).replace(microsecond=0)
    earliest_utc = now_utc + get_min_publish_lead_delta()
    if minimum_utc is not None:
        minimum_aware = (
            minimum_utc.replace(tzinfo=UTC)
            if minimum_utc.tzinfo is None
            else minimum_utc.astimezone(UTC)
        )
        earliest_utc = max(earliest_utc, minimum_aware.replace(microsecond=0))
    earliest_msk = earliest_utc.astimezone(MSK_TZ)

    excluded_ids = {int(item) for item in (exclude_task_ids or set())}
    occupied_rows = db.query(models.VideoTask).filter(
        models.VideoTask.user_id == user.id,
        models.VideoTask.target_account_id.in_(list(account_limits.keys())),
        models.VideoTask.publish_at.isnot(None),
        models.VideoTask.publishing_status.in_(["scheduled", "in_progress", "published"]),
        *(
            [models.VideoTask.postmypost_project_id == int(project_id)]
            if project_id is not None
            else []
        ),
    ).all()

    reserved_slots: dict[int, set[datetime.datetime]] = {}
    daily_counts: dict[tuple[int, datetime.date], int] = {}
    format_counts: dict[tuple[int, datetime.date, str], int] = {}
    for row in occupied_rows:
        if (
            row.id in excluded_ids
            or row.publish_at is None
            or row.target_account_id is None
            or not getattr(row, "postmypost_id", None)
        ):
            continue
        row_lane = "vizard" if _publication_lane_for_task(row) == "vizard" else "other"
        account_id = int(row.target_account_id)
        publish_utc = row.publish_at.replace(tzinfo=UTC) if row.publish_at.tzinfo is None else row.publish_at.astimezone(UTC)
        publish_utc_naive = publish_utc.replace(tzinfo=None, microsecond=0)
        day_msk = _task_publish_day_msk(row.publish_at)
        reserved_slots.setdefault(account_id, set()).add(publish_utc_naive)
        daily_key = (account_id, day_msk)
        daily_counts[daily_key] = daily_counts.get(daily_key, 0) + 1
        format_key = (account_id, day_msk, row_lane)
        format_counts[format_key] = format_counts.get(format_key, 0) + 1

    planned: list[datetime.datetime | None] = []
    for account_id in concrete_account_ids:
        account_settings = account_limits[int(account_id)]
        limit_per_day = account_settings["total"]
        format_group = "vizard" if normalized_lane == "vizard" else "other"
        format_limit = account_settings[format_group]
        account_reserved = reserved_slots.setdefault(account_id, set())
        day_cursor = earliest_msk.date()
        planned_for_output = False

        if allow_immediate_if_today_slot_available and normalized_lane == "instant":
            today = now_utc.astimezone(MSK_TZ).date()
            today_key = (account_id, today)
            format_key = (account_id, today, format_group)
            if (
                daily_counts.get(today_key, 0) < limit_per_day
                and format_counts.get(format_key, 0) < format_limit
            ):
                daily_counts[today_key] = daily_counts.get(today_key, 0) + 1
                format_counts[format_key] = format_counts.get(format_key, 0) + 1
                planned.append(None)
                continue

        for _ in range(0, 370):
            daily_key = (account_id, day_cursor)
            format_key = (account_id, day_cursor, format_group)
            if (
                daily_counts.get(daily_key, 0) >= limit_per_day
                or format_counts.get(format_key, 0) >= format_limit
            ):
                day_cursor = day_cursor + datetime.timedelta(days=1)
                continue

            slots_msk = _build_daily_slots(
                day_msk=day_cursor,
                limit_per_day=limit_per_day,
                start_msk=start_time,
                end_msk=end_time,
            )
            for slot_msk in slots_msk:
                if slot_msk <= earliest_msk:
                    continue
                slot_utc_naive = _to_utc_naive(slot_msk)
                if slot_utc_naive in account_reserved:
                    continue
                account_reserved.add(slot_utc_naive)
                daily_counts[daily_key] = daily_counts.get(daily_key, 0) + 1
                format_counts[format_key] = format_counts.get(format_key, 0) + 1
                planned.append(slot_utc_naive)
                planned_for_output = True
                break

            if planned_for_output:
                break
            day_cursor = day_cursor + datetime.timedelta(days=1)
        else:
            raise RuntimeError("Unable to plan publish times in configured per-account schedule window")

    return planned


def plan_next_publish_times(
    db,
    user: models.User,
    count: int,
    *,
    platform_code: str | None = None,
    exclude_task_ids: set[int] | None = None,
) -> list[datetime.datetime]:
    if count < 1:
        return []

    limit, start_raw, end_raw = validate_schedule_settings(
        getattr(user, "publish_limit_per_day", DEFAULT_LIMIT_PER_DAY),
        getattr(user, "publish_window_start_msk", DEFAULT_START_MSK),
        getattr(user, "publish_window_end_msk", DEFAULT_END_MSK),
    )
    start_time = parse_hhmmss(start_raw, DEFAULT_START_MSK)
    end_time = parse_hhmmss(end_raw, DEFAULT_END_MSK)

    now_utc = datetime.datetime.now(UTC).replace(microsecond=0)
    earliest_utc = now_utc + get_min_publish_lead_delta()
    earliest_msk = earliest_utc.astimezone(MSK_TZ)

    occupied_rows = db.query(models.VideoTask).filter(
        models.VideoTask.user_id == user.id,
        models.VideoTask.publish_at.isnot(None),
        models.VideoTask.publishing_status.in_(["scheduled", "in_progress"]),
    ).all()

    occupied: set[datetime.datetime] = set()
    excluded_ids = {int(item) for item in (exclude_task_ids or set())}
    for row in occupied_rows:
        if row.id in excluded_ids or not getattr(row, "postmypost_id", None):
            continue
        publish_at = row.publish_at
        if not publish_at:
            continue
        row_platform = (getattr(row, "target_platform", None) or getattr(row, "type", None) or "").strip().lower()
        if platform_code and row_platform and row_platform != platform_code.strip().lower():
            continue
        publish_utc = publish_at.replace(tzinfo=UTC) if publish_at.tzinfo is None else publish_at.astimezone(UTC)
        occupied.add(publish_utc.replace(tzinfo=None, microsecond=0))

    planned: list[datetime.datetime] = []
    reserved = set(occupied)
    day_cursor = earliest_msk.date()

    for _ in range(0, 370):
        slots_msk = _build_daily_slots(
            day_msk=day_cursor,
            limit_per_day=limit,
            start_msk=start_time,
            end_msk=end_time,
        )
        for slot_msk in slots_msk:
            if slot_msk <= earliest_msk:
                continue
            slot_utc_naive = _to_utc_naive(slot_msk)
            if slot_utc_naive in reserved:
                continue
            reserved.add(slot_utc_naive)
            planned.append(slot_utc_naive)
            if len(planned) >= count:
                return planned
        day_cursor = day_cursor + datetime.timedelta(days=1)

    raise RuntimeError("Unable to plan publish times in configured schedule window")
