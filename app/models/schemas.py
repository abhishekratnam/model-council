from pydantic import BaseModel

from app.core.config import DEFAULT_OLLAMA_BASE_URL


class OllamaModelsPayload(BaseModel):
    base_url: str = DEFAULT_OLLAMA_BASE_URL
