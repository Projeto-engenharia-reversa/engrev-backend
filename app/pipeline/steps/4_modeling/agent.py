import asyncio
import logging

from pydantic import ValidationError

from app.core.config import settings
from app.core.exceptions import AppError
from app.helpers.llm.prompts import build_data_modeling_messages
from app.helpers.llm.provider import LLMMessage, get_llm_provider
from app.helpers.llm.tokens import estimate_tokens
from app.pipeline.types import AnalysisContext, ConceptualModel, extract_json

from .consenso import consolidar
from .reconcile import reconcile

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 2


async def model(ctx: AnalysisContext) -> AnalysisContext:
    provider = get_llm_provider()
    messages, budget_warnings = build_data_modeling_messages(ctx.project_name, ctx.structural)

    # Rede de segurança: a seleção de evidência já aplica o próprio orçamento.
    prompt_tokens_estimate = sum(estimate_tokens(m.content) for m in messages)
    if prompt_tokens_estimate > settings.TOKEN_BUDGET:
        raise AppError(
            "O prompt de modelagem excede o orçamento de tokens mesmo após os cortes "
            "por seção (mapa/evidência), considere reduzir TOKEN_BUDGET/EVIDENCE_BUDGET "
            "ou o escopo do projeto analisado.",
            "token_budget",
        )

    # Auto-consistência: N amostras consolidadas por maioria. Em paralelo porque
    # esta etapa domina o tempo da análise e as N chamadas são independentes.
    n_amostras = max(1, settings.AMOSTRAS_MODELAGEM)
    if n_amostras == 1:
        amostras = [await _uma_amostra(provider, messages, ctx)]
    else:
        amostras = await _amostrar_em_paralelo_com_recuo(provider, messages, ctx, n_amostras)
    ctx.amostras_de_modelagem = amostras
    ctx.conceptual = consolidar(amostras)
    # A modelagem substitui o que a etapa estrutural apurou; a reconciliação devolve.
    reconcile_issues = reconcile(ctx.structural, ctx.conceptual)
    ctx.conceptual.issues = [*ctx.conceptual.issues, *reconcile_issues, *budget_warnings]
    return ctx


async def _amostrar_em_paralelo_com_recuo(
    provider, messages: list[LLMMessage], ctx: AnalysisContext, n: int
) -> list[ConceptualModel]:
    """N amostras em paralelo; em série se a rajada for recusada.

    Prompt grande com várias requisições simultâneas pode voltar 503 enquanto uma
    sozinha passa. Recuar para série se autocorrige sem depender de um limiar por
    tamanho, que varia com o provedor e com o modelo.
    """
    try:
        return list(await asyncio.gather(*(_uma_amostra(provider, messages, ctx) for _ in range(n))))
    except AppError as exc:
        if exc.code != "llm_unavailable":
            raise
        logger.warning(
            "as %s amostras em paralelo foram recusadas (%s); refazendo em série",
            n, exc.code,
        )
    # Do zero: não dá para saber quais da rajada chegaram a completar.
    return [await _uma_amostra(provider, messages, ctx) for _ in range(n)]


async def _uma_amostra(provider, messages: list[LLMMessage], ctx: AnalysisContext) -> ConceptualModel:
    """Uma resposta válida do modelo, com o retry de JSON malformado por amostra."""
    last_error: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        # Nos modelos com raciocínio a saída é dividida entre pensamento e texto,
        # então um limite justo arrisca truncar o JSON.
        response = await provider.complete(messages, max_output_tokens=settings.MAX_OUTPUT_TOKENS)
        ctx.registrar_uso("modeling", settings.LLM_MODEL, response.input_tokens, response.output_tokens)
        if response.finish_reason == "MAX_TOKENS":
            # Sem isto a truncagem chegaria como JSON malformado e o retry gastaria
            # outra requisição para falhar pela causa errada.
            raise AppError(
                f"A resposta do modelo foi cortada em {response.output_tokens} tokens de saída "
                f"(MAX_OUTPUT_TOKENS={settings.MAX_OUTPUT_TOKENS}). O JSON veio incompleto. "
                f"O limite é do modelo, não da aplicação: confira o `outputTokenLimit` "
                f"de {settings.LLM_MODEL} antes de subir MAX_OUTPUT_TOKENS, e se já "
                f"estiver no teto, o caminho é reduzir o escopo analisado.",
                "llm_output_truncated",
            )
        try:
            return ConceptualModel.model_validate(extract_json(response.content))
        except (AppError, ValidationError) as exc:
            last_error = exc
            if attempt + 1 >= _MAX_ATTEMPTS:
                break
            # Reenvia pedindo correção em vez de derrubar a run inteira por um JSON malformado.
            messages = [
                *messages,
                LLMMessage(role="assistant", content=response.content),
                LLMMessage(
                    role="user",
                    content=(
                        "A resposta anterior não é um JSON válido conforme o schema pedido "
                        f"(erro: {exc}). Responda novamente APENAS com o JSON, sem markdown."
                    ),
                ),
            ]

    raise AppError(
        f"Resposta do modelo inválida após {_MAX_ATTEMPTS} tentativas: {last_error}",
        "llm_invalid_response",
    )
