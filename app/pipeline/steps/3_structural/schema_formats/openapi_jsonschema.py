"""Parser para OpenAPI/Swagger e JSON Schema solto (YAML ou JSON) -- formato de
schema language-agnostic (a API é o mesmo contrato independente da linguagem do
backend). Detecta por conteúdo (chaves `openapi`/`swagger`/`$schema`/
`components.schemas`/`definitions`), não só pela extensão.
"""

from __future__ import annotations

import json

import yaml

from app.helpers.naming import table_name_for, to_snake

from ..column_utils import ensure_primary_key
from ..parsed_types import FileExtraction, ParsedColumn, ParsedTable

_TYPE_MAP = {
    "integer": "integer",
    "number": "decimal",
    "string": "string",
    "boolean": "boolean",
}


def parse_openapi(path: str, text: str, is_yaml: bool) -> FileExtraction | None:
    data = _load(text, is_yaml)
    if not _looks_like_openapi_or_schema(data):
        return None
    schemas: dict = {}
    components = data.get("components")
    if isinstance(components, dict) and isinstance(components.get("schemas"), dict):
        schemas.update(components["schemas"])
    if isinstance(data.get("definitions"), dict):
        schemas.update(data["definitions"])
    if not schemas and "$schema" in data:
        # JSON Schema "solto": o documento raiz já descreve uma única entidade.
        stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        schemas = {stem: data}
    # O filtro de domínio por nome estava ligado em Python, Java, C# e TypeScript e
    # **não** aqui — mesma omissão que o TypeScript já teve. Um documento OpenAPI
    # descreve a API, não o banco: junto das entidades vêm envelopes de resposta e
    # erros. No `grocy.openapi.json` eram 29 tabelas falsas (`CurrentStockResponse`,
    # `Error400`, `Error500`) contra 36 reais — mais ruído que sinal.
    #
    # Vale para todo formato de schema declarativo, não só OpenAPI: o critério é o
    # mesmo `domain_entity` que serve às linguagens.
    from ..domain_entity import parece_infraestrutura_pelo_nome

    tables: list[ParsedTable] = []
    for name, schema in schemas.items():
        if parece_infraestrutura_pelo_nome(name):
            continue
        table = _schema_to_table(name, schema, path)
        if table is not None:
            tables.append(table)
    if not tables:
        return None
    return FileExtraction(path=path, language="openapi", text=text, tables=tables)


def _load(text: str, is_yaml: bool):
    try:
        return yaml.safe_load(text) if is_yaml else json.loads(text)
    except Exception:  # noqa: BLE001 - conteúdo não é YAML/JSON válido, não é esse formato
        return None


def _looks_like_openapi_or_schema(data) -> bool:
    if not isinstance(data, dict):
        return False
    if "openapi" in data or "swagger" in data:
        return True
    if "$schema" in data:
        return True
    components = data.get("components")
    if isinstance(components, dict) and isinstance(components.get("schemas"), dict):
        return True
    return isinstance(data.get("definitions"), dict)


def _schema_to_table(name: str, schema, path: str) -> ParsedTable | None:
    if not isinstance(schema, dict):
        return None
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return None
    required = {to_snake(r) for r in (schema.get("required") or [])}
    columns: list[ParsedColumn] = []
    for prop_name, prop_schema in properties.items():
        column = _property_to_column(prop_name, prop_schema, required)
        if column is not None:
            columns.append(column)
    if not columns:
        return None
    ensure_primary_key(columns)
    return ParsedTable(name=table_name_for(name), columns=columns, path=path)


def _property_to_column(prop_name: str, prop_schema, required: set[str]) -> ParsedColumn | None:
    if not isinstance(prop_schema, dict):
        return None
    if "$ref" in prop_schema:
        return None  # referência a outra entidade -- sem coluna própria (heurística de FK cobre o resto)
    prop_type = prop_schema.get("type")
    if prop_type == "array":
        items = prop_schema.get("items")
        if isinstance(items, dict) and "$ref" in items:
            return None  # lista de outra entidade -- sem coluna própria
        data_type = "json"
    elif prop_type == "object":
        data_type = "json"
    else:
        fmt = prop_schema.get("format")
        if fmt in ("date-time", "date"):
            data_type = "datetime"
        elif fmt == "uuid":
            data_type = "uuid"
        else:
            data_type = _TYPE_MAP.get(prop_type, "string")
    name = to_snake(prop_name)
    return ParsedColumn(name=name, data_type=data_type, nullable=name not in required)
