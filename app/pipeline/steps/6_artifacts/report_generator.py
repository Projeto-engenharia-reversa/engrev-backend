from app.helpers.llm.prompts import load_prompt
from app.pipeline.types import CONFIDENCE_LEVELS, AnalysisContext, ConceptualModel, RelationshipDef

from .fk_resolution import resolve_sides

_TEMPLATE = load_prompt("report")

# Como cada nivel de confianca (types.CONFIDENCE_LEVELS) se le num relatorio de
# engenharia reversa. Numa ferramenta academica "de onde saiu esta entidade" e o
# que precisa ser defensavel: sem isto uma tabela lida de um CREATE TABLE e uma
# proposta pelo LLM sem nenhuma corroboracao chegam com o mesmo peso visual.
_ROTULO_DE_CONFIANCA = {
    "ddl": "DDL real",
    "schema-definition": "schema declarado",
    "ast": "código (AST)",
    "heuristic": "heurística",
    "weak-fallback": "indício fraco",
    "raw-fallback": "texto bruto",
    "llm-inferred": "proposta do LLM, sem corroboração estrutural",
}


def _local(location, source_hint: str | None) -> str:
    """`arquivo:inicio-fim` quando ha localizacao; so o arquivo quando nao ha.

    E a diferenca entre o relatorio afirmar algo e o relatorio mostrar onde
    aquilo esta escrito -- num trabalho de engenharia reversa, a segunda coisa e
    o que se pode conferir.
    """
    if location is not None and location.path:
        if location.line_start and location.line_end > location.line_start:
            return f"`{location.path}:{location.line_start}-{location.line_end}`"
        if location.line_start:
            return f"`{location.path}:{location.line_start}`"
        return f"`{location.path}`"
    return f"`{source_hint}`" if source_hint else ""


def _relationship_line(model: ConceptualModel, rel: RelationshipDef) -> str:
    """Descreve o relacionamento com o lado "one" primeiro e diz o que o sustenta.

    Como nos geradores de SQL e Mermaid, a ordem de `table_a`/`table_b` vinda do
    LLM nao e confiavel: quem define a direcao e a tabela que realmente possui a
    coluna de chave estrangeira. Essa coluna e justamente a evidencia da relacao,
    entao ela aparece no texto -- dizer "clientes 1:N enderecos" sem dizer por
    que pede confianca; citar `enderecos.cliente_id` deixa conferir.
    """
    onde = _local(rel.location, rel.source_hint)
    sufixo_local = f", em {onde}" if onde else ""

    if rel.through:
        return (
            f"- **{rel.table_a}** N --- N **{rel.table_b}** — pela tabela de junção "
            f"`{rel.through}`{sufixo_local}"
        )
    if rel.kind == "one-to-many":
        lado_one, lado_many = resolve_sides(model, rel) or (rel.table_a, rel.table_b)
        via = f"`{lado_many}.{rel.fk_column}`" if rel.fk_column else f"uma FK em `{lado_many}`"
        return f"- **{lado_one}** 1 --- N **{lado_many}** — sustentada por {via}{sufixo_local}"
    return f"- **{rel.table_a}** -({rel.kind})-> **{rel.table_b}**{sufixo_local}"


def _rotulo(confidence: str) -> str:
    return _ROTULO_DE_CONFIANCA.get(confidence, confidence)


def _bloco_de_procedencia(model: ConceptualModel) -> str:
    """Resumo por origem, do mais confiavel pro menos -- na ordem de
    CONFIDENCE_LEVELS, nao na ordem em que as tabelas sairam."""
    por_nivel: dict[str, list[str]] = {}
    for table in model.tables:
        por_nivel.setdefault(table.confidence, []).append(table.name)
    linhas = []
    for nivel in CONFIDENCE_LEVELS:
        nomes = por_nivel.pop(nivel, [])
        if nomes:
            linhas.append(f"- **{_rotulo(nivel)}** ({len(nomes)}): {', '.join(sorted(nomes))}")
    for nivel, nomes in sorted(por_nivel.items()):  # nivel desconhecido nao some do relatorio
        linhas.append(f"- **{_rotulo(nivel)}** ({len(nomes)}): {', '.join(sorted(nomes))}")
    return "\n".join(linhas) or "- Nenhuma entidade detectada."


def _bloco_de_tabela(table) -> str:
    """Entidade com a origem no cabecalho e as colunas embaixo.

    O cabecalho responde "de onde isto saiu" (arquivo, linhas, classe) e o nivel
    de confianca responde "o quanto isso e afirmacao ou palpite".
    """
    onde = _local(table.location, table.source_hint)
    simbolo = f" (`{table.location.symbol}`)" if table.location and table.location.symbol else ""
    origem = f" — {onde}{simbolo}" if onde else ""
    colunas = ", ".join(f"`{c.name}`" for c in table.columns) or "_sem colunas_"
    return f"- **{table.name}** _({_rotulo(table.confidence)})_{origem}\n  {colunas}"


def _bloco_de_raciocinio(model: ConceptualModel) -> str:
    """As `notes` que o LLM produz explicando de onde tirou cada entidade.

    O prompt ja pede 3 a 8 itens com esse racional e o modelo ja os devolve; eles
    ficavam no `model.json` e nunca chegavam ao relatorio, que e onde alguem
    efetivamente le.
    """
    return "\n".join(f"- {nota}" for nota in model.notes) or (
        "- A etapa de modelagem não registrou o racional desta extração "
        "(acontece com o provedor `mock`, que não gera explicação)."
    )


def _linha_de_coluna_removida(r) -> str:
    """Um RENAME nao e um DROP: o dado continua la, com outro nome. Tratar os dois
    como "retirada" faria o relatorio afirmar que uma coluna existente sumiu."""
    onde = f"`{r.path}:{r.line}`"
    if r.motivo == "rename" and r.renomeada_para:
        return (
            f"- `{r.table}.{r.column}` foi renomeada para "
            f"`{r.renomeada_para}` por {onde} — só o nome novo entra no modelo."
        )
    return f"- `{r.table}.{r.column}` foi removida por {onde} — não entra no modelo."


def _bloco_de_decisoes(ctx: AnalysisContext) -> str:
    """O que a analise decidiu sozinha, e com base em que.

    Duas fontes: as colunas que uma migration retirou (a Fase 3 aplica o ALTER e
    a coluna simplesmente some -- sem dizer aqui, o leitor nao tem como saber que
    ela existiu) e as correcoes da reconciliacao, que sao `info` justamente por
    serem decisao tomada, nao pendencia a resolver.
    """
    linhas = [_linha_de_coluna_removida(r) for r in ctx.structural.removed_columns]
    linhas.extend(f"- {i.message}" for i in ctx.conceptual.issues if i.severity == "info")
    return "\n".join(linhas) or "- Nenhuma correção automática foi necessária."


def generate_report(ctx: AnalysisContext) -> str:
    tables = "\n".join(_bloco_de_tabela(t) for t in ctx.conceptual.tables) or "- Nenhuma entidade detectada."
    relationships = "\n".join(
        _relationship_line(ctx.conceptual, r) for r in ctx.conceptual.relationships
    ) or "- Nenhum relacionamento detectado."
    # `info` sai daqui: e decisao ja tomada, e aparece na secao propria. Misturar
    # com warning/error fazia "Qualidade" listar coisas que nao pedem acao.
    pendencias = [i for i in ctx.conceptual.issues if i.severity != "info"]
    issues = "\n".join(f"- [{i.severity}] {i.message}" for i in pendencias) or "- Nenhuma violação encontrada."
    next_steps = "\n".join(f"- {i.suggestion}" for i in pendencias if i.suggestion) or "- Revisar o modelo gerado."
    return _TEMPLATE.format(
        project_name=ctx.project_name,
        status="concluída",
        entities=len(ctx.conceptual.tables),
        relationships_count=len(ctx.conceptual.relationships),
        tables=tables,
        provenance=_bloco_de_procedencia(ctx.conceptual),
        relationships=relationships,
        rationale=_bloco_de_raciocinio(ctx.conceptual),
        decisions=_bloco_de_decisoes(ctx),
        issues=issues,
        next_steps=next_steps,
    )
