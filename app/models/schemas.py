from pydantic import BaseModel

from app.core.config import DEFAULT_OLLAMA_BASE_URL, DEFAULT_EXO_BASE_URL


class OllamaModelsPayload(BaseModel):
    base_url: str = DEFAULT_OLLAMA_BASE_URL


class ExoModelsPayload(BaseModel):
    base_url: str = DEFAULT_EXO_BASE_URL


class OpenRouterModelsPayload(BaseModel):
    api_key: str


class GeminiModelsPayload(BaseModel):
    api_key: str
