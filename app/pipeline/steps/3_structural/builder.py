from pathlib import Path

from app.helpers.language_detect import detect_language
from app.pipeline.types import DocEvidence, FileSummary, RawEvidence, StructuralModel

from .graph import build_structural as _build_graph
from .markdown_sections import extract_sections, filter_relevant_sections
from .parsers import parse_file

# Mesmo limite de linhas usado nos snippets de evidência de tabela (parsers.py/graph.py)
# — um arquivo sem parser não pode dominar sozinho o orçamento de evidência.
_MAX_RAW_EVIDENCE_LINES = 500


def build_structural(summaries: list[FileSummary], root: Path) -> StructuralModel:
    extractions = []
    unmapped_files: list[str] = []
    raw_evidence: list[RawEvidence] = []
    doc_evidence: list[DocEvidence] = []
    for summary in summaries:
        if summary.status != "ok":
            continue
        path = root / summary.relative_path
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if detect_language(summary.relative_path) == "markdown":
            # Markdown nunca produz TableDef -- alimenta só o canal de documentação
            # (Fase 4.2), fora do fluxo normal de parse_file.
            sections = filter_relevant_sections(extract_sections(text))
            doc_evidence.extend(
                DocEvidence(path=summary.relative_path, heading=s.heading, text=_truncate(s.text)) for s in sections
            )
            continue

        extraction = parse_file(summary.relative_path, text)
        if extraction is None:
            unmapped_files.append(summary.relative_path)
            raw_evidence.append(RawEvidence(path=summary.relative_path, text=_truncate(text)))
            continue
        extractions.append(extraction)
        # Parser rodou e não achou nada: o arquivo some do modelo estrutural, e
        # sumia também do prompt. Num projeto que declara o schema isso é o certo
        # (`views.py` não tem modelo mesmo). Num projeto que NÃO declara, é o
        # oposto: o modelo está no uso, e o uso é justamente o que foi descartado.
        # A ferramenta não distingue os dois casos por arquivo — então entrega o
        # texto no nível mais fraco e deixa o orçamento decidir.
        if not (extraction.tables or extraction.symbols or extraction.alters or extraction.queries):
            raw_evidence.append(
                RawEvidence(
                    path=summary.relative_path,
                    text=_truncate(text),
                    parseado_sem_entidade=True,
                )
            )
    model = _build_graph(extractions)
    model.unmapped_files = unmapped_files
    model.raw_evidence = raw_evidence
    model.doc_evidence = doc_evidence
    return model


def _truncate(text: str, max_lines: int = _MAX_RAW_EVIDENCE_LINES) -> str:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    return "\n".join(lines[:max_lines]) + f"\n... (truncado, {len(lines) - max_lines} linhas a mais)"
