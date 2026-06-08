import httpx
from typing import Any


class PostMyPostApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        method: str,
        path: str,
        response_text: str,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.method = method
        self.path = path
        self.response_text = response_text


def summarize_error_response(response: httpx.Response) -> str:
    try:
        payload: Any = response.json()
    except ValueError:
        return response.text.strip()[:700] or "пустой ответ API"

    if not isinstance(payload, dict):
        return str(payload)[:700]

    parts: list[str] = []
    for key in ("message", "error", "description", "detail", "name", "code"):
        value = payload.get(key)
        if value not in (None, ""):
            parts.append(str(value))
    return ". ".join(parts)[:700] or str(payload)[:700]


def format_postmypost_api_error(response: httpx.Response, *, method: str, path: str) -> PostMyPostApiError:
    details = summarize_error_response(response)
    response_text = response.text.strip()[:1000]

    if "Срок действия вашего тарифа истёк" in details:
        message = (
            "PostMyPost: срок действия тарифа истёк. "
            "Продлите тариф в PostMyPost и повторите публикацию."
        )
    elif response.status_code == 401:
        message = "PostMyPost: неверный или истекший API-ключ. Проверьте POSTMYPOST_API_KEY."
    elif response.status_code == 402:
        message = "PostMyPost: недостаточно средств или лимитов на аккаунте."
    elif response.status_code == 429:
        message = "PostMyPost: превышен лимит запросов. Попробуем повторить позже."
    else:
        message = f"PostMyPost вернул ошибку HTTP {response.status_code}: {details}"

    return PostMyPostApiError(
        message,
        status_code=response.status_code,
        method=method,
        path=path,
        response_text=response_text,
    )
