from app.providers.base import LLMProvider


class GroqLLMProvider(LLMProvider):
    """Groq LLM provider (LLaMA via Groq Cloud).

    Free tier: 14.4K requests/day.
    Docs: https://console.groq.com/docs
    """

    async def generate(self, prompt: str, *, max_tokens: int = 1024) -> str:
        raise NotImplementedError("Groq generate() will be implemented in Phase 3")

    async def generate_with_context(
        self,
        query: str,
        context: list[str],
        *,
        max_tokens: int = 2048,
    ) -> str:
        raise NotImplementedError("Groq generate_with_context() will be implemented in Phase 3")

    @property
    def provider_name(self) -> str:
        return "groq"
