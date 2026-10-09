from typing import Any


def error_body(code: str, message: str, fields: list[dict] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "fields": fields or []}}
