"""Parser para changelog XML do Liquibase -- formato de migration language-agnostic
(usado por qualquer app, independente da linguagem de programação). Usa
`xml.etree.ElementTree` (stdlib), sem regex. Detecta o formato por conteúdo
(tag raiz `databaseChangeLog`), não só pela extensão `.xml`.

Trata cada `<changeSet>` como um passo de migration, na mesma linha do que já
fazemos para `ALTER TABLE` em SQL (Fase 1.5): createTable/addColumn/dropColumn/
renameColumn/addForeignKeyConstraint viram `ParsedTable`/`ParsedAlter`, aplicados
em sequência pelo `graph.py`.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from ..column_utils import ensure_primary_key
from ..parsed_types import FileExtraction, ParsedAlter, ParsedColumn, ParsedTable
from ..sql_types import sql_type_to_generic


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_liquibase(path: str, text: str) -> FileExtraction | None:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    if _local(root.tag) != "databaseChangeLog":
        return None
    tables: list[ParsedTable] = []
    alters: list[ParsedAlter] = []
    for changeset in root:
        if _local(changeset.tag) != "changeSet":
            continue
        for change in changeset:
            tag = _local(change.tag)
            if tag == "createTable":
                table = _create_table(change, path)
                if table is not None:
                    tables.append(table)
            elif tag == "addColumn":
                alters.extend(_add_column(change, path))
            elif tag == "dropColumn":
                alters.extend(_drop_column(change, path))
            elif tag == "renameColumn":
                alter = _rename_column(change, path)
                if alter is not None:
                    alters.append(alter)
            elif tag == "addForeignKeyConstraint":
                alter = _add_fk_constraint(change, path)
                if alter is not None:
                    alters.append(alter)
    if not tables and not alters:
        return None
    return FileExtraction(path=path, language="liquibase-xml", text=text, tables=tables, alters=alters)


def _create_table(elem: ET.Element, path: str) -> ParsedTable | None:
    table_name = elem.get("tableName")
    if not table_name:
        return None
    columns: list[ParsedColumn] = []
    for child in elem:
        if _local(child.tag) != "column":
            continue
        column = _parse_column(child)
        if column is not None:
            columns.append(column)
    if not columns:
        return None
    ensure_primary_key(columns)
    return ParsedTable(name=table_name, columns=columns, path=path)


def _parse_column(elem: ET.Element) -> ParsedColumn | None:
    name = elem.get("name")
    if not name:
        return None
    column = ParsedColumn(name=name, data_type=sql_type_to_generic(elem.get("type") or ""))
    for child in elem:
        if _local(child.tag) != "constraints":
            continue
        if (child.get("primaryKey") or "").lower() == "true":
            column.primary_key = True
        if (child.get("nullable") or "").lower() == "false":
            column.nullable = False
        if (child.get("unique") or "").lower() == "true":
            column.unique = True
        references = child.get("references")
        if references and "(" in references and references.endswith(")"):
            ref_table, ref_col = references[:-1].split("(", 1)
            column.fk_table = ref_table.strip()
            column.fk_column = ref_col.strip()
    return column


def _add_column(elem: ET.Element, path: str) -> list[ParsedAlter]:
    table_name = elem.get("tableName")
    if not table_name:
        return []
    out: list[ParsedAlter] = []
    for child in elem:
        if _local(child.tag) != "column":
            continue
        column = _parse_column(child)
        if column is not None:
            out.append(ParsedAlter(table=table_name, action="add_column", column=column, path=path))
    return out


def _drop_column(elem: ET.Element, path: str) -> list[ParsedAlter]:
    table_name = elem.get("tableName")
    if not table_name:
        return []
    out: list[ParsedAlter] = []
    single = elem.get("columnName")
    if single:
        out.append(ParsedAlter(table=table_name, action="drop_column", column_name=single, path=path))
    for child in elem:
        if _local(child.tag) == "column":
            name = child.get("name")
            if name:
                out.append(ParsedAlter(table=table_name, action="drop_column", column_name=name, path=path))
    return out


def _rename_column(elem: ET.Element, path: str) -> ParsedAlter | None:
    table_name = elem.get("tableName")
    old_name = elem.get("oldColumnName")
    new_name = elem.get("newColumnName")
    if not (table_name and old_name and new_name):
        return None
    return ParsedAlter(table=table_name, action="rename_column", old_name=old_name, new_name=new_name, path=path)


def _add_fk_constraint(elem: ET.Element, path: str) -> ParsedAlter | None:
    table_name = elem.get("baseTableName")
    column_name = elem.get("baseColumnNames")
    ref_table = elem.get("referencedTableName")
    ref_column = elem.get("referencedColumnNames")
    if not (table_name and column_name and ref_table):
        return None
    # baseColumnNames pode ter múltiplas colunas separadas por vírgula (FK composta);
    # tratamos só a primeira -- caso raro pra esse escopo.
    first_column = column_name.split(",")[0].strip()
    return ParsedAlter(
        table=table_name,
        action="add_fk",
        column_name=first_column,
        fk_table=ref_table,
        fk_column=(ref_column.split(",")[0].strip() if ref_column else "id"),
        path=path,
    )
