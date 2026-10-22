"""Extração de campos de formulário HTML (`<form>` com `<input>`/`<select>`/
`<textarea>`) -- evidência fraca de campo de entidade, comum em sistemas legados
server-rendered (PHP/ASP clássico/JSP) onde o formulário espelha a coluna do
banco. Sempre marca `confidence="weak-fallback"` (definido em `graph.py` via
`language="html"`) -- nunca é tratado como fonte estrutural confiável.
"""

from __future__ import annotations

import tree_sitter_html
from tree_sitter import Language, Node, Parser

from app.helpers.naming import table_name_for, to_snake

from .column_utils import ensure_primary_key
from .parsed_types import FileExtraction, ParsedColumn, ParsedTable

_HTML_LANGUAGE = Language(tree_sitter_html.language())
_FIELD_TAGS = {"input", "select", "textarea"}

_INPUT_TYPE_MAP = {
    "number": "decimal",
    "range": "decimal",
    "date": "date",
    "datetime-local": "datetime",
    "month": "date",
    "week": "date",
    "checkbox": "boolean",
    "radio": "boolean",
    "email": "string",
    "url": "string",
    "tel": "string",
}


def parse_html(path: str, text: str) -> FileExtraction | None:
    parser = Parser(_HTML_LANGUAGE)
    tree = parser.parse(text.encode("utf-8"))
    root = tree.root_node
    tables: list[ParsedTable] = []
    for form in _find_all(root, "element"):
        if _tag_name(form) != "form":
            continue
        table = _form_to_table(form, path)
        if table is not None:
            tables.append(table)
    if not tables:
        return None
    return FileExtraction(path=path, language="html", text=text, tables=tables)


def _find_all(node: Node, type_name: str) -> list[Node]:
    found = []
    stack = [node]
    while stack:
        current = stack.pop()
        if current.type == type_name:
            found.append(current)
        stack.extend(reversed(current.children))
    return found


def _start_tag(element: Node) -> Node | None:
    return next((c for c in element.children if c.type == "start_tag"), None)


def _tag_name(element: Node) -> str | None:
    start = _start_tag(element)
    if start is None:
        return None
    name_node = next((c for c in start.children if c.type == "tag_name"), None)
    return name_node.text.decode(errors="replace") if name_node is not None else None


def _attr_value(start_tag: Node, attr_name: str) -> str | None:
    for attr in start_tag.children:
        if attr.type != "attribute":
            continue
        name_node = next((c for c in attr.children if c.type == "attribute_name"), None)
        if name_node is None or name_node.text.decode(errors="replace") != attr_name:
            continue
        value_node = next((c for c in attr.children if c.type == "quoted_attribute_value"), None)
        if value_node is None:
            continue
        inner = next((c for c in value_node.children if c.type == "attribute_value"), None)
        return inner.text.decode(errors="replace") if inner is not None else ""
    return None


def _form_to_table(form: Node, path: str) -> ParsedTable | None:
    start = _start_tag(form)
    action = _attr_value(start, "action") if start is not None else None
    table_name = _table_name_from_action(action) or _table_name_from_path(path)
    if table_name is None:
        return None
    # Pontos lidos antes da varredura: `_find_all(form, ...)` percorre os filhos e
    # invalida `form` nesta versão do py-tree-sitter (use-after-free na leitura
    # posterior, que se manifesta como segmentation fault sob volume).
    linha_inicial = form.start_point.row + 1
    linha_final = form.end_point.row + 1
    columns: list[ParsedColumn] = []
    seen: set[str] = set()
    for field in _find_all(form, "element"):
        tag = _tag_name(field)
        if tag not in _FIELD_TAGS:
            continue
        field_start = _start_tag(field)
        if field_start is None:
            continue
        # Campo oculto é encanamento de formulário — token CSRF, id de sessão,
        # estado de página. `chamados.session_id` vinha de um
        # `<input type="hidden">`, e "session" já estava nas stopwords de FK: o
        # mesmo conhecimento só não era usado para excluir a coluna.
        if tag == "input" and (_attr_value(field_start, "type") or "").lower() == "hidden":
            continue
        name = _attr_value(field_start, "name")
        if not name:
            continue
        column_name = to_snake(name)
        if column_name in seen:
            continue
        seen.add(column_name)
        data_type = _INPUT_TYPE_MAP.get(_attr_value(field_start, "type") or "", "string") if tag == "input" else "string"
        columns.append(ParsedColumn(name=column_name, data_type=data_type, line=field.start_point.row + 1))
    if not columns:
        return None
    ensure_primary_key(columns)
    return ParsedTable(
        name=table_name, columns=columns, line_start=linha_inicial, line_end=linha_final, path=path
    )


def _table_name_from_action(action: str | None) -> str | None:
    # Não usa table_name_for() aqui (que pluraliza) -- o segmento de uma URL REST
    # já costuma vir no plural (`/pedidos`, `/users`), e to_plural() não é
    # idempotente (pluralizaria "pedidos" -> "pedidoses"). Só normaliza pra snake_case.
    if not action:
        return None
    parts = [p for p in action.split("?")[0].strip("/").split("/") if p and p != "api"]
    return to_snake(parts[0]) if parts else None


def _table_name_from_path(path: str) -> str | None:
    stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return table_name_for(stem) if stem else None
