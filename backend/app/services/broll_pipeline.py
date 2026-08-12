import logging
import os

from sqlalchemy.orm import Session

from .. import models
from .broll_planner import BrollCandidate, build_broll_plan
from .broll_renderer import BrollRenderer

logger = logging.getLogger(__name__)


def apply_project_broll(
    db: Session,
    *,
    user_id: int,
    project_id: int | None,
    input_path: str,
    output_path: str,
    seed: int,
    timeout_seconds: int | None = None,
) -> tuple[str, dict]:
    if project_id is None:
        return input_path, {"status": "skipped", "reason": "project_id_missing"}

    assets = (
        db.query(models.BrollAsset)
        .filter(
            models.BrollAsset.user_id == user_id,
            models.BrollAsset.postmypost_project_id == int(project_id),
            models.BrollAsset.is_active.is_(True),
        )
        .order_by(models.BrollAsset.id.asc())
        .all()
    )
    if not assets:
        return input_path, {"status": "skipped", "reason": "library_empty", "available_assets": 0}

    renderer = BrollRenderer()
    source_probe = renderer.probe(input_path)
    main_duration = float(source_probe.get("format", {}).get("duration") or 0.0)
    candidates: list[BrollCandidate] = []
    skipped_assets: list[int] = []
    for asset in assets:
        if not asset.file_path or not os.path.isfile(asset.file_path):
            skipped_assets.append(asset.id)
            continue
        try:
            probe = renderer.probe(asset.file_path)
            duration = float(probe.get("format", {}).get("duration") or 0.0)
        except Exception:
            skipped_assets.append(asset.id)
            continue
        candidates.append(BrollCandidate(asset.id, asset.file_path, duration))

    plan = build_broll_plan(main_duration=main_duration, candidates=candidates, seed=seed)
    broll_segments = [segment for segment in plan if segment.kind == "broll"]
    if not broll_segments:
        return input_path, {
            "status": "skipped",
            "reason": "no_feasible_insertions",
            "available_assets": len(candidates),
            "skipped_assets": skipped_assets,
        }

    logger.info(
        "Applying project B-roll: user=%s project=%s input=%s insertions=%s",
        user_id,
        project_id,
        input_path,
        len(broll_segments),
    )
    meta = renderer.render(
        input_path=input_path,
        output_path=output_path,
        plan=plan,
        timeout_seconds=timeout_seconds,
    )
    meta.update(
        {
            "project_id": int(project_id),
            "available_assets": len(candidates),
            "skipped_assets": skipped_assets,
            "inserted_asset_ids": [segment.asset_id for segment in broll_segments],
        }
    )
    return output_path, meta
