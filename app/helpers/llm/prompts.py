from functools import lru_cache
from pathlib import Path

from app.core.config import settings
from app.helpers.llm.provider import LLMMessage
from app.pipeline.types import StructuralModel, ValidationIssue

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


@lru_cache
def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def build_data_modeling_messages(
    project_name: str, structural: StructuralModel
) -> tuple[list[LLMMessage], list[ValidationIssue]]:
    """Monta as mensagens do prompt de modelagem. Retorna também avisos (5.4) de
    quanto conteúdo foi cortado por orçamento em cada seção — antes esse corte
    era silencioso; agora vira `ValidationIssue` visível no resultado final."""
    from importlib import import_module

    context_builder = import_module("app.pipeline.steps.3_structural.context_builder")
    template = load_prompt("data_modeling")
    structural_json = _resumo_estrutural(structural)
    project_map, map_omitted = context_builder.build_context(project_name, structural, settings.MAP_BUDGET)
    evidence, evidence_omitted = context_builder.select_evidence(structural, settings.EVIDENCE_BUDGET)
    content = (
        template.replace("{project_map}", project_map)
        .replace("{evidence}", evidence)
        .replace("{doc_evidence}", context_builder.build_doc_context(structural))
        .replace("{structural_json}", structural_json)
    )
    messages = [
        LLMMessage(role="system", content=load_prompt("system")),
        LLMMessage(role="user", content=content),
    ]
    return messages, _budget_warnings(map_omitted, evidence_omitted)


def _resumo_estrutural(structural) -> str:
    """O modelo apurado pela Fase 3, sem o que já viaja por outro canal do prompt.

    `raw_evidence` sai daqui porque `context_builder.select_evidence` já entrega
    o mesmo conteúdo — e o entrega **do jeito certo**: por último, como o nível
    de confiança mais baixo, e sujeito a orçamento. Esta cópia não tinha teto, o
    que anulava a priorização inteira: a evidência mais fraca do sistema era a
    única que sempre entrava, e entrava completa. No spring-petclinic eram 92.178
    dos 105.203 tokens desta seção — 87% de duplicata.

    `edges` e `unmapped_files` também saem: o mapa (`build_context`) já os resume,
    e em forma legível. E `queries` sem tabela identificada não dizem nada sobre o
    modelo de dados.
    """
    return structural.model_dump_json(
        exclude={
            "tables": {"__all__": {"evidence"}},
            "queries": {"__all__": {"evidence"}},
            "raw_evidence": True,
            "edges": True,
            "unmapped_files": True,
        }
    )


def _budget_warnings(map_omitted: dict[str, int], evidence_omitted: int) -> list[ValidationIssue]:
    warnings: list[ValidationIssue] = []
    if evidence_omitted:
        warnings.append(
            ValidationIssue(
                severity="warning",
                message=(
                    f"{evidence_omitted} trecho(s) de evidência de código não couberam no "
                    "orçamento de tokens e foram omitidos — o modelo pode estar incompleto "
                    "pra essas tabelas/consultas."
                ),
                source="token_budget",
            )
        )
    for section, count in map_omitted.items():
        if not count:
            continue
        warnings.append(
            ValidationIssue(
                severity="warning",
                message=(
                    f"{count} item(ns) da seção '{section}' do mapa do projeto foram omitidos "
                    "por orçamento de tokens."
                ),
                source="token_budget",
            )
        )
    return warnings


def build_validation_messages(model_json: str, issues_json: str) -> list[LLMMessage]:
    template = load_prompt("validation")
    content = template.replace("{model_json}", model_json).replace("{issues_json}", issues_json)
    return [
        LLMMessage(role="system", content=load_prompt("system")),
        LLMMessage(role="user", content=content),
    ]
