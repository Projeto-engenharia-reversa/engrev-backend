"""Parser para Prisma Schema Language (.prisma) -- sem regex: parsing manual
linha-a-linha, já que a sintaxe é simples e regular (blocos `model Nome { ... }`).
"""

from __future__ import annotations

from app.helpers.naming import table_name_for, to_snake

from ..column_utils import ensure_primary_key
from ..parsed_types import FileExtraction, ParsedColumn, ParsedTable

_TYPE_MAP = {
    "String": "string",
    "Int": "integer",
    "BigInt": "integer",
    "Float": "decimal",
    "Decimal": "decimal",
    "Boolean": "boolean",
    "DateTime": "datetime",
    "Json": "json",
    "Bytes": "string",
}


def parse_prisma(path: str, text: str) -> FileExtraction | None:
    lines = text.splitlines()
    model_names = _collect_model_names(lines)
    if not model_names:
        return None
    # Resolve os `@@map` antes de montar as tabelas: sem isso a tabela sairia
    # renomeada mas as FKs continuariam apontando para o nome pluralizado antigo.
    # No Prisma dá para fazer num passo só, porque os modelos ficam no mesmo arquivo.
    nomes_de_tabela = _collect_table_names(lines, model_names)

    tables: list[ParsedTable] = []
    i = 0
    n = len(lines)
    while i < n:
        stripped = lines[i].strip()
        if stripped.startswith("model ") and stripped.endswith("{"):
            name = stripped[len("model "):-1].strip()
            body_start = i + 1
            j = body_start
            body: list[tuple[int, str]] = []
            while j < n and lines[j].strip() != "}":
                body.append((j + 1, lines[j]))
                j += 1
            table = _model_to_table(name, body, model_names, nomes_de_tabela, path, body_start, j)
            if table is not None:
                tables.append(table)
            i = j + 1
            continue
        i += 1
    if not tables:
        return None
    return FileExtraction(path=path, language="prisma", text=text, tables=tables)


def _collect_model_names(lines: list[str]) -> set[str]:
    names: set[str] = set()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("model ") and stripped.endswith("{"):
            names.add(stripped[len("model "):-1].strip())
    return names


def _collect_table_names(lines: list[str], model_names: set[str]) -> dict[str, str]:
    """Nome real de cada model: `@@map("x")` quando declarado, senão o plural."""
    nomes = {nome: table_name_for(nome) for nome in model_names}
    atual: str | None = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("model ") and stripped.endswith("{"):
            atual = stripped[len("model "):-1].strip()
        elif stripped == "}":
            atual = None
        elif atual is not None and (mapeado := _atributo_map(stripped)):
            nomes[atual] = mapeado
    return nomes


def _model_to_table(
    name: str,
    body: list[tuple[int, str]],
    model_names: set[str],
    nomes_de_tabela: dict[str, str],
    path: str,
    line_start: int,
    line_end: int,
) -> ParsedTable | None:
    columns: list[ParsedColumn] = []
    explicit_fks: dict[str, tuple[str, str]] = {}
    for line_no, raw in body:
        stripped = raw.strip()
        if not stripped or stripped.startswith("//"):
            continue
        if stripped.startswith("@@"):
            continue  # atributo de bloco (@@map já foi resolvido em _collect_table_names)
        parts = stripped.split()
        if len(parts) < 2:
            continue
        field_name, type_token = parts[0], parts[1]

        if "@relation(" in stripped:
            fk_fields = _bracket_list(stripped, "fields:")
            ref_fields = _bracket_list(stripped, "references:")
            if fk_fields and ref_fields:
                explicit_fks[fk_fields[0]] = (type_token.rstrip("?[]"), ref_fields[0])

        is_list = type_token.endswith("[]")
        base_type = type_token[:-2] if is_list else type_token
        nullable = base_type.endswith("?")
        if nullable:
            base_type = base_type[:-1]
        if base_type in model_names:
            continue  # campo de relação (objeto/lista) -- sem coluna própria
        data_type = "json" if is_list else _TYPE_MAP.get(base_type, "string")
        attrs = parts[2:]
        columns.append(
            ParsedColumn(
                # Normaliza para snake_case como todo o resto do pipeline: campo
                # Prisma é camelCase por convenção (`clienteId`), e sem isso a
                # mesma entidade sai com nomes diferentes conforme a fonte.
                name=to_snake(field_name),
                data_type=data_type,
                nullable=nullable,
                primary_key="@id" in attrs,
                unique="@unique" in attrs,
                line=line_no,
            )
        )

    for field_name, (target_model, ref_field) in explicit_fks.items():
        # `explicit_fks` guarda o nome cru vindo de `fields: [clienteId]`, então a
        # busca precisa normalizar dos dois lados — comparar com o nome cru aqui
        # faria os `@relation` pararem de ligar.
        alvo = to_snake(field_name)
        column = next((c for c in columns if c.name == alvo), None)
        if column is not None:
            column.fk_table = nomes_de_tabela.get(target_model, table_name_for(target_model))
            column.fk_column = to_snake(ref_field)

    if not columns:
        return None
    ensure_primary_key(columns)
    return ParsedTable(
        name=nomes_de_tabela.get(name, table_name_for(name)),
        columns=columns,
        line_start=line_start,
        line_end=line_end,
        path=path,
    )


def _atributo_map(stripped: str) -> str | None:
    """`@@map("nome_real")` -> `nome_real`. Outros `@@` (index, unique) são ignorados."""
    if not stripped.startswith("@@map("):
        return None
    dentro = stripped[len("@@map(") :].split(")")[0].strip()
    return dentro.strip('"') or None


def _bracket_list(line: str, keyword: str) -> list[str]:
    """Extrai o conteúdo de `keyword: [a, b]` sem regex -- busca de substring + split."""
    idx = line.find(keyword)
    if idx == -1:
        return []
    start = line.find("[", idx)
    end = line.find("]", start) if start != -1 else -1
    if start == -1 or end == -1:
        return []
    inner = line[start + 1 : end]
    return [p.strip() for p in inner.split(",") if p.strip()]
