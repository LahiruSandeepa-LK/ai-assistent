"""Shared error taxonomy. See docs/09-api-design.md §5."""
from __future__ import annotations


class AppError(Exception):
    http_status = 500
    code = "app_error"

    def __init__(self, message: str, **ctx):
        super().__init__(message)
        self.message = message
        self.ctx = ctx


class ValidationError(AppError):
    http_status = 400
    code = "validation_error"


class AuthzError(AppError):
    http_status = 403
    code = "authz_error"


class RateLimitError(AppError):
    http_status = 429
    code = "rate_limit_error"


class TokenBudgetError(AppError):
    http_status = 402
    code = "token_budget_exhausted"


class UpstreamError(AppError):
    http_status = 503
    code = "upstream_error"


class ToolTimeoutError(AppError):
    http_status = 504
    code = "tool_timeout"
