from app.helpers.llm.tokens import estimate_tokens
from app.pipeline.types import StructuralModel, confidence_rank


def build_context(project_name: str, model: StructuralModel, budget: int) -> tuple[str, dict[str, int]]:
    """Monta o "Mapa do Projeto". Orçado (5.1): se o orçamento apertar, corta por
    prioridade (tabelas > relacionamentos > queries > dependências > arquivos sem
    extração > módulos) em vez de nunca truncar. Retorna também quantos itens de
    cada seção foram omitidos, pra quem chama poder registrar isso como aviso (5.4)."""
    lines = [f"# Mapa do Projeto: {project_name}", ""]
    total = 0
    omitted: dict[str, int] = {}

    def try_add(line: str) -> bool:
        nonlocal total
        tokens = estimate_tokens(line)
        if total + tokens > budget:
            return False
        total += tokens
        lines.append(line)
        return True

    def add_section(title: str, items: list[str], empty_msg: str, key: str) -> None:
        try_add(f"## {title}")
        if not items:
            try_add(empty_msg)
            return
        for i, item in enumerate(items):
            if try_add(item):
                continue
            remaining = len(items) - i
            omitted[key] = remaining
            try_add(f"- ... ({remaining} item(ns) adicionais omitidos por orçamento)")
            break

    table_lines = [
        f"- {t.name} ({t.confidence}) [{', '.join(_column_repr(c) for c in t.columns)}]{_location_suffix(t.location)}"
        for t in sorted(model.tables, key=lambda t: confidence_rank(t.confidence))
    ]
    add_section("Entidades candidatas", table_lines, "- (nenhuma entidade detectada)", "entidades")
    lines.append("")

    relationship_lines = [
        f"- {r.table_a} -({r.kind})-> {r.table_b}"
        + (f" via {r.through}" if r.through else "")
        + f" ({r.confidence}){_location_suffix(r.location)}"
        for r in sorted(model.relationships, key=lambda r: confidence_rank(r.confidence))
    ]
    add_section("Relacionamentos", relationship_lines, "- (nenhum relacionamento detectado)", "relacionamentos")
    lines.append("")

    query_lines = [f"- {q.kind}: {', '.join(q.tables) or '?'}{_location_suffix(q.location)}" for q in model.queries]
    add_section("Consultas", query_lines, "- (nenhuma consulta detectada)", "consultas")
    lines.append("")

    edge_lines = [f"- [{e.kind}] {e.source} -> {e.target}" for e in model.edges]
    add_section("Dependências entre arquivos", edge_lines, "- (sem dependências detectadas)", "dependências")

    if model.unmapped_files:
        lines.append("")
        try_add(f"## Arquivos sem extração estrutural ({len(model.unmapped_files)})")
        try_add(
            "Estes arquivos não têm parser dedicado nesta versão do pipeline, então "
            "nenhuma entidade/relação foi extraída automaticamente deles. O conteúdo "
            "bruto desses arquivos pode aparecer na seção de evidências abaixo, "
            "rotulado como 'sem extração estrutural' — avalie diretamente, com "
            "confiança baixa, e nunca proponha uma entidade daqui sem apoio de outra evidência."
        )
        for i, path in enumerate(model.unmapped_files):
            if try_add(f"- {path}"):
                continue
            omitted["arquivos_sem_extração"] = len(model.unmapped_files) - i
            break

    lines.append("")
    if try_add(f"Módulos analisados ({len(model.modules)}):"):
        for i, module in enumerate(model.modules):
            if try_add(f"- {module}"):
                continue
            omitted["módulos"] = len(model.modules) - i
            break
    else:
        omitted["módulos"] = len(model.modules)

    return "\n".join(lines), omitted


def build_doc_context(model: StructuralModel) -> str:
    """Bloco separado de documentação em linguagem natural (Fase 4.2) — corroborativo,
    nunca é a única fonte usada pra propor uma entidade (instrução reforçada no prompt)."""
    if not model.doc_evidence:
        return "(nenhuma documentação com seção relevante encontrada)"
    blocks = [f"### {doc.heading}  [{doc.path}]\n{doc.text}" for doc in model.doc_evidence]
    return "\n\n".join(blocks)


def select_evidence(model: StructuralModel, budget: int) -> tuple[str, int]:
    """Retorna o texto de evidência e quantos blocos ficaram de fora por orçamento
    (5.4) — antes essa perda era só silenciosa."""
    blocks: list[str] = []
    total = 0
    omitted = 0

    def add(text: str) -> bool:
        nonlocal total
        if not text:
            return True
        tokens = estimate_tokens(text)
        if total + tokens > budget:
            return False
        total += tokens
        blocks.append(text)
        return True

    # 1.4: prioriza por confiança (ddl > schema-definition > ast > heuristic >
    # weak-fallback > raw-fallback) em vez da ordem em que as tabelas aparecem —
    # se o orçamento apertar, corta primeiro a evidência menos confiável.
    tables_by_confidence = sorted(model.tables, key=lambda t: confidence_rank(t.confidence))
    for table in tables_by_confidence:
        text = table.evidence or ""
        if not text:
            continue
        if not add(text):
            omitted += 1
            if total >= budget:
                break
    for query in model.queries:
        if len(query.tables) < 2:
            continue
        text = query.evidence or ""
        if not text:
            continue
        if not add(text):
            omitted += 1
            if total >= budget:
                break
    for query in model.queries:
        if len(query.tables) >= 2:
            continue
        text = query.evidence or ""
        if not text:
            continue
        if not add(text):
            omitted += 1
            if total >= budget:
                break
    # 4.1: evidência bruta, sempre por último — é o nível de confiança mais baixo,
    # então é o primeiro a ficar de fora quando o orçamento aperta.
    #
    # Em duas ondas, e a ordem importa: "não existe parser" é evidência mais forte
    # que "o parser olhou e não achou nada". No segundo caso já houve uma
    # conclusão negativa sobre o arquivo, então ele cede o lugar primeiro. O
    # cabeçalho diz qual é qual, para o LLM poder pesar cada um pelo que vale.
    sem_parser = [r for r in model.raw_evidence if not r.parseado_sem_entidade]
    parseados_vazios = [r for r in model.raw_evidence if r.parseado_sem_entidade]
    for rotulo, grupo in (
        ("Arquivo sem extração estrutural", sem_parser),
        ("Arquivo lido pelo parser, sem entidade declarada", parseados_vazios),
    ):
        for raw in grupo:
            block = f"# {rotulo}: {raw.path}\n{raw.text}"
            if not add(block):
                omitted += 1
                if total >= budget:
                    break
        else:
            continue
        break
    return "\n\n".join(blocks), omitted


def _column_repr(column) -> str:
    parts = [column.name, column.data_type]
    if column.primary_key:
        parts.append("PK")
    if column.fk_table:
        parts.append(f"FK->{column.fk_table}.{column.fk_column or '?'}")
    if column.unique:
        parts.append("UQ")
    return ":".join(parts)


def _location_suffix(location) -> str:
    if location is None or not location.path:
        return ""
    suffix = f"  [{location.path}:{location.line_start}"
    if location.line_end and location.line_end != location.line_start:
        suffix += f"-{location.line_end}"
    return suffix + "]"
