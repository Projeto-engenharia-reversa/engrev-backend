from abc import ABC, abstractmethod

from pydantic import BaseModel


class LLMMessage(BaseModel):
    role: str
    content: str


class LLMResponse(BaseModel):
    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    # Motivo de parada do provedor. "MAX_TOKENS" com texto parcial e o caso
    # perigoso: sem isso a truncagem chega ao agente como JSON malformado.
    finish_reason: str = ""


class LLMProvider(ABC):
    @abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        max_output_tokens: int = 8192,
        model: str | None = None,
    ) -> LLMResponse:
        """`model=None` usa `settings.LLM_MODEL`. Cada agente pode pedir um modelo
        diferente do mesmo provedor (ex.: 5_validation usa o modelo leve)."""
        ...

    @abstractmethod
    async def count_tokens(self, text: str) -> int:
        ...


def get_llm_provider() -> LLMProvider:
    from app.core.config import settings
    from app.helpers.llm.providers import create_provider

    return create_provider(settings.LLM_PROVIDER)
