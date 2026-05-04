from app.providers.base import EmbeddingProvider, LLMProvider


class GeminiEmbeddingProvider(EmbeddingProvider):
    """Google Gemini embedding provider.

    Free tier available.
    Docs: https://ai.google.dev/
    """

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError("Gemini embed() will be implemented in Phase 3")

    @property
    def dimensions(self) -> int:
        return 768

    @property
    def provider_name(self) -> str:
        return "gemini"


class GeminiLLMProvider(LLMProvider):
    """Google Gemini LLM provider.

    Free tier or Pro plan.
    Docs: https://ai.google.dev/
    """

    async def generate(self, prompt: str, *, max_tokens: int = 1024) -> str:
        raise NotImplementedError("Gemini generate() will be implemented in Phase 3")

    async def generate_with_context(
        self,
        query: str,
        context: list[str],
        *,
        max_tokens: int = 2048,
    ) -> str:
        raise NotImplementedError("Gemini generate_with_context() will be implemented in Phase 3")

    @property
    def provider_name(self) -> str:
        return "gemini"
