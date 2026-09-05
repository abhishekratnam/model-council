from pydantic import BaseModel
from typing import Any, Dict, List

class ProviderSettings(BaseModel):
    enabled: bool = True
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    mode: str = "responses"
    label: str = "Custom"
    endpoint: str = ""
    auth_type: str = "bearer"
    headers: Dict[str, str] = {}
    query_params: Dict[str, str] = {}

class AskPayload(BaseModel):
    question: str
    providers: Dict[str, ProviderSettings]
    system_prompt: str = ""
    max_tokens: int = 1200
    temperature: float = 0.4
    session_id: str = ""
    memory_enabled: bool = True

class Submission(BaseModel):
    provider: str
    label: str
    model: str
    text: str

class SynthesizePayload(BaseModel):
    question: str
    moderator: str
    providers: Dict[str, ProviderSettings]
    submissions: List[Submission]
    round_id: str = ""
    max_tokens: int = 1400
    temperature: float = 0.25
    session_id: str = ""
    memory_enabled: bool = True

class OllamaModelsPayload(BaseModel):
    base_url: str = "http://127.0.0.1:11434"