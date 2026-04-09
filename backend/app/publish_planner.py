import datetime
from zoneinfo import ZoneInfo

from . import models

MSK_TZ = ZoneInfo("Europe/Moscow")
UTC = datetime.timezone.utc

DEFAULT_LIMIT_PER_DAY = 3
DEFAULT_START_MSK = "10:00:00"
DEFAULT_END_MSK = "22:00:00"


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


def _to_utc_naive(dt_aware: datetime.datetime) -> datetime.datetime:
    return dt_aware.astimezone(UTC).replace(tzinfo=None, microsecond=0)


def _build_daily_slots(day_msk: datetime.date, limit_per_day: int, start_msk: datetime.time, end_msk: datetime.time) -> list[datetime.datetime]:
    start_dt = datetime.datetime.combine(day_msk, start_msk, tzinfo=MSK_TZ)
    end_dt = datetime.datetime.combine(day_msk, end_msk, tzinfo=MSK_TZ)
    if limit_per_day <= 1:
        return [start_dt]

    total_seconds = int((end_dt - start_dt).total_seconds())
    if total_seconds <= 0:
        return [start_dt]

    step = total_seconds / float(limit_per_day - 1)
    slots: list[datetime.datetime] = []
    for index in range(limit_per_day):
        seconds = int(round(step * index))
        slot = start_dt + datetime.timedelta(seconds=seconds)
        slots.append(slot.replace(microsecond=0))
    return slots


def plan_next_publish_times(db, user: models.User, count: int) -> list[datetime.datetime]:
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
    now_msk = now_utc.astimezone(MSK_TZ)

    occupied_rows = db.query(models.VideoTask).filter(
        models.VideoTask.user_id == user.id,
        models.VideoTask.publish_at.isnot(None),
        models.VideoTask.publishing_status.in_(["scheduled", "in_progress"]),
    ).all()

    occupied: set[datetime.datetime] = set()
    for row in occupied_rows:
        publish_at = row.publish_at
        if not publish_at:
            continue
        publish_utc = publish_at.replace(tzinfo=UTC) if publish_at.tzinfo is None else publish_at.astimezone(UTC)
        occupied.add(publish_utc.replace(tzinfo=None, microsecond=0))

    planned: list[datetime.datetime] = []
    reserved = set(occupied)
    day_cursor = now_msk.date()

    for _ in range(0, 370):
        slots_msk = _build_daily_slots(
            day_msk=day_cursor,
            limit_per_day=limit,
            start_msk=start_time,
            end_msk=end_time,
        )
        for slot_msk in slots_msk:
            if slot_msk <= now_msk:
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
