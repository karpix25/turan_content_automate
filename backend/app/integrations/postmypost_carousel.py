import datetime
from typing import Any


def build_carousel_payload(
    project_id: int,
    account_ids: list[int],
    post_at: datetime.datetime,
    file_ids: list[int],
    content: str,
) -> dict[str, Any]:
    normalized_accounts = sorted({int(account_id) for account_id in account_ids})
    normalized_files = [int(file_id) for file_id in file_ids]
    if not normalized_accounts or not normalized_files:
        raise ValueError("Для карусели нужны аккаунты и изображения")
    aware_post_at = post_at if post_at.tzinfo else post_at.replace(tzinfo=datetime.timezone.utc)
    post_at_iso = aware_post_at.astimezone(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "project_id": int(project_id),
        "post_at": post_at_iso,
        "account_ids": normalized_accounts,
        "publication_status": 5,
        "details": [
            {
                "account_id": account_id,
                # PostMyPost API принимает несколько file_ids в обычном POST.
                "publication_type": 1,
                "file_ids": normalized_files,
                "content": (content or "").strip(),
            }
            for account_id in normalized_accounts
        ],
    }


def create_carousel_publication(client, **kwargs: Any) -> dict[str, Any]:
    payload = build_carousel_payload(**kwargs)
    response = client._request("POST", "/publications", json=payload)
    return client._unwrap_data(response)
