"""Parser para GraphQL SDL (.graphql/.gql) -- usa `graphql-core` pra parse real do
schema (não regex/heurística de texto), já que a linguagem GraphQL tem gramática
própria com blocos aninhados que regex não daria conta de forma confiável.
"""

from __future__ import annotations

from graphql import (
    GraphQLEnumType,
    GraphQLInterfaceType,
    GraphQLList,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLScalarType,
    build_schema,
)

from app.helpers.naming import table_name_for, to_snake

from ..column_utils import ensure_primary_key
from ..parsed_types import FileExtraction, ParsedColumn, ParsedTable

_SCALAR_TYPE_MAP = {
    # `ID` serializa como String no GraphQL, mas semanticamente é "identificador
    # opaco", não texto. Mapeá-lo para "string" contradizia a convenção do resto
    # do sistema (`ensure_primary_key` insere `id` integer, o prompt de modelagem
    # pede id integer) e, como a FK adota o tipo da PK que referencia, um único
    # `id: ID!` espalhava VARCHAR(255) por todas as tabelas que apontavam pra ela.
    # Projeto com id em UUID precisa corrigir isso à mão -- é um default, não uma
    # leitura do código.
    "ID": "integer",
    "String": "string",
    "Int": "integer",
    "Float": "decimal",
    "Boolean": "boolean",
}

# Tipos raiz da API (não são entidades de domínio, são o ponto de entrada de queries/mutations).
_ROOT_TYPE_NAMES = {"Query", "Mutation", "Subscription"}


def parse_graphql(path: str, text: str) -> FileExtraction | None:
    try:
        schema = build_schema(text)
    except Exception:  # noqa: BLE001 - SDL inválida ou incompleta não deve derrubar o pipeline
        return None
    object_names = {
        name
        for name, t in schema.type_map.items()
        if isinstance(t, (GraphQLObjectType, GraphQLInterfaceType)) and not name.startswith("__")
    }
    tables: list[ParsedTable] = []
    for name in object_names:
        if name in _ROOT_TYPE_NAMES:
            continue
        gql_type = schema.type_map[name]
        table = _object_type_to_table(name, gql_type, object_names, path)
        if table is not None:
            tables.append(table)
    if not tables:
        return None
    return FileExtraction(path=path, language="graphql", text=text, tables=tables)


def _unwrap(gql_type):
    while isinstance(gql_type, (GraphQLNonNull, GraphQLList)):
        gql_type = gql_type.of_type
    return gql_type


def _is_list(gql_type) -> bool:
    """Se há uma lista em qualquer ponto da cadeia de tipos.

    Precisa ser checado antes do `_unwrap`, que descarta `GraphQLNonNull` e
    `GraphQLList` juntos e apaga justamente a distinção entre o lado "one" e o
    lado "many" de uma relação.
    """
    while isinstance(gql_type, (GraphQLNonNull, GraphQLList)):
        if isinstance(gql_type, GraphQLList):
            return True
        gql_type = gql_type.of_type
    return False


def _object_type_to_table(name: str, gql_type, object_names: set[str], path: str) -> ParsedTable | None:
    columns: list[ParsedColumn] = []
    for field_name, gql_field in gql_type.fields.items():
        base = _unwrap(gql_field.type)
        base_name = getattr(base, "name", None)
        if base_name in object_names:
            if _is_list(gql_field.type):
                continue  # lado "many" da relação -- a coluna fica na outra tabela
            # Referência singular (`cliente: Cliente!`) é o lado "one" de um
            # muitos-para-um: vira coluna de FK, como o parser de Java já faz.
            columns.append(
                ParsedColumn(
                    name=to_snake(field_name) + "_id",
                    data_type="integer",
                    nullable=not isinstance(gql_field.type, GraphQLNonNull),
                    fk_table=table_name_for(base_name),
                    fk_column="id",
                )
            )
            continue
        if isinstance(base, GraphQLEnumType):
            data_type = "string"
        elif isinstance(base, GraphQLScalarType):
            data_type = _SCALAR_TYPE_MAP.get(base_name, "string")
        else:
            data_type = "string"
        column_name = to_snake(field_name)
        columns.append(
            ParsedColumn(name=column_name, data_type=data_type, nullable=not isinstance(gql_field.type, GraphQLNonNull))
        )
    if not columns:
        return None
    ensure_primary_key(columns)
    return ParsedTable(name=table_name_for(name), columns=columns, path=path)
