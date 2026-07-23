import os
from typing import Any


def resolve_user_postmypost_project_id(user: Any, pmp_client: Any) -> int:
    user_project_id = getattr(user, "postmypost_project_id", None)
    if user_project_id:
        return int(user_project_id)

    project_id_raw = os.getenv("POSTMYPOST_PROJECT_ID", "").strip()
    project_id = int(project_id_raw) if project_id_raw else None
    return pmp_client.ensure_project_id(project_id)


def resolve_task_postmypost_project_id(task: Any, user: Any, pmp_client: Any) -> int:
    task_project_id = getattr(task, "postmypost_project_id", None)
    if task_project_id:
        return int(task_project_id)
    return resolve_user_postmypost_project_id(user, pmp_client)


def ensure_postmypost_project_available(project_id: int, pmp_client: Any) -> int:
    projects = pmp_client.get_projects()
    available_ids = {
        int(project["id"])
        for project in projects
        if isinstance(project, dict) and project.get("id") is not None
    }
    if int(project_id) not in available_ids:
        raise ValueError("PostMyPost project is not available for this API key")
    return int(project_id)


def normalize_postmypost_project(raw_project: dict[str, Any], selected_project_id: int | None) -> dict[str, Any]:
    project_id = int(raw_project["id"])
    return {
        "id": project_id,
        "name": str(raw_project.get("name") or f"Project {project_id}"),
        "timezone_id": raw_project.get("timezone_id"),
        "selected": bool(selected_project_id and project_id == int(selected_project_id)),
    }
