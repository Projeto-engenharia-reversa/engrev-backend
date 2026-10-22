"""Descobre qual lado de um relacionamento carrega a chave estrangeira.

Os dois geradores de artefato precisavam dessa resposta e cada um assumia uma
convenção — opostas entre si. O gerador de SQL tratava `table_a` como o lado
"many" (punha a FK nele); o Mermaid tratava `table_a` como o lado "one". Como o
LLM não emite a direção de forma consistente, cada rodada acertava um artefato e
errava o outro.

A direção não precisa ser adivinhada: `ColumnDef.fk_table`/`fk_column` já dizem
qual coluna aponta para qual tabela, e `RelationshipDef.fk_column` nomeia a
coluna que sustenta o relacionamento. Este módulo lê esse metadado; os geradores
só formatam.
"""

from __future__ import annotations

from app.helpers.naming import fk_name_for
from app.pipeline.types import ConceptualModel, RelationshipDef, TableDef


def table_by_name(model: ConceptualModel, name: str) -> TableDef | None:
    return next((t for t in model.tables if t.name == name), None)


def resolve_sides(model: ConceptualModel, rel: RelationshipDef) -> tuple[str, str] | None:
    """Retorna `(lado_one, lado_many)` de um relacionamento, ou `None` se o modelo
    não tiver evidência suficiente.

    O lado "many" é o que possui a coluna de FK apontando para o outro.
    """
    for holder, target in ((rel.table_a, rel.table_b), (rel.table_b, rel.table_a)):
        table = table_by_name(model, holder)
        if table is None:
            continue
        for column in table.columns:
            if column.fk_table == target and (not rel.fk_column or column.name == rel.fk_column):
                return target, holder

    # Sem `fk_table` preenchido, o nome da coluna declarado no relacionamento
    # ainda identifica o lado que a possui.
    if rel.fk_column:
        for holder, target in ((rel.table_a, rel.table_b), (rel.table_b, rel.table_a)):
            table = table_by_name(model, holder)
            if table is not None and any(c.name == rel.fk_column for c in table.columns):
                return target, holder
    return None


def _parte_correspondente(tabela: str, partes: list[str]) -> str | None:
    """Casa `livros` com a parte `livro` de uma junção chamada `livro_autor`."""
    for parte in partes:
        if tabela.startswith(parte):
            return f"{parte}_id"
    return None


def junction_fk_names(through: str, table_a: str, table_b: str) -> tuple[str, str]:
    """Nomes das duas colunas de FK de uma tabela de junção sintetizada.

    A convenção usual nomeia a junção com as duas entidades no singular
    (`livro_autor` entre `livros` e `autores`) e as colunas seguem esse singular.
    Quando o nome da junção não tem essa forma, cai para `<tabela>_id`. Evita-se
    singularizar por regra: `to_plural` é anglófono e não se inverte em
    português (`autores` não volta para `autor`).
    """
    partes = [p for p in through.split("_") if p]
    nome_a = _parte_correspondente(table_a, partes) or fk_name_for(table_a)
    nome_b = _parte_correspondente(table_b, partes) or fk_name_for(table_b)
    if nome_a == nome_b:
        return fk_name_for(table_a), fk_name_for(table_b)
    return nome_a, nome_b


def missing_junctions(model: ConceptualModel) -> list[tuple[str, str, str, str, str]]:
    """Junções declaradas em `rel.through` que não existem como tabela no modelo.

    Cada item é `(nome_da_juncao, coluna_a, tabela_a, coluna_b, tabela_b)`.
    """
    existentes = {t.name for t in model.tables}
    vistas: set[str] = set()
    faltantes: list[tuple[str, str, str, str, str]] = []
    for rel in model.relationships:
        if not rel.through or rel.through in existentes or rel.through in vistas:
            continue
        vistas.add(rel.through)
        col_a, col_b = junction_fk_names(rel.through, rel.table_a, rel.table_b)
        faltantes.append((rel.through, col_a, rel.table_a, col_b, rel.table_b))
    return faltantes
