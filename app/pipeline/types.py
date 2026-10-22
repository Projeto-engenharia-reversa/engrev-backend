import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from pydantic import BaseModel

from app.core.exceptions import AppError


class RunStatus(str, Enum):
    PENDING = "pending"
    SCAN = "scan"
    PARSE = "parse"
    STRUCTURAL = "structural"
    MODELING = "modeling"
    VALIDATION = "validation"
    ARTIFACTS = "artifacts"
    DONE = "done"
    FAILED = "failed"


# Níveis de confiança de uma tabela/relação detectada, do mais pro menos confiável.
# "ddl": DDL SQL real (CREATE/ALTER TABLE). "schema-definition": formato de schema
# estruturado (Prisma, GraphQL SDL, Protobuf...). "ast": classe/struct lida via AST
# (Python/TS/Java/C#...). "heuristic": inferência determinística sem sintaxe
# explícita (ex.: FK por convenção de nome de coluna). "weak-fallback": candidato
# fraco extraído sem parser dedicado. "raw-fallback": nenhuma extração estrutural,
# só texto bruto entregue como evidência pro LLM avaliar. "llm-inferred": proposta
# do LLM sem nenhuma contraparte na extração determinística — o nível mais fraco,
# atribuído na reconciliação (Fase 4.5), nunca na Fase 3.
CONFIDENCE_LEVELS: tuple[str, ...] = (
    "ddl",
    "schema-definition",
    "ast",
    "heuristic",
    "weak-fallback",
    "raw-fallback",
    "llm-inferred",
)
_CONFIDENCE_RANK = {level: rank for rank, level in enumerate(CONFIDENCE_LEVELS)}


def confidence_rank(value: str) -> int:
    """Menor rank = mais confiável. Valores desconhecidos vão pro fim (menos confiáveis)."""
    return _CONFIDENCE_RANK.get(value, len(CONFIDENCE_LEVELS))


class CodeLocation(BaseModel):
    path: str = ""
    line_start: int = 0
    line_end: int = 0
    symbol: str | None = None


class ColumnDef(BaseModel):
    name: str
    data_type: str = "string"
    nullable: bool = True
    primary_key: bool = False
    unique: bool = False
    fk_table: str | None = None
    fk_column: str | None = None
    line: int | None = None


class TableDef(BaseModel):
    name: str
    columns: list[ColumnDef] = []
    source_hint: str | None = None
    location: CodeLocation | None = None
    evidence: str | None = None
    confidence: str = "ast"


class RelationshipDef(BaseModel):
    name: str
    table_a: str
    table_b: str
    kind: str = "one-to-many"
    through: str | None = None
    source_hint: str | None = None
    location: CodeLocation | None = None
    confidence: str = "ast"
    fk_column: str | None = None


class QueryDef(BaseModel):
    name: str
    kind: str = "select"
    tables: list[str] = []
    source_hint: str | None = None
    location: CodeLocation | None = None
    evidence: str | None = None


class ModuleEdge(BaseModel):
    kind: str = "references"
    source: str = ""
    target: str = ""
    source_hint: str | None = None


class RawEvidence(BaseModel):
    """Texto bruto de um arquivo sem extração estrutural (Fase 4.1) — o conteúdo
    entregue como evidência de baixa confiança pro LLM avaliar diretamente. Nunca
    vira TableDef sozinho.

    `parseado_sem_entidade` separa dois casos que não valem o mesmo:

    - **False** — não existe parser para a linguagem. Ninguém olhou o arquivo.
    - **True** — existe parser, ele olhou e não achou entidade nenhuma.

    O segundo é evidência mais fraca (o parser já concluiu que ali não há modelo)
    e por isso é o primeiro a sair quando o orçamento aperta. Mas ele **precisa
    existir**: sem ele, um arquivo parseado que não produz entidade desaparecia
    por completo, e uma linguagem COM parser entregava ao LLM menos evidência que
    uma sem. Era o que zerava o django sem schema (33 arquivos, 1 vira evidência)
    enquanto o rails, sem parser nenhum, chegava a 83%.
    """

    path: str
    text: str
    confidence: str = "raw-fallback"
    parseado_sem_entidade: bool = False


class DocEvidence(BaseModel):
    """Trecho de documentação em linguagem natural (README/ARCHITECTURE/docs .md)
    com heading relevante pro modelo de dados (Fase 4.2) — canal separado do mapa
    e da evidência de código: é corroborativo, nunca gera TableDef sozinho."""

    path: str
    heading: str
    text: str


class RemovedColumn(BaseModel):
    """Coluna que uma migration tirou da tabela (`DROP COLUMN`, ou o nome antigo de
    um `RENAME COLUMN`). O fato de ter sido removida é informação sobre o código
    tão real quanto a coluna que ficou — e some se não for registrada, porque a
    Fase 3 aplica o alter direto sobre a lista de colunas.

    A reconciliação (Fase 4.5) usa isto para impedir que o LLM ressuscite a coluna
    ao ver o `CREATE TABLE` original na mesma evidência que o `DROP`.

    Para a reconciliação tanto faz se foi DROP ou RENAME — nos dois casos o nome
    antigo não pode voltar. Para o relatório faz toda diferença: dizer que uma
    coluna renomeada "foi retirada" é informação falsa, o dado continua lá com
    outro nome."""

    table: str
    column: str
    path: str = ""
    line: int = 0
    motivo: str = "drop"  # "drop" | "rename"
    renomeada_para: str | None = None


class StructuralModel(BaseModel):
    tables: list[TableDef] = []
    relationships: list[RelationshipDef] = []
    queries: list[QueryDef] = []
    modules: list[str] = []
    edges: list[ModuleEdge] = []
    unmapped_files: list[str] = []
    raw_evidence: list[RawEvidence] = []
    doc_evidence: list[DocEvidence] = []
    removed_columns: list[RemovedColumn] = []


class ValidationIssue(BaseModel):
    severity: str = "warning"
    message: str
    source: str | None = None
    suggestion: str | None = None


class ConceptualModel(BaseModel):
    tables: list[TableDef] = []
    relationships: list[RelationshipDef] = []
    queries: list[QueryDef] = []
    notes: list[str] = []
    issues: list[ValidationIssue] = []


class FileSummary(BaseModel):
    relative_path: str
    language: str = ""
    size_bytes: int = 0
    status: str = "ok"
    reason: str | None = None
    imported_symbols: list[str] = []
    exported_symbols: list[str] = []


@dataclass
class StepUsage:
    """Consumo de uma chamada de LLM, por etapa e por modelo.

    Antes só havia um par de contadores no contexto e o orquestrador gravava uma
    linha com `step="modeling"` fixo — o agente de validação (que roda no modelo
    leve) não somava em lugar nenhum, então metade do consumo era invisível e o
    `total_tokens` da run ficava abaixo do real."""

    step: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class AnalysisContext:
    run_id: int
    project_id: int
    project_name: str
    root_path: Path
    summaries: list[FileSummary] = field(default_factory=list)
    structural: StructuralModel = field(default_factory=StructuralModel)
    conceptual: ConceptualModel = field(default_factory=ConceptualModel)
    usages: list[StepUsage] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)
    # As amostras da modelagem ANTES de consolidadas. Só a avaliação usa: permite
    # consolidar o mesmo conjunto por políticas diferentes e comparar, sem
    # nenhuma chamada a mais ao LLM. A pipeline em si nunca lê isto.
    amostras_de_modelagem: list[ConceptualModel] = field(default_factory=list)

    def registrar_uso(self, step: str, model: str, entrada: int, saida: int) -> None:
        self.usages.append(
            StepUsage(step=step, model=model, input_tokens=entrada, output_tokens=saida)
        )

    @property
    def prompt_tokens(self) -> int:
        return sum(u.input_tokens for u in self.usages)

    @property
    def completion_tokens(self) -> int:
        return sum(u.output_tokens for u in self.usages)


def extract_json(content: str) -> dict:
    """Localiza e decodifica o primeiro objeto JSON válido dentro de `content`.

    Usa `raw_decode` (em vez de `find('{')`/`rfind('}')`) para não se confundir
    com chaves que aparecem dentro de strings de evidência ou texto após o
    JSON — tenta cada ocorrência de '{' até achar um objeto que decodifica.
    """
    decoder = json.JSONDecoder()
    search_from = 0
    while True:
        idx = content.find("{", search_from)
        if idx == -1:
            raise AppError("Resposta do modelo não contém um JSON válido", "llm_invalid_response")
        try:
            obj, _ = decoder.raw_decode(content, idx)
            return obj
        except json.JSONDecodeError:
            search_from = idx + 1
