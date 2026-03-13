from app.providers.base import EmbeddingProvider


class VoyageEmbeddingProvider(EmbeddingProvider):
    """Voyage AI embedding provider (voyage-code-3).

    Free tier: 200M tokens/month.
    Docs: https://docs.voyageai.com/
    """

    def __init__(self, api_key: str, model: str = "voyage-code-3") -> None:
        self._api_key = api_key
        self._model = model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError("Voyage embed() will be implemented in Phase 3")

    @property
    def dimensions(self) -> int:
        return 1024

    @property
    def provider_name(self) -> str:
        return "voyage"
