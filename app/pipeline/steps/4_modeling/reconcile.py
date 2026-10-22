"""Fase 4.5 -- confronta a saída do LLM com o que a Fase 3 apurou de forma
determinística.

Sem esta etapa a Fase 4 é uma substituição total: `ctx.conceptual` passa a ser
exatamente o que o modelo devolveu, e tudo que a extração estrutural estabeleceu
(confiança da fonte, procedência, colunas retiradas por migration) desaparece.
Na prática isso deixava o palpite do LLM ganhar do DDL literal, e fazia uma
tabela inventada pelo modelo chegar no relatório indistinguível de uma lida de
um `CREATE TABLE`.

A postura aqui é estreita de propósito: só se desfaz o que **contradiz** um fato
declarado explicitamente no código. Divergência que pode ser decisão legítima de
modelagem (renomear, fundir, dividir entidade) vira `ValidationIssue` -- não
correção silenciosa. Corrigir sozinho o que não é contradição seria trocar o
palpite do LLM pelo meu.
"""

from __future__ import annotations

from app.pipeline.types import (
    ConceptualModel,
    RelationshipDef,
    StructuralModel,
    TableDef,
    ValidationIssue,
)


def reconcile(structural: StructuralModel, conceptual: ConceptualModel) -> list[ValidationIssue]:
    """Ajusta `conceptual` no lugar e devolve as questões levantadas."""
    issues: list[ValidationIssue] = []
    issues.extend(_remover_colunas_ressuscitadas(structural, conceptual))
    issues.extend(_repor_tabelas_que_o_proprio_llm_referencia(structural, conceptual))
    _reatar_procedencia(structural, conceptual)
    issues.extend(_apontar_tabelas_declaradas_ausentes(structural, conceptual))
    return issues


def _repor_tabelas_que_o_proprio_llm_referencia(
    structural: StructuralModel, conceptual: ConceptualModel
) -> list[ValidationIssue]:
    """Repõe tabela que a saída do LLM cita mas esqueceu de listar.

    Caso observado: o modelo declara a relação N:N com `through="livro_autor"` e
    não inclui `livro_autor` em `tables`. Os geradores de SQL e Mermaid
    compensam sozinhos, mas o modelo conceitual fica contraditório e a Fase 5
    acusa dois erros sobre algo que o pipeline já resolveu.

    Ao contrário de uma tabela que simplesmente sumiu (ver
    `_apontar_tabelas_declaradas_ausentes`, onde repor seria chute), aqui não há
    ambiguidade: **o próprio LLM afirma que a tabela existe**, e a Fase 3 tem a
    definição dela. Repor é obedecer às duas fontes, não escolher entre elas.

    Só vale para `through`. Um `fk_table` órfão tem outra explicação plausível —
    o LLM renomeou a tabela alvo e esqueceu de atualizar a FK — e aí repor criaria
    a entidade duplicada que `_reatar_fks_das_colunas` evita pelo mesmo motivo.
    Uma tabela de junção não sofre desse risco: ela não tem identidade própria
    para ser renomeada, existe só para ligar as duas pontas.
    """
    presentes = {t.name for t in conceptual.tables}
    disponiveis = {t.name: t for t in structural.tables}
    citadas = {rel.through for rel in conceptual.relationships if rel.through}

    issues: list[ValidationIssue] = []
    for nome in sorted(citadas - presentes):
        origem = disponiveis.get(nome)
        if origem is None:
            continue  # a Fase 3 também não conhece: é erro real, a Fase 5 acusa
        conceptual.tables.append(origem.model_copy(deep=True))
        issues.append(
            ValidationIssue(
                severity="info",
                message=(
                    f"Tabela '{nome}' era citada pelo modelo mas não estava na lista de "
                    f"tabelas — reposta a partir da extração estrutural."
                ),
                source=nome,
            )
        )
    return issues


def _remover_colunas_ressuscitadas(
    structural: StructuralModel, conceptual: ConceptualModel
) -> list[ValidationIssue]:
    """A2 -- coluna que uma migration retirou não volta pela porta dos fundos.

    O LLM recebe na mesma evidência o `CREATE TABLE` original e o `ALTER TABLE
    ... DROP COLUMN`, e com frequência devolve a coluna. Como `DROP COLUMN` é uma
    deleção explícita na fonte de confiança máxima, aqui não há ambiguidade a
    respeitar: a coluna sai.
    """
    if not structural.removed_columns:
        return []
    por_tabela: dict[str, dict[str, tuple[str, int]]] = {}
    for removida in structural.removed_columns:
        por_tabela.setdefault(removida.table, {})[removida.column] = (removida.path, removida.line)

    issues: list[ValidationIssue] = []
    for table in conceptual.tables:
        removidas = por_tabela.get(table.name)
        if not removidas:
            continue
        mantidas = []
        for column in table.columns:
            origem = removidas.get(column.name)
            if origem is None:
                mantidas.append(column)
                continue
            path, line = origem
            local = f"{path}:{line}" if path else "uma migration"
            issues.append(
                ValidationIssue(
                    severity="info",
                    message=(
                        f"Coluna '{column.name}' foi removida de '{table.name}' por "
                        f"{local} e reaparecia no modelo do LLM — descartada."
                    ),
                    source=table.name,
                )
            )
        table.columns = mantidas
    return issues


def _reatar_procedencia(structural: StructuralModel, conceptual: ConceptualModel) -> None:
    """A3 -- devolve confiança/localização, que a Fase 4 não tem como carregar.

    O formato de resposta do prompt não tem esses campos (nem deveria: o LLM não
    sabe de que parser a tabela veio), então tudo volta no default do schema. Sem
    reatar aqui, `confidence` passa a mentir em vez de faltar.
    """
    tabelas = {t.name: t for t in structural.tables}
    nomes_finais = {t.name for t in conceptual.tables}
    for table in conceptual.tables:
        origem = tabelas.get(table.name)
        if origem is None:
            table.confidence = "llm-inferred"
            continue
        table.confidence = origem.confidence
        table.location = table.location or origem.location
        table.source_hint = table.source_hint or origem.source_hint
        _restaurar_tipos_declarados(origem, table)
        _reatar_fks_das_colunas(origem, table, nomes_finais)

    relacoes = {_chave_de_relacao(r): r for r in structural.relationships}
    for rel in conceptual.relationships:
        origem = relacoes.get(_chave_de_relacao(rel))
        if origem is None:
            rel.confidence = "llm-inferred"
            continue
        rel.confidence = origem.confidence
        rel.location = rel.location or origem.location
        rel.source_hint = rel.source_hint or origem.source_hint
        rel.fk_column = rel.fk_column or origem.fk_column


def _restaurar_tipos_declarados(origem: TableDef, table: TableDef) -> None:
    """Devolve o tipo que a Fase 3 leu de uma fonte que **declara** tipo.

    Simétrico à regra de merge da Fase 3 (`graph._melhor_tipo`): DDL e formato de
    schema declaram; AST de linguagem sem anotação e formulário HTML inferem. O
    LLM pode melhorar um tipo inferido — `criado_em` como datetime a partir do
    nome é acerto dele. O que ele não pode é sobrepor um `VARCHAR(11)` declarado
    num `CREATE TABLE`.

    Medido no projeto 2 antes desta regra: 0 divergências, o modelo preservava
    tudo. Era lacuna latente, não defeito ativo — a guarda existe para o dia em
    que o modelo variar.
    """
    # Importado da Fase 3 em vez de duplicado: é a mesma política, e duas cópias
    # divergiriam em silêncio sobre o que conta como declaração.
    from importlib import import_module

    graph = import_module("app.pipeline.steps.3_structural.graph")
    if origem.confidence not in graph._FONTES_COM_TIPO_DECLARADO:
        return
    declarados = {c.name: c.data_type for c in origem.columns}
    for column in table.columns:
        tipo = declarados.get(column.name)
        if tipo and tipo != column.data_type:
            column.data_type = tipo


def _reatar_fks_das_colunas(origem: TableDef, table: TableDef, nomes_finais: set[str]) -> None:
    """Repõe `fk_table`/`fk_column` que a Fase 3 apurou e o LLM deixou nulo.

    Só preenche vazio -- nunca sobrescreve uma FK que o LLM afirmou -- e só se a
    tabela alvo sobreviveu na saída final, senão o que se repõe é uma FK pendurada
    (o LLM pode ter renomeado a tabela alvo legitimamente).
    """
    por_nome = {c.name: c for c in origem.columns}
    for column in table.columns:
        if column.fk_table:
            continue
        anterior = por_nome.get(column.name)
        if anterior is None or not anterior.fk_table:
            continue
        if anterior.fk_table not in nomes_finais:
            continue
        column.fk_table = anterior.fk_table
        column.fk_column = anterior.fk_column


def _chave_de_relacao(rel: RelationshipDef) -> tuple[frozenset[str], str | None]:
    """Casa relação por par de tabelas, não por nome.

    O nome é livre e o LLM o inventa a cada rodada; a ordem de `table_a`/`table_b`
    também varia (foi o bug 1). O par não-ordenado mais o `through` é o que
    identifica a mesma relação entre as duas fases.
    """
    return frozenset({rel.table_a, rel.table_b}), rel.through


def _apontar_tabelas_declaradas_ausentes(
    structural: StructuralModel, conceptual: ConceptualModel
) -> list[ValidationIssue]:
    """A4 -- tabela vinda de DDL real que sumiu na Fase 4 vira questão, não volta.

    Reinserir seria tentador e errado: o LLM pode tê-la renomeado por um motivo
    válido (`@Table`, singular/plural), e reinserir criaria duplicata das mesmas
    colunas com dois nomes. Quem lê o relatório decide.
    """
    nomes_finais = {t.name for t in conceptual.tables}
    issues: list[ValidationIssue] = []
    for table in structural.tables:
        if table.confidence != "ddl" or table.name in nomes_finais:
            continue
        local = table.location.path if table.location and table.location.path else table.source_hint
        onde = f" (declarada em {local})" if local else ""
        issues.append(
            ValidationIssue(
                severity="error",
                message=(
                    f"Tabela '{table.name}' vem de DDL real{onde} mas não aparece no "
                    f"modelo final — pode ter sido renomeada ou perdida na modelagem."
                ),
                source=table.name,
                suggestion=f"Confirme se '{table.name}' foi renomeada; se não, reinsira-a.",
            )
        )
    return issues
