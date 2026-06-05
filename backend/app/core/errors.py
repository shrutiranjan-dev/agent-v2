from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class PlatformError(Exception):
    status_code = 400
    code = "platform_error"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(PlatformError):
    status_code = 404
    code = "not_found"


class PermissionBlockedError(PlatformError):
    status_code = 403
    code = "permission_blocked"


class PermissionPendingError(PlatformError):
    status_code = 202
    code = "permission_pending"


class ToolExecutionError(PlatformError):
    status_code = 400
    code = "tool_execution_error"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(PlatformError)
    async def platform_error_handler(_: Request, exc: PlatformError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )

