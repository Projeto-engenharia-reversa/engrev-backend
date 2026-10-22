from app.helpers.naming import constraint_name
from app.pipeline.types import ConceptualModel

from .fk_resolution import missing_junctions

# Palavra reservada do PostgreSQL usada como nome de tabela ou coluna quebra o DDL:
# `CREATE TABLE user (...)` é erro de sintaxe. E `user` é nome de entidade comum —
# o nestjs-realworld declara `@Entity('user')` e o django tem uma coluna `user`.
#
# A lista vem do apêndice C da documentação do PostgreSQL (categorias "reserved" e
# "reserved (can be function or type)"). Tentei derivá-la de
# `sqlglot.dialects.postgres.Postgres.Tokenizer.KEYWORDS`, mas aquilo é um mapa de
# tokenização e não uma lista de reservadas: faltam `user`, `order`, `group` e
# `check` — justamente os nomes que aparecem em modelo de dados real.
_RESERVADAS_POSTGRES = frozenset("""
all analyse analyze and any array as asc asymmetric authorization binary both
case cast check collate collation column concurrently constraint create cross
current_catalog current_date current_role current_schema current_time
current_timestamp current_user default deferrable desc distinct do else end
except false fetch for foreign freeze from full grant group having ilike in
initially inner intersect into is isnull join lateral leading left like limit
localtime localtimestamp natural not notnull null offset on only or order outer
overlaps placing primary references returning right select session_user similar
some symmetric table tablesample then to trailing true union unique user using
variadic verbose when where window with
""".split())


def _ident(nome: str) -> str:
    """Identificador citado só quando precisa.

    Citar tudo também funcionaria, mas deixaria o DDL ilegível e case-sensitive
    sem necessidade — o pipeline já normaliza tudo para snake_case minúsculo.
    """
    if not nome:
        return nome
    if nome.lower() in _RESERVADAS_POSTGRES or not nome.replace("_", "").isalnum() or nome[0].isdigit():
        return '"' + nome.replace('"', '""') + '"'
    return nome


_SQL_TYPES = {
    "int": "INTEGER",
    "integer": "INTEGER",
    "str": "VARCHAR(255)",
    "string": "VARCHAR(255)",
    "text": "TEXT",
    "bool": "BOOLEAN",
    "boolean": "BOOLEAN",
    "float": "NUMERIC(12,4)",
    "number": "NUMERIC(12,4)",
    "decimal": "NUMERIC(12,4)",
    "datetime": "TIMESTAMP WITH TIME ZONE",
    "date": "DATE",
    "uuid": "UUID",
    "json": "JSONB",
    "list": "JSONB",
}


def _sql_type(data_type: str) -> str:
    t = data_type.strip().lower()
    return _SQL_TYPES.get(t, t.upper() or "VARCHAR(255)")


def _tipo_das_chaves(model: ConceptualModel) -> dict[str, str]:
    """Tipo SQL da PK de cada tabela, para alinhar as FKs que apontam para ela."""
    tipos: dict[str, str] = {}
    for table in model.tables:
        pk = next((c for c in table.columns if c.primary_key), None)
        if pk is not None:
            tipos[table.name] = _sql_type(pk.data_type)
    return tipos


def _corpo_da_tabela(table, tipo_das_chaves: dict[str, str]) -> str:
    """Colunas da tabela, com a PK composta como cláusula de tabela quando for o caso.

    Numa tabela de junção a chave é o par (a_id, b_id): declarar `PRIMARY KEY` em
    cada coluna daria dois PRIMARY KEY na mesma tabela, que o Postgres recusa.
    """
    pks = [c.name for c in table.columns if c.primary_key]
    composta = len(pks) > 1
    linhas = [
        _column_ddl(c, tipo_das_chaves.get(c.fk_table) if c.fk_table else None, inline_pk=not composta)
        for c in table.columns
    ]
    if composta:
        linhas.append(f"    PRIMARY KEY ({', '.join(_ident(n) for n in pks)})")
    return ",\n".join(linhas)


def _column_ddl(column, tipo_da_chave: str | None = None, inline_pk: bool = True) -> str:
    # Uma FK precisa ter o mesmo tipo da chave que referencia, senão o Postgres
    # recusa a constraint. Os tipos divergem quando as duas pontas vêm de fontes
    # diferentes: classe JS sem tipo dá `string`, `ID!` do GraphQL dá `string`, e
    # do outro lado a PK sai `integer`. O tipo da PK é quem manda.
    tipo = tipo_da_chave or _sql_type(column.data_type)
    parts = [f"    {_ident(column.name)} {tipo}"]
    if column.primary_key and inline_pk:
        parts.append("PRIMARY KEY")
    # Coluna de PK composta sai com NOT NULL explícito: a cláusula de tabela vem
    # depois e o Postgres já a exigiria, mas o DDL fica auto-explicativo.
    if not column.nullable or column.primary_key:
        parts.append("NOT NULL")
    if column.unique:
        parts.append("UNIQUE")
    return " ".join(parts)


def _foreign_key(source_table: str, column_name: str, target_table: str, target_column: str) -> str:
    return (
        f"ALTER TABLE {_ident(source_table)} ADD CONSTRAINT {constraint_name('fk', source_table, column_name)} "
        f"FOREIGN KEY ({_ident(column_name)}) REFERENCES {_ident(target_table)}({_ident(target_column)});"
    )


def generate_sql(model: ConceptualModel) -> str:
    """Gera o DDL a partir do modelo conceitual.

    As chaves estrangeiras saem de `column.fk_table`/`fk_column`, que dizem
    exatamente qual coluna aponta para onde. Não se deduz nada da ordem de
    `table_a`/`table_b` do relacionamento: o LLM não emite essa direção de forma
    consistente, e deduzir dela produzia FK na tabela errada e coluna duplicada
    com nome no plural (`clientes_id` ao lado do `cliente_id` correto).
    """
    juncoes = missing_junctions(model)
    table_names = {t.name for t in model.tables} | {j[0] for j in juncoes}
    tipo_das_chaves = _tipo_das_chaves(model)

    lines = ["-- Modelo gerado pela plataforma EngRev", "BEGIN;", ""]

    for table in model.tables:
        lines.append(f"CREATE TABLE IF NOT EXISTS {_ident(table.name)} (")
        lines.append(_corpo_da_tabela(table, tipo_das_chaves))
        lines.append(");")
        lines.append("")

    # Tabelas de junção declaradas via `rel.through` mas ausentes do modelo — sem
    # elas o DDL referencia uma tabela que não existe.
    for nome, col_a, tabela_a, col_b, tabela_b in juncoes:
        lines.append("-- Tabela de junção inferida do relacionamento muitos-para-muitos")
        lines.append(f"CREATE TABLE IF NOT EXISTS {_ident(nome)} (")
        # Chave é o par, não um id sintético: numa junção N:N o `id` surrogate deixa
        # o mesmo par ser inserido duas vezes, que é exatamente o que a tabela
        # existe pra impedir.
        lines.append(
            ",\n".join(
                [
                    f"    {_ident(col_a)} {tipo_das_chaves.get(tabela_a, 'INTEGER')} NOT NULL",
                    f"    {_ident(col_b)} {tipo_das_chaves.get(tabela_b, 'INTEGER')} NOT NULL",
                    f"    PRIMARY KEY ({_ident(col_a)}, {_ident(col_b)})",
                ]
            )
        )
        lines.append(");")
        lines.append("")

    for table in model.tables:
        for column in table.columns:
            if column.fk_table and column.fk_table in table_names:
                lines.append(
                    _foreign_key(table.name, column.name, column.fk_table, column.fk_column or "id")
                )

    for nome, col_a, tabela_a, col_b, tabela_b in juncoes:
        if tabela_a in table_names:
            lines.append(_foreign_key(nome, col_a, tabela_a, "id"))
        if tabela_b in table_names:
            lines.append(_foreign_key(nome, col_b, tabela_b, "id"))

    lines.append("COMMIT;")
    return "\n".join(lines)
