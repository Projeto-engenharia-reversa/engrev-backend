import asyncio
import json
import logging

import httpx

from app.core.config import settings
from app.core.exceptions import AppError
from app.helpers.llm.provider import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)

_JSON_START = "<<<JSON_START>>>"
_JSON_END = "<<<JSON_END>>>"


def _extract_marked_json(text: str):
    start = text.find(_JSON_START)
    end = text.find(_JSON_END)
    if start == -1 or end == -1:
        raise ValueError("Marcadores de JSON ausentes no prompt")
    return json.loads(text[start + len(_JSON_START) : end].strip())


def _mock_conceptual_model(structural: dict) -> dict:
    tables = []
    for t in structural.get("tables", []):
        columns = [
            {"name": "id", "data_type": "integer", "nullable": False, "primary_key": True, "unique": False, "fk_table": None, "fk_column": None}
        ]
        for c in t.get("columns", []):
            if c.get("primary_key"):
                continue
            columns.append(
                {
                    "name": c.get("name"),
                    "data_type": c.get("data_type", "string"),
                    "nullable": c.get("nullable", True),
                    "primary_key": False,
                    "unique": False,
                    "fk_table": None,
                    "fk_column": None,
                }
            )
        tables.append({"name": t.get("name"), "columns": columns, "source_hint": t.get("source_hint")})
    relationships = []
    seen = set()
    for r in structural.get("relationships", []):
        key = (r.get("table_a"), r.get("table_b"))
        if key in seen:
            continue
        seen.add(key)
        rel = {
            "name": r.get("name") or f"{r.get('table_a')}_{r.get('table_b')}",
            "table_a": r.get("table_a"),
            "table_b": r.get("table_b"),
            "kind": r.get("kind", "one-to-many"),
            "through": r.get("through"),
            "source_hint": r.get("source_hint"),
        }
        if rel["kind"] == "many-to-many" and not rel["through"]:
            rel["through"] = f"{rel['table_a']}_{rel['table_b']}"
            tables.append(
                {
                    "name": rel["through"],
                    "columns": [
                        {"name": "id", "data_type": "integer", "nullable": False, "primary_key": True, "unique": False, "fk_table": None, "fk_column": None}
                    ],
                    "source_hint": None,
                }
            )
        relationships.append(rel)
    return {
        "tables": tables,
        "relationships": relationships,
        "queries": structural.get("queries", []),
        "notes": ["Modelo gerado pelo provedor mock (determinístico)."],
    }


class MockProvider(LLMProvider):
    async def complete(self, messages, max_output_tokens: int = 8192, model: str | None = None) -> LLMResponse:
        await asyncio.sleep(0.1)
        user = messages[-1].content
        if _JSON_START in user:
            payload = _extract_marked_json(user)
            if isinstance(payload, list):
                content = json.dumps({"issues": payload}, ensure_ascii=False)
            else:
                content = json.dumps(_mock_conceptual_model(payload), ensure_ascii=False)
        else:
            content = json.dumps({"message": "ok"}, ensure_ascii=False)
        return LLMResponse(content=content, model="mock", input_tokens=1500, output_tokens=1000)

    async def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)


_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# O tier gratuito devolve 503 UNAVAILABLE ("high demand") de forma intermitente,
# mesmo em prompts que passam segundos depois. Sem repetir a chamada, um único
# 503 derruba a run inteira depois de todo o trabalho de parsing já feito.
_STATUS_TRANSITORIOS = {429, 500, 502, 503, 504}
_TENTATIVAS = 4
_ESPERA_INICIAL_SEGUNDOS = 2.0


async def _post_com_retry(url: str, payload: dict, headers: dict, model: str) -> httpx.Response:
    """POST com backoff exponencial nos erros transitórios do provedor.

    **Timeout conta como transitório.** Antes só código de status era repetido, e
    uma exceção de rede subia direto — matando a run depois de todo o parsing já
    feito. Pior: `httpx.ReadTimeout` tem `str()` VAZIO, então a falha chegava ao
    usuário como "rodada 1 falhou: " e nada mais. Foi assim que a célula do grocy
    sem schema caiu na ablação, sem deixar rastro do motivo.
    """
    espera = _ESPERA_INICIAL_SEGUNDOS
    ultima: httpx.Response | None = None
    ultimo_erro: Exception | None = None
    # O prompt do grocy tem 126 mil tokens; 180 s eram apertados para um projeto
    # desse tamanho, e o teto de saída é de 32 mil tokens.
    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=30.0)) as client:
        for tentativa in range(1, _TENTATIVAS + 1):
            try:
                ultima = await client.post(url, json=payload, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                ultimo_erro = exc
                ultima = None
                logger.warning(
                    "%s falhou por %s (tentativa %s/%s); repetindo em %.0fs",
                    model, type(exc).__name__, tentativa, _TENTATIVAS, espera,
                )
            else:
                if ultima.status_code not in _STATUS_TRANSITORIOS:
                    ultima.raise_for_status()
                    return ultima
                logger.warning(
                    "%s devolveu %s (tentativa %s/%s); repetindo em %.0fs",
                    model, ultima.status_code, tentativa, _TENTATIVAS, espera,
                )
            if tentativa < _TENTATIVAS:
                await asyncio.sleep(espera)
                espera *= 2

    if ultima is not None:
        motivo = f"devolveu {ultima.status_code}"
    else:
        # O nome da classe, porque a mensagem costuma ser vazia.
        motivo = f"falhou por {type(ultimo_erro).__name__}"
    raise AppError(
        f"O provedor {motivo} em {_TENTATIVAS} tentativas para o modelo {model}. "
        "Provedores de LLM ficam indisponíveis de forma intermitente; tente de novo "
        "em alguns minutos, ou reduza o escopo do projeto se o prompt for muito grande.",
        "llm_unavailable",
    )


def _to_gemini_payload(messages, max_output_tokens: int) -> dict:
    """Traduz as mensagens do formato interno para o do Gemini.

    Duas diferenças em relação aos outros provedores: o prompt de sistema não entra
    em `contents` (vai num campo separado) e o papel do assistente se chama `model`,
    não `assistant` — isso importa no retry de `4_modeling`, que reenvia a resposta
    anterior como `assistant` para pedir a correção do JSON.
    """
    system_parts: list[dict] = []
    contents: list[dict] = []
    for message in messages:
        if message.role == "system":
            system_parts.append({"text": message.content})
            continue
        role = "model" if message.role == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": message.content}]})

    payload: dict = {
        "contents": contents,
        "generationConfig": {"maxOutputTokens": max_output_tokens},
    }
    if system_parts:
        payload["systemInstruction"] = {"parts": system_parts}
    return payload


def _extract_gemini_text(data: dict, model: str) -> str:
    """Extrai o texto da resposta, falhando com mensagem clara quando o Gemini
    devolve 200 sem conteúdo — o que acontece quando o filtro de segurança bloqueia
    ou quando o limite de saída corta antes de qualquer texto."""
    candidates = data.get("candidates") or []
    if not candidates:
        feedback = data.get("promptFeedback", {})
        raise AppError(
            f"O modelo {model} não retornou nenhuma resposta "
            f"(promptFeedback: {feedback or 'sem detalhes'}).",
            "llm_invalid_response",
        )
    candidate = candidates[0]
    parts = candidate.get("content", {}).get("parts") or []
    text = "".join(part.get("text", "") for part in parts)
    if not text:
        finish_reason = candidate.get("finishReason", "desconhecido")
        detail = ""
        if finish_reason == "MAX_TOKENS":
            # Nos modelos com raciocínio, maxOutputTokens é dividido entre os tokens
            # de pensamento e o texto final — o pensamento pode consumir todo o
            # orçamento antes de sobrar qualquer resposta.
            thoughts = data.get("usageMetadata", {}).get("thoughtsTokenCount", 0)
            detail = (
                f" O orçamento de saída acabou durante o raciocínio "
                f"({thoughts} tokens de pensamento) — aumente max_output_tokens."
            )
        raise AppError(
            f"O modelo {model} retornou uma resposta vazia "
            f"(finishReason: {finish_reason}).{detail}",
            "llm_invalid_response",
        )
    return text


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str | None):
        self.api_key = api_key or ""

    async def complete(self, messages, max_output_tokens: int = 8192, model: str | None = None) -> LLMResponse:
        if not self.api_key:
            raise AppError("API_KEY não configurada", "llm_not_configured")
        model = model or settings.LLM_MODEL
        payload = _to_gemini_payload(messages, max_output_tokens)
        # Chave no header, não na query string: evita que ela apareça em logs de URL.
        headers = {"x-goog-api-key": self.api_key}
        response = await _post_com_retry(
            f"{_GEMINI_BASE_URL}/{model}:generateContent", payload, headers, model
        )
        data = response.json()
        usage = data.get("usageMetadata", {})
        return LLMResponse(
            content=_extract_gemini_text(data, model),
            model=model,
            finish_reason=(data.get("candidates") or [{}])[0].get("finishReason", ""),
            input_tokens=usage.get("promptTokenCount", 0),
            # Soma os tokens de raciocínio: o Gemini os cobra como saída e eles
            # consomem o mesmo maxOutputTokens do texto, então ignorá-los
            # subestimaria o uso real.
            output_tokens=usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0),
        )

    async def count_tokens(self, text: str) -> int:
        # Heurística local em vez do endpoint :countTokens — cada chamada real
        # consumiria uma requisição da cota diária (20/dia no modelo pesado).
        return max(1, len(text) // 4)


def create_provider(name: str) -> LLMProvider:
    if name == "mock":
        return MockProvider()
    if name == "gemini":
        return GeminiProvider(settings.API_KEY)
    raise AppError(f"Provedor LLM desconhecido: {name}", "llm_not_configured")
