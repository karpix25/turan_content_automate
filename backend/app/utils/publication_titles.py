import re
from collections.abc import Mapping, Sequence

from .. import models
from .platform_utils import _normalize_platform_code

TITLE_REQUIRED_PLATFORMS = {
    "youtube",
    "vk",
    "dzen",
    "rutube",
    "reddit",
    "medium",
    "pinterest",
    "odnoklassniki",
}
TITLE_REQUIRED_TASK_TYPES = {"avatar_instagram_post_5s"}
DEFAULT_PUBLICATION_TITLE = "Видео"
MAX_PUBLICATION_TITLE_LENGTH = 100


def _clean_publication_title(value: str | None) -> str:
    title = re.sub(r"\s+", " ", (value or "").strip())
    title = title.strip("\"'«»“”")
    title = re.sub(r"[#@]\S+", "", title).strip()
    title = re.sub(r"\s+", " ", title)
    if len(title) > MAX_PUBLICATION_TITLE_LENGTH:
        title = title[:MAX_PUBLICATION_TITLE_LENGTH].rsplit(" ", 1)[0].strip()
    return title or DEFAULT_PUBLICATION_TITLE


def platform_requires_title(platform: str | None) -> bool:
    return _normalize_platform_code(platform) in TITLE_REQUIRED_PLATFORMS


def task_requires_publication_title(task: models.VideoTask) -> bool:
    return (getattr(task, "type", None) or "") in TITLE_REQUIRED_TASK_TYPES


def build_publication_titles_by_account(
    *,
    task: models.VideoTask,
    account_ids: Sequence[int],
    account_platform_map: Mapping[int, str],
) -> dict[int, str]:
    title = _clean_publication_title(getattr(task, "source_title", None))
    target_platform = getattr(task, "target_platform", None)
    target_requires_title = platform_requires_title(target_platform)
    task_requires_title = task_requires_publication_title(task)

    result: dict[int, str] = {}
    for account_id in account_ids:
        account_platform = account_platform_map.get(int(account_id))
        if task_requires_title or target_requires_title or platform_requires_title(account_platform):
            result[int(account_id)] = title
    return result
