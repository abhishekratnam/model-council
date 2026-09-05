import re
from typing import Any
from app.core.exceptions import CouncilError

def trim_text(value: Any, *, field: str, limit: int, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise CouncilError(f"{field} must be text.")
    result = value.strip()
    if required and not result:
        raise CouncilError(f"{field} is required.")
    if len(result) > limit:
        raise CouncilError(f"{field} must be {limit:,} characters or fewer.")
    return result

def bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise CouncilError("Response length must be a whole number.") from error
    return max(minimum, min(maximum, parsed))

def bounded_float(value: Any, *, default: float, minimum: float, maximum: float) -> float:
    if value is None or value == "":
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise CouncilError("Creativity must be a number.") from error
    return max(minimum, min(maximum, parsed))

def truncate(value: str, limit: int) -> tuple[str, bool]:
    if len(value) <= limit:
        return value, False
    return value[:limit].rstrip() + "\n\n[Truncated by Model Council]", True

def validate_session_id(value: Any) -> str:
    if value is None or value == "":
        return ""
    if not isinstance(value, str):
        raise CouncilError("Session ID must be text.")
    cleaned = value.strip()
    if len(cleaned) > 128 or not re.match(r"^[a-zA-Z0-9_\-]+$", cleaned):
        raise CouncilError(
            "Session ID must be 1–128 alphanumeric characters, hyphens, or underscores."
        )
    return cleaned