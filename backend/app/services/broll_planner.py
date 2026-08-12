from dataclasses import asdict, dataclass
import random
from typing import Literal


@dataclass(frozen=True)
class BrollCandidate:
    asset_id: int
    path: str
    duration: float


@dataclass(frozen=True)
class TimelineSegment:
    kind: Literal["main", "broll"]
    start: float
    duration: float
    asset_id: int | None = None
    path: str | None = None
    source_start: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


def build_broll_plan(
    *,
    main_duration: float,
    candidates: list[BrollCandidate],
    seed: int,
    gap_min: float = 3.0,
    gap_max: float = 5.0,
    insert_min: float = 2.0,
    insert_max: float = 4.0,
) -> list[TimelineSegment]:
    safe_main_duration = max(0.0, float(main_duration))
    if safe_main_duration <= 0 or not candidates:
        return [TimelineSegment("main", 0.0, safe_main_duration)] if safe_main_duration else []

    rng = random.Random(seed)
    eligible = [
        item
        for item in sorted(candidates, key=lambda candidate: candidate.asset_id)
        if item.duration >= insert_min
    ]
    segments: list[TimelineSegment] = []
    used_asset_ids: set[int] = set()
    cursor = 0.0

    while cursor < safe_main_duration:
        gap = rng.uniform(gap_min, gap_max)
        insertion_start = cursor + gap
        if insertion_start >= safe_main_duration or safe_main_duration - insertion_start < insert_min:
            break

        segments.append(TimelineSegment("main", cursor, gap))
        available = [item for item in eligible if item.asset_id not in used_asset_ids]
        if not available:
            cursor = insertion_start
            break

        candidate = rng.choice(available)
        max_duration = min(insert_max, candidate.duration, safe_main_duration - insertion_start)
        if max_duration < insert_min:
            used_asset_ids.add(candidate.asset_id)
            cursor = insertion_start
            continue

        insert_duration = rng.uniform(insert_min, max_duration)
        source_max_start = max(0.0, candidate.duration - insert_duration)
        source_start = rng.uniform(0.0, source_max_start) if source_max_start else 0.0
        segments.append(
            TimelineSegment(
                "broll",
                insertion_start,
                insert_duration,
                asset_id=candidate.asset_id,
                path=candidate.path,
                source_start=source_start,
            )
        )
        used_asset_ids.add(candidate.asset_id)
        cursor = insertion_start + insert_duration

    if cursor < safe_main_duration:
        segments.append(TimelineSegment("main", cursor, safe_main_duration - cursor))
    return [segment for segment in segments if segment.duration > 0.001]
