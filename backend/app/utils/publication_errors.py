import re
from typing import Iterable

from ..integrations.postmypost_errors import PostMyPostApiError


def _compact_text(value: str | None, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def format_missing_project_accounts_error(account_ids: Iterable[int], project_id: int) -> str:
    ids = [str(int(account_id)) for account_id in account_ids if account_id is not None]
    accounts = ", ".join(ids) if ids else "неизвестный аккаунт"
    return (
        f"PostMyPost: аккаунт {accounts} не подключен к проекту {project_id}. "
        "Подключи его в PostMyPost или выключи этот канал в настройках Turan."
    )


def format_publication_sync_error(error: Exception, account_ids: Iterable[int] | None = None) -> str:
    ids = [str(int(account_id)) for account_id in (account_ids or []) if account_id is not None]
    account_text = f" аккаунт {', '.join(ids)}:" if ids else ":"

    if isinstance(error, PostMyPostApiError):
        details = _compact_text(str(error), 260)
        response_text = _compact_text(getattr(error, "response_text", ""), 260)
        source = f"{details} {response_text}".lower()
        if "не подключ" in source and "проект" in source:
            return (
                f"PostMyPost отклонил{account_text} аккаунт не подключен к текущему проекту. "
                "Подключи его в PostMyPost или выключи канал в Turan."
            )
        return f"PostMyPost отклонил{account_text} {details}"

    details = _compact_text(str(error), 260)
    if details.startswith("PostMyPost:"):
        return f"{details} Аккаунт: {', '.join(ids)}." if ids else details
    return f"Не удалось синхронизировать публикацию{account_text} {details}"


def set_publication_error(task, error_text: str) -> None:
    meta = dict(getattr(task, "script_meta", None) or {})
    publication_meta = dict(meta.get("publication") or {})
    publication_meta["error"] = _compact_text(error_text, 500)
    meta["publication"] = publication_meta
    task.script_meta = meta


def clear_publication_error(task) -> None:
    meta = dict(getattr(task, "script_meta", None) or {})
    publication_meta = dict(meta.get("publication") or {})
    if "error" not in publication_meta:
        return
    publication_meta.pop("error", None)
    if publication_meta:
        meta["publication"] = publication_meta
    else:
        meta.pop("publication", None)
    task.script_meta = meta


def get_publication_error(task) -> str:
    try:
        publication_meta = dict((getattr(task, "script_meta", None) or {}).get("publication") or {})
    except Exception:
        return ""
    return _compact_text(publication_meta.get("error"), 180)
