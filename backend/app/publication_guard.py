import datetime
from dataclasses import dataclass
from typing import Any


UTC = datetime.timezone.utc


class PublicationVerificationError(RuntimeError):
    """The provider accepted a publication but returned an invalid record."""


@dataclass(frozen=True)
class VerifiedPublication:
    post_at: datetime.datetime
    publication_status: Any


def _parse_utc(value: Any, field_name: str) -> datetime.datetime:
    if isinstance(value, datetime.datetime):
        parsed = value
    elif isinstance(value, str):
        raw = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.datetime.fromisoformat(raw)
        except ValueError as exc:
            raise PublicationVerificationError(
                f"PostMyPost returned invalid {field_name}: {value!r}"
            ) from exc
    else:
        raise PublicationVerificationError(
            f"PostMyPost response has no valid {field_name}"
        )

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).replace(microsecond=0)


def verify_publication_payload(
    payload: dict[str, Any],
    *,
    expected_post_at: datetime.datetime,
    now_utc: datetime.datetime,
    minimum_lead: datetime.timedelta,
    require_future: bool = True,
) -> VerifiedPublication:
    if not isinstance(payload, dict):
        raise PublicationVerificationError("PostMyPost returned a non-object publication")

    publication_status = payload.get("publication_status")
    if publication_status is None:
        publication_status = payload.get("publicationStatus")
    if publication_status is None:
        raise PublicationVerificationError(
            "PostMyPost publication has no publication_status"
        )

    actual_post_at = _parse_utc(payload.get("post_at"), "post_at")
    expected = _parse_utc(expected_post_at, "expected post_at")
    if require_future and actual_post_at <= now_utc.astimezone(UTC) + minimum_lead:
        raise PublicationVerificationError(
            f"PostMyPost returned a past or too-soon post_at: {actual_post_at.isoformat()}"
        )

    if abs((actual_post_at - expected).total_seconds()) > 5:
        raise PublicationVerificationError(
            "PostMyPost changed post_at from "
            f"{expected.isoformat()} to {actual_post_at.isoformat()}"
        )

    return VerifiedPublication(
        post_at=actual_post_at,
        publication_status=publication_status,
    )
