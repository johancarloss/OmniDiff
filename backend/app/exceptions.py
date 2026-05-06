class AppError(Exception):
    """Base application error."""

    def __init__(self, message: str, status_code: int = 500) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class NotFoundError(AppError):
    """Resource not found."""

    def __init__(self, resource: str, identifier: str | int) -> None:
        super().__init__(
            message=f"{resource} not found: {identifier}",
            status_code=404,
        )


class ProviderError(AppError):
    """AI provider error (embedding or LLM)."""

    def __init__(self, provider: str, message: str) -> None:
        self.provider = provider
        super().__init__(
            message=f"Provider '{provider}' error: {message}",
            status_code=502,
        )


class IngestError(AppError):
    """Failure during repository ingestion (parse error, lock contention, etc)."""

    def __init__(self, message: str, status_code: int = 500) -> None:
        super().__init__(message=message, status_code=status_code)
