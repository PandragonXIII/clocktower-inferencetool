"""Protocol-level error type shared by the backend.

An :class:`ApiError` represents an HTTP error response as defined by
``web/protocol/types.ts`` (``ErrorResponse``): a status code, a machine-readable
``code``, a human-readable ``message`` and a JSON Pointer ``path`` locating the
offending position in the request JSON.

Logical unsatisfiability (``consistency = "unsat"``) is *not* an error and must
never be reported through this exception.
"""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    """An HTTP error carrying a protocol error code and JSON Pointer path."""

    def __init__(self, status: int, code: str, message: str, path: str = ""):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.path = path

    def to_dict(self) -> dict[str, Any]:
        """Return the ``error`` object (without the surrounding envelope)."""
        return {"code": self.code, "message": self.message, "path": self.path}

    def to_response(self, api_version: str = "1.0", request_id: str | None = None) -> dict[str, Any]:
        """Return a full ``ErrorResponse`` envelope."""
        response: dict[str, Any] = {"api_version": api_version}
        if request_id is not None:
            response["request_id"] = request_id
        response["error"] = self.to_dict()
        return response

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ApiError(status={self.status!r}, code={self.code!r}, message={self.message!r}, path={self.path!r})"
