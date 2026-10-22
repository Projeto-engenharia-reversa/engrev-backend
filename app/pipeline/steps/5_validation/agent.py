import json

from app.core.config import settings
from app.helpers.llm.prompts import build_validation_messages
from app.helpers.llm.provider import get_llm_provider
from app.pipeline.types import AnalysisContext, ValidationIssue, extract_json


async def review(ctx: AnalysisContext, issues: list[ValidationIssue]) -> list[ValidationIssue]:
    provider = get_llm_provider()
    messages = build_validation_messages(
        ctx.conceptual.model_dump_json(),
        json.dumps([i.model_dump() for i in issues]),
    )
    # Modelo leve: a revisão é aditiva (ver _merge_issues) e roda com muito mais
    # folga de cota diária do que o modelo usado na modelagem.
    response = await provider.complete(
        messages, max_output_tokens=settings.MAX_OUTPUT_TOKENS_LIGHT, model=settings.LLM_MODEL_LIGHT
    )
    # Registrar antes do parse: o consumo aconteceu mesmo que a resposta venha
    # malformada e a gente caia no fallback abaixo — cota gasta é cota gasta.
    ctx.registrar_uso(
        "validation", settings.LLM_MODEL_LIGHT, response.input_tokens, response.output_tokens
    )
    try:
        payload = extract_json(response.content)
        llm_issues = [ValidationIssue.model_validate(item) for item in payload.get("issues", [])]
    except Exception:  # noqa: BLE001 - fallback: mantém issues locais se a saída for malformada
        return issues
    return _merge_issues(issues, llm_issues)


def _merge_issues(
    deterministic: list[ValidationIssue], llm: list[ValidationIssue]
) -> list[ValidationIssue]:
    """Combina as issues determinísticas com a revisão do LLM sem descartar nenhuma.

    Chave de dedupe inclui a mensagem (não só source/severity) porque as regras
    determinísticas frequentemente emitem múltiplas issues distintas para a mesma
    tabela e mesma severidade (ex.: "sem chave primária" e "coluna duplicada" no
    mesmo `source="error"`) — uma chave mais curta colapsaria issues reais entre si.
    O LLM pode complementar com issues novas, mas nunca apagar uma determinística
    que ele deixou de citar de volta.
    """
    merged: dict[tuple[str | None, str, str], ValidationIssue] = {
        (issue.source, issue.severity, issue.message): issue for issue in deterministic
    }
    for issue in llm:
        merged[(issue.source, issue.severity, issue.message)] = issue
    return list(merged.values())
