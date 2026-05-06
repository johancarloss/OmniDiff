from app.config import Settings
from app.providers.base import EmbeddingProvider, LLMProvider
from app.providers.gemini import GeminiEmbeddingProvider, GeminiLLMProvider
from app.providers.groq import GroqLLMProvider
from app.providers.voyage import VoyageEmbeddingProvider

_EMBEDDING_PROVIDERS: dict[str, type[EmbeddingProvider]] = {
    "voyage": VoyageEmbeddingProvider,
    "gemini": GeminiEmbeddingProvider,
}

_LLM_PROVIDERS: dict[str, type[LLMProvider]] = {
    "gemini": GeminiLLMProvider,
    "groq": GroqLLMProvider,
}

_API_KEY_MAP: dict[str, str] = {
    "voyage": "voyage_api_key",
    "gemini": "gemini_api_key",
    "groq": "groq_api_key",
}


def _resolve_api_key(settings: Settings, provider_name: str) -> str:
    """Resolve API key for a provider, raising if empty."""
    attr_name = _API_KEY_MAP.get(provider_name)
    if attr_name is None:
        raise ValueError(f"No API key mapping for provider: '{provider_name}'")

    api_key: str = getattr(settings, attr_name)
    if not api_key:
        raise ValueError(
            f"API key '{attr_name}' is empty. Set {attr_name.upper()} in your .env file."
        )
    return api_key


def create_embedding_provider(settings: Settings) -> EmbeddingProvider:
    """Create an embedding provider based on settings."""
    provider_name = settings.embedding_provider
    provider_class = _EMBEDDING_PROVIDERS.get(provider_name)
    if provider_class is None:
        supported = ", ".join(_EMBEDDING_PROVIDERS.keys())
        raise ValueError(f"Unknown embedding provider: '{provider_name}'. Supported: {supported}")

    api_key = _resolve_api_key(settings, provider_name)
    return provider_class(api_key=api_key, model=settings.embedding_model)


def create_llm_provider(settings: Settings, *, batch: bool = False) -> LLMProvider:
    """Create an LLM provider based on settings.

    Args:
        settings: Application settings.
        batch: If True, use the batch provider (for NL descriptions).
               If False, use the interactive provider (for RAG).
    """
    provider_name = settings.llm_batch_provider if batch else settings.llm_provider
    model = settings.llm_batch_model if batch else settings.llm_model

    provider_class = _LLM_PROVIDERS.get(provider_name)
    if provider_class is None:
        supported = ", ".join(_LLM_PROVIDERS.keys())
        raise ValueError(f"Unknown LLM provider: '{provider_name}'. Supported: {supported}")

    api_key = _resolve_api_key(settings, provider_name)
    return provider_class(api_key=api_key, model=model)
