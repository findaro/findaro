from __future__ import annotations

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: object | None = None):
        self.status, self.code, self.message, self.details = status, code, message, details


def _body(code: str, message: str, details: object | None = None) -> dict:
    err: dict = {"code": code, "message": message}
    if details is not None:
        err["details"] = details
    return {"error": err}


async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    headers = {"Retry-After": "1"} if exc.status == 429 else None
    return JSONResponse(_body(exc.code, exc.message, exc.details), status_code=exc.status, headers=headers)


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    details = [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()]
    return JSONResponse(_body("invalid_request", "request validation failed", details), status_code=422)
