"""Normalized view of a failed API call; carries no credentials."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ApiFailure:
    kind: str                      # network, timeout, invalid_json, unauthorized,
                                   # rate_limited, server, api
    code: str | None = None        # stable error.code from the API
    message: str | None = None     # error.message, only a fallback text
    retry_after: int | None = None
    status: int = 0
    license: dict | None = None    # raw "licenca" of an error body
    server_now: str | None = None

    @classmethod
    def from_result(cls, result):
        if result.error in {"network", "timeout", "invalid_json"}:
            kind = result.error
        elif result.status == 401:
            kind = "unauthorized"
        elif result.status == 429:
            kind = "rate_limited"
        elif result.status >= 500 or not result.status:
            kind = "server"
        else:
            kind = "api"
        return cls(kind, result.error_code, result.error_message, result.retry_after,
                   result.status, result.error_license, result.server_now)

    @property
    def unreachable(self):
        """API could not be reached or is down without a contract error code."""
        return self.kind in {"network", "timeout"} or (self.kind == "server" and not self.code)


def failure_kind(result):
    return ApiFailure.from_result(result).kind
