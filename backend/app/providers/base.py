from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    """Abstract base for embedding providers."""

    def __init__(self, *, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a batch of texts."""

    async def embed_single(self, text: str) -> list[float]:
        """Generate embedding for a single text. Defaults to batch of 1."""
        results = await self.embed([text])
        return results[0]

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Return the embedding dimensions."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider name."""


class LLMProvider(ABC):
    """Abstract base for LLM providers."""

    def __init__(self, *, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    @abstractmethod
    async def generate(self, prompt: str, *, max_tokens: int = 1024) -> str:
        """Generate a response from a prompt."""

    @abstractmethod
    async def generate_with_context(
        self,
        query: str,
        context: list[str],
        *,
        max_tokens: int = 2048,
    ) -> str:
        """Generate a response using retrieved context (RAG)."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider name."""
