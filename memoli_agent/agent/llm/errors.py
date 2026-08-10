"""可安全记录的 Provider 错误分类。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from memoli_agent.agent.llm.contracts import ProviderAttempt


class ProviderError(RuntimeError):
    """所有模型 Provider 错误的基类。"""

    error_type = "provider-error"

    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        model: str = "",
        status_code: int | None = None,
        retryable: bool = False,
        attempt: int = 1,
        request_id: str = "",
        retry_after: float | None = None,
        partial_stream: bool = False,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.status_code = status_code
        self.retryable = retryable
        self.attempt = attempt
        self.request_id = request_id
        self.retry_after = retry_after
        self.partial_stream = partial_stream
        self.attempts: tuple[ProviderAttempt, ...] = ()


class AuthenticationProviderError(ProviderError):
    error_type = "provider-authentication"


class PermissionProviderError(ProviderError):
    error_type = "provider-permission"


class RateLimitProviderError(ProviderError):
    error_type = "provider-rate-limit"


class ProviderTimeoutError(ProviderError):
    error_type = "provider-timeout"


class ProviderNetworkError(ProviderError):
    error_type = "provider-network"


class ContextLengthProviderError(ProviderError):
    error_type = "provider-context-length"


class ContentSafetyProviderError(ProviderError):
    error_type = "provider-content-safety"


class InvalidRequestProviderError(ProviderError):
    error_type = "provider-invalid-request"


class ResponseProtocolError(ProviderError):
    error_type = "provider-response-protocol"


class UnsupportedCapabilityError(ProviderError):
    error_type = "unsupported-capability"
