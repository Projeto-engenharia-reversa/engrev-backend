"""Parsing estrutural por AST (tree-sitter) e sqlglot.

Substitui as heurísticas por regex do builder antigo. Cada parser produz uma
representação intermediária (`FileExtraction`) consumida por `graph.py`.
"""

from __future__ import annotations

import json
import re

import sqlglot
import tree_sitter_python
import tree_sitter_typescript
from sqlglot import exp
from tree_sitter import Language, Node, Parser

from app.helpers.language_detect import detect_language
from app.helpers.naming import table_name_for, to_snake

from .c_family import parse_csharp, parse_java
from .domain_entity import selecionar_por_anotacao
from .html_forms import parse_html
from .parsed_types import (
    FileExtraction,
    ParsedAlter,
    ParsedColumn,
    ParsedField,
    ParsedQuery,
    ParsedSymbol,
    ParsedTable,
)
from .schema_formats.graphql_sdl import parse_graphql
from .schema_formats.liquibase_xml import parse_liquibase
from .schema_formats.mybatis_xml import parse_mybatis
from .schema_formats.openapi_jsonschema import parse_openapi
from .schema_formats.prisma import parse_prisma
from .schema_formats.protobuf import parse_protobuf
from .sql_types import sql_type_to_generic

_PY_LANGUAGE = Language(tree_sitter_python.language())
_TS_LANGUAGE = Language(tree_sitter_typescript.language_typescript())
_TSX_LANGUAGE = Language(tree_sitter_typescript.language_tsx())

_SQL_KEYWORD_RE = re.compile(
    r"\b(SELECT\b|INSERT\s+INTO\b|UPDATE\b|DELETE\s+FROM\b)", re.IGNORECASE
)
_QUOTE_CHARS = "'\"`"
_MAX_EVIDENCE_LINES = 500

# Acima disto, o objeto JSON é dado (dicionário de tradução, mapa de emoji) e não
# o retrato de uma entidade. `data/categoria.json` do projeto 1, com 6 chaves,
# continua passando — é dado de exemplo de uma entidade real.
_MAX_COLUNAS_DE_JSON = 50


def parse_file(path: str, text: str) -> FileExtraction | None:
    language = detect_language(path)
    if language is None:
        return None
    if language == "python":
        return _parse_python(path, text)
    if language in ("typescript", "tsx", "javascript", "jsx"):
        return _parse_typescript(path, text, language)
    if language == "sql":
        return _parse_sql(path, text)
    if language == "prisma":
        return parse_prisma(path, text)
    if language == "protobuf":
        return parse_protobuf(path, text)
    if language == "graphql":
        return parse_graphql(path, text)
    if language == "yaml":
        return parse_openapi(path, text, is_yaml=True)
    if language == "xml":
        # Liquibase primeiro (declara tabela), MyBatis depois (declara QUAIS
        # classes são entidade). Formatos diferentes, mesma extensão.
        return parse_liquibase(path, text) or parse_mybatis(path, text)
    if language == "java":
        return parse_java(path, text)
    if language == "csharp":
        return parse_csharp(path, text)
    if language == "html":
        return parse_html(path, text)
    if language == "json":
        # Camada 2: tenta OpenAPI/JSON Schema primeiro (formato de schema explícito,
        # mais confiável); só cai pra heurística de forma de dados se não for.
        openapi_extraction = parse_openapi(path, text, is_yaml=False)
        if openapi_extraction is not None:
            return openapi_extraction
        return _parse_json(path, text)
    return None


def _find_all(node: Node, type_name: str) -> list[Node]:
    found = []
    stack = [node]
    while stack:
        current = stack.pop()
        if current.type == type_name:
            found.append(current)
        stack.extend(reversed(current.children))
    return found


def _node_text(node: Node) -> str:
    return node.text.decode(errors="replace")


def _snippet(text: str, line_start: int, line_end: int, max_lines: int = _MAX_EVIDENCE_LINES) -> str:
    lines = text.splitlines()
    start = max(0, line_start - 1)
    end = min(len(lines), line_end)
    if end - start > max_lines:
        end = start + max_lines
    return "\n".join(lines[start:end])


def _unquote(value: str) -> str:
    value = value.strip()
    if value and value[0] in _QUOTE_CHARS and value[-1] == value[0]:
        return value[1:-1]
    return value


# --------------------------------------------------------------------------
# Tipos genéricos
# --------------------------------------------------------------------------


def _py_type(raw: str | None) -> str:
    if not raw:
        return "string"
    raw = raw.strip().lower()
    if any(k in raw for k in ("list", "set", "dict", "sequence")):
        return "json"
    if "str" in raw:
        return "string"
    if "int" in raw:
        return "integer"
    if any(k in raw for k in ("float", "decimal")):
        return "decimal"
    if "bool" in raw:
        return "boolean"
    if any(k in raw for k in ("datetime", "date")):
        return "datetime"
    if "uuid" in raw:
        return "uuid"
    return "string"


def _ts_type(raw: str | None) -> str:
    if not raw:
        return "string"
    raw = raw.strip().lower()
    if "number" in raw or "bigint" in raw:
        return "integer"
    if "boolean" in raw:
        return "boolean"
    if any(k in raw for k in ("date", "time")):
        return "datetime"
    if "[]" in raw or "array" in raw or "any" in raw:
        return "json"
    return "string"


def _json_type(value) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "decimal"
    if isinstance(value, str):
        return "string"
    return "json"


# --------------------------------------------------------------------------
# Python (tree-sitter-python)
# --------------------------------------------------------------------------


def _parse_python(path: str, text: str) -> FileExtraction:
    parser = Parser(_PY_LANGUAGE)
    tree = parser.parse(text.encode("utf-8"))
    root = tree.root_node
    imports = _python_imports(root)
    symbols: list[ParsedSymbol] = []
    queries: list[ParsedQuery] = []
    # Classe aninhada nunca é entidade: em Python ela é configuração do que a
    # contém (`class Meta` do Django/DRF é o caso canônico) e virava a tabela
    # `metas`.
    candidatos = [cd for cd in _find_all(root, "class_definition") if not _dentro_de_outra_classe(cd)]
    # Python não tem anotação de entidade para consultar, então a política cai no
    # modo por nome — o mesmo `domain_entity` que serve Java e C#, em vez de uma
    # regra paralela só para cá.
    de_dominio = selecionar_por_anotacao(
        {
            nome: set(_python_decoradores(cd))
            for cd in candidatos
            if (nome := _python_class_name(cd)) is not None
        },
        path,
        # Python não anota entidade; quem declara é a superclasse.
        bases={
            nome: _python_bases(cd)
            for cd in candidatos
            if (nome := _python_class_name(cd)) is not None
        },
    )
    for cd in candidatos:
        if _python_class_name(cd) not in de_dominio:
            continue
        symbol = _python_class(cd, path)
        if symbol is not None:
            symbols.append(symbol)
    for string_node in _find_all(root, "string"):
        queries.extend(_sql_from_string(string_node, path))
    return FileExtraction(path=path, language="python", text=text, imports=imports, symbols=symbols, queries=queries)


def _python_bases(cd: Node) -> list[str]:
    """Superclasses declaradas: `class User(Base)` -> `["Base"]`."""
    argumentos = cd.child_by_field_name("superclasses")
    if argumentos is None:
        return []
    return [
        _node_text(filho)
        for filho in argumentos.named_children
        if filho.type in ("identifier", "attribute", "dotted_name")
    ]


def _python_class_name(cd: Node) -> str | None:
    name_node = cd.child_by_field_name("name")
    return _node_text(name_node) if name_node is not None else None


def _dentro_de_outra_classe(cd: Node) -> bool:
    pai = cd.parent
    while pai is not None:
        if pai.type == "class_definition":
            return True
        pai = pai.parent
    return False


def _python_decoradores(cd: Node) -> list[str]:
    pai = cd.parent
    if pai is None or pai.type != "decorated_definition":
        return []
    nomes = []
    for filho in pai.children:
        if filho.type == "decorator":
            texto = _node_text(filho).lstrip("@").split("(")[0].strip()
            nomes.append(texto.rsplit(".", 1)[-1])
    return nomes


def _python_imports(root: Node) -> list[str]:
    out: list[str] = []
    for imp in _find_all(root, "import_statement"):
        for child in imp.children:
            if child.type == "dotted_name":
                out.append(_node_text(child))
    for impf in _find_all(root, "import_from_statement"):
        module = _import_from_module(impf)
        if module:
            out.append(module)
    return list(dict.fromkeys(out))


def _import_from_module(impf: Node) -> str | None:
    for child in impf.children:
        if child.type == "relative_import":
            prefix = ""
            dotted = ""
            for part in child.children:
                if part.type == "import_prefix":
                    prefix = _node_text(part)
                elif part.type == "dotted_name":
                    dotted = _node_text(part)
            return (prefix + dotted) if dotted else prefix
    for child in impf.children:
        if child.type == "dotted_name":
            return _node_text(child)
    return None


def _python_class(cd: Node, path: str) -> ParsedSymbol | None:
    name_node = cd.child_by_field_name("name")
    if name_node is None:
        return None
    name = _node_text(name_node)
    parent = cd.parent
    line_start = cd.start_point.row + 1
    decorators: list[str] = []
    if parent is not None and parent.type == "decorated_definition":
        line_start = parent.start_point.row + 1
        for child in parent.children:
            if child.type == "decorator":
                inner = " ".join(_node_text(c) for c in child.children if c.type != "@")
                decorators.append(inner)

    bases: list[str] = []
    for child in cd.children:
        if child.type == "argument_list":
            for base in child.children:
                if base.type in ("identifier", "attribute"):
                    bases.append(_node_text(base))

    # Antes de percorrer os filhos: iterar `block.children` invalida `cd` nesta
    # versão do py-tree-sitter, e ler seus pontos depois é use-after-free.
    line_end = cd.end_point.row + 1
    block = cd.child_by_field_name("body")
    fields: list[ParsedField] = []
    table_override: str | None = None
    for stmt in block.children if block is not None else []:
        if stmt.type != "expression_statement":
            continue
        assign = next((c for c in stmt.children if c.type == "assignment"), None)
        if assign is None:
            continue
        left = assign.child_by_field_name("left")
        if left is None or left.type != "identifier":
            continue
        field_name = _node_text(left)
        line = assign.start_point.row + 1
        if field_name == "__tablename__":
            for child in assign.children:
                if child.type == "string":
                    table_override = _unquote(_node_text(child))
            continue
        if field_name.startswith("_") or field_name in ("self", "cls"):
            continue
        if _python_e_navegacao(assign):
            continue
        fields.append(_python_field(assign, field_name, line))

    return ParsedSymbol(
        kind="class",
        name=name,
        fields=fields,
        bases=bases,
        decorators=decorators,
        table_name_override=table_override,
        line_start=line_start,
        line_end=line_end,
        path=path,
    )


# Construtores de ORM que declaram navegação entre entidades, não coluna: viram
# atributo da classe igual a uma coluna, mas não existem no banco. Sem filtrar,
# `enderecos = relationship("Endereco")` sai como coluna `enderecos` no CREATE
# TABLE de `clientes` — e a relação real já vem da coluna com ForeignKey, que é
# declarada à parte. Mesma família do `static final` do Java virando coluna.
_PY_CHAMADAS_DE_NAVEGACAO = ("relationship", "backref", "association_proxy", "synonym")


def _python_e_navegacao(assign: Node) -> bool:
    right = assign.child_by_field_name("right")
    if right is None:
        right = next((c for c in assign.children if c.type == "call"), None)
    if right is None or right.type != "call":
        return False
    fn = right.child_by_field_name("function")
    if fn is None:
        return False
    # `relationship(...)` ou `orm.relationship(...)`: interessa o último segmento.
    nome = _node_text(fn).rsplit(".", 1)[-1]
    return nome in _PY_CHAMADAS_DE_NAVEGACAO


def _python_field(assign: Node, field_name: str, line: int) -> ParsedField:
    field = ParsedField(name=field_name, line=line)
    type_node = assign.child_by_field_name("type")
    right = next(
        (c for c in assign.children if c.type in ("call", "string", "integer", "float", "true", "false", "list", "dictionary", "none")),
        None,
    )
    col_call = _find_call(right, "Column") if right is not None else None
    tipo_por_construtor = _tipo_por_construtor(right)
    if col_call is not None:
        _apply_column_call(col_call, field)
    elif tipo_por_construtor is not None:
        field.data_type = tipo_por_construtor
    elif type_node is not None:
        field.data_type = _py_type(_node_text(type_node))
    else:
        field.data_type = _infer_default(right)
    return field


def _find_call(node: Node, func_name: str) -> Node | None:
    if node is None:
        return None
    if node.type == "call":
        fn = node.child_by_field_name("function") or (node.children[0] if node.children else None)
        if fn is not None and fn.type == "identifier" and _node_text(fn) == func_name:
            return node
    for child in node.children:
        found = _find_call(child, func_name)
        if found is not None:
            return found
    return None


def _apply_column_call(call: Node, field: ParsedField) -> None:
    args = call.child_by_field_name("arguments")
    if args is None:
        return
    for arg in args.children:
        if arg.type == "identifier":
            field.data_type = _py_type(_node_text(arg))
            continue
        if arg.type == "call":
            fn = arg.children[0] if arg.children else None
            if fn is not None and fn.type == "identifier" and _node_text(fn) == "ForeignKey":
                target = _string_arg(arg)
                if target:
                    field.fk_target = target
            continue
        if arg.type == "keyword_argument":
            key = arg.child_by_field_name("name")
            value = arg.child_by_field_name("value")
            if key is None or value is None:
                continue
            name = _node_text(key)
            raw = _node_text(value).lower()
            if name == "primary_key":
                field.primary_key = raw == "true"
            elif name == "nullable":
                field.nullable = raw != "false"
            elif name == "unique":
                field.unique = raw == "true"


def _string_arg(node: Node) -> str | None:
    if node is None:
        return None
    if node.type == "string":
        return _unquote(_node_text(node))
    for child in node.children:
        found = _string_arg(child)
        if found is not None:
            return found
    return None


# Tipo a partir do sufixo do construtor de campo. `XxxField(...)` é convenção
# compartilhada por Django, Peewee, DRF, mongoengine e WTForms — é tabela de
# nomenclatura, não suporte a um ORM específico: nenhum nome de biblioteca
# aparece aqui, e a semântica de relacionamento continua fora.
#
# Sem isto, `created_at = models.DateTimeField(...)` e `is_active =
# models.BooleanField(...)` saíam ambos como "string".
_SUFIXOS_DE_CAMPO = (
    ("datetimefield", "datetime"),
    ("timestampfield", "datetime"),
    ("datefield", "date"),
    ("booleanfield", "boolean"),
    ("bigintegerfield", "integer"),
    ("smallintegerfield", "integer"),
    ("positiveintegerfield", "integer"),
    ("integerfield", "integer"),
    ("autofield", "integer"),
    ("decimalfield", "decimal"),
    ("floatfield", "decimal"),
    ("uuidfield", "uuid"),
    ("jsonfield", "json"),
    ("charfield", "string"),
    ("textfield", "string"),
    ("emailfield", "string"),
    ("urlfield", "string"),
    ("slugfield", "string"),
    ("filefield", "string"),
    ("imagefield", "string"),
)


def _tipo_por_construtor(right: Node | None) -> str | None:
    """`models.DateTimeField(...)` -> "datetime". `None` quando não reconhece."""
    if right is None or right.type != "call":
        return None
    fn = right.child_by_field_name("function")
    if fn is None:
        return None
    nome = _node_text(fn).rsplit(".", 1)[-1].lower()
    for sufixo, tipo in _SUFIXOS_DE_CAMPO:
        if nome.endswith(sufixo):
            return tipo
    return None


def _infer_default(right: Node | None) -> str:
    if right is None:
        return "string"
    if right.type == "integer":
        return "integer"
    if right.type == "float":
        return "decimal"
    if right.type in ("true", "false"):
        return "boolean"
    if right.type in ("list", "dictionary", "set", "tuple"):
        return "json"
    return "string"


# --------------------------------------------------------------------------
# TypeScript / JavaScript (tree-sitter-typescript)
# --------------------------------------------------------------------------


def _parse_typescript(path: str, text: str, language: str) -> FileExtraction:
    parser = Parser(_TSX_LANGUAGE if language in ("tsx", "jsx") else _TS_LANGUAGE)
    tree = parser.parse(text.encode("utf-8"))
    root = tree.root_node
    imports = _ts_imports(root)
    candidatos: list[ParsedSymbol] = []
    for tipo, extrator in (
        ("interface_declaration", _ts_interface),
        ("class_declaration", _ts_class),
        ("type_alias_declaration", _ts_type_alias),
    ):
        for n in _find_all(root, tipo):
            symbol = extrator(n, path)
            if symbol is not None:
                candidatos.append(symbol)

    # O filtro de domínio estava ligado em Python, Java e C#, e **não** aqui —
    # omissão. Sem ele, DTO, ROI, decorador de config e classe de teste viravam
    # entidade: 17 falsas num único projeto NestJS.
    de_dominio = selecionar_por_anotacao(
        {s.name: set(s.decorators) for s in candidatos}, path
    )
    symbols = [s for s in candidatos if s.name in de_dominio]
    queries: list[ParsedQuery] = []
    for string_node in _find_all(root, "string"):
        queries.extend(_sql_from_string(string_node, path))
    return FileExtraction(path=path, language=language, text=text, imports=imports, symbols=symbols, queries=queries)


def _ts_imports(root: Node) -> list[str]:
    out: list[str] = []
    for imp in _find_all(root, "import_statement"):
        for child in imp.children:
            if child.type == "string":
                out.append(_unquote(_node_text(child)))
    return list(dict.fromkeys(out))


def _ts_interface(n: Node, path: str) -> ParsedSymbol | None:
    name_node = n.child_by_field_name("name")
    if name_node is None:
        return None
    body = n.child_by_field_name("body")
    fields = [_ts_property(p) for p in body.children if p.type == "property_signature"] if body is not None else []
    return ParsedSymbol(
        kind="interface",
        name=_node_text(name_node),
        fields=fields,
        line_start=n.start_point.row + 1,
        line_end=n.end_point.row + 1,
        path=path,
    )


def _ts_decoradores(n: Node) -> tuple[list[str], str | None]:
    """Decoradores da classe e o nome de tabela declarado, se houver.

    Em TypeScript o decorador é irmão da declaração dentro do nó pai, não filho
    dela — por isso `n.children` não os acha e é preciso subir. Sem ler isto, o
    `@Entity('article')` do TypeORM era ignorado e a tabela saía `article_entities`
    (plural do nome da classe), enquanto Java já lia `@Table` e C# `[Table]`.
    """
    pai = n.parent
    if pai is None:
        return [], None
    nomes: list[str] = []
    declarado: str | None = None
    for irmao in pai.children:
        if irmao.type != "decorator" or irmao.start_point.row > n.start_point.row:
            continue
        texto = _node_text(irmao).lstrip("@").strip()
        nome = texto.split("(")[0].strip().rsplit(".", 1)[-1]
        nomes.append(nome)
        if nome in ("Entity", "Table") and "(" in texto:
            dentro = texto[texto.find("(") + 1 : texto.rfind(")")].strip()
            valor = _unquote(dentro.split(",")[0].strip())
            # `@Entity()` sem argumento, ou com objeto de opções, não declara nome.
            if valor and not valor.startswith("{"):
                declarado = valor
    return nomes, declarado


def _ts_class(n: Node, path: str) -> ParsedSymbol | None:
    name_node = n.child_by_field_name("name")
    if name_node is None:
        return None
    body = n.child_by_field_name("body")
    fields: list[ParsedField] = []
    if body is not None:
        for pd in body.children:
            if pd.type == "public_field_definition":
                fields.append(_ts_public_field(pd))
    decoradores, nome_declarado = _ts_decoradores(n)
    return ParsedSymbol(
        kind="class",
        name=_node_text(name_node),
        fields=fields,
        decorators=decoradores,
        table_name_override=nome_declarado,
        line_start=n.start_point.row + 1,
        line_end=n.end_point.row + 1,
        path=path,
    )


def _ts_type_alias(n: Node, path: str) -> ParsedSymbol | None:
    name_node = n.child_by_field_name("name")
    value = n.child_by_field_name("value")
    if name_node is None or value is None or value.type != "object_type":
        return None
    fields = [_ts_property(p) for p in value.children if p.type == "property_signature"]
    return ParsedSymbol(
        kind="type",
        name=_node_text(name_node),
        fields=fields,
        line_start=n.start_point.row + 1,
        line_end=n.end_point.row + 1,
        path=path,
    )


def _ts_property(prop: Node) -> ParsedField:
    name_node = prop.child_by_field_name("name")
    type_node = prop.child_by_field_name("type")
    name = _node_text(name_node) if name_node is not None else ""
    raw = type_node.text.decode(errors="replace") if type_node is not None else ""
    field = ParsedField(name=name, data_type=_ts_type(raw), line=prop.start_point.row + 1)
    if name == "id":
        field.primary_key = True
    return field


def _ts_public_field(pd: Node) -> ParsedField:
    name_node = pd.child_by_field_name("name")
    type_node = pd.child_by_field_name("type")
    name = _node_text(name_node) if name_node is not None else ""
    raw = type_node.text.decode(errors="replace") if type_node is not None else ""
    field = ParsedField(name=name, data_type=_ts_type(raw), line=pd.start_point.row + 1)
    if name == "id":
        field.primary_key = True
    return field


# --------------------------------------------------------------------------
# SQL (sqlglot)
# --------------------------------------------------------------------------


def _parse_sql(path: str, text: str) -> FileExtraction:
    try:
        statements = sqlglot.parse(text)
    except Exception:  # noqa: BLE001 - sql inválido não deve derrubar o pipeline
        return FileExtraction(path=path, language="sql", text=text)
    tables: list[ParsedTable] = []
    queries: list[ParsedQuery] = []
    alters: list[ParsedAlter] = []
    offset = 0
    for stmt in statements or []:
        if stmt is None:
            continue
        if isinstance(stmt, exp.Create):
            table = _sql_create_table(stmt, path, text, offset)
            if table is not None:
                tables.append(table)
                # `offset` é posição de CARACTERE (é o que `_locate` recebe como
                # `start`). Aqui ele recebia `line_end`, um número de LINHA — o que
                # jogava a busca de volta para perto do início do arquivo e fazia
                # todo ALTER seguinte ser atribuído à linha errada.
                #
                # O teste que cobria isso usava um arquivo só de ALTERs, sem CREATE,
                # então o bug nunca aparecia: precisa dos dois misturados, que é
                # como migration de verdade se parece.
                offset = _fim_do_statement(text, table.name, offset)
            continue
        if isinstance(stmt, exp.Drop) and (stmt.args.get("kind") or "").upper() == "TABLE":
            # `DROP TABLE x` era simplesmente ignorado, e a tabela sobrevivia no
            # modelo mesmo quando o DDL dizia que ela deixou de existir.
            nome = getattr(stmt.this, "name", None)
            if nome:
                linha, pos = _locate(text, ["drop"], offset)
                if pos >= 0:
                    offset = pos + len("drop")
                alters.append(ParsedAlter(table=nome, action="drop_table", line=linha, path=path))
            continue
        if isinstance(stmt, exp.Alter):
            renomeada = _sql_rename_table(stmt)
            if renomeada is not None:
                antiga, nova = renomeada
                linha, pos = _locate(text, ["alter"], offset)
                if pos >= 0:
                    offset = pos + len("alter")
                alters.append(
                    ParsedAlter(table=antiga, action="rename_table", new_name=nova, line=linha, path=path)
                )
                continue
            line, pos = _locate(text, ["alter"], offset)
            # Avançar o offset é o que faz o próximo ALTER achar a *próxima*
            # ocorrência: sem isso todos eles reencontravam o primeiro e o
            # arquivo inteiro de migration era reportado numa linha só.
            if pos >= 0:
                offset = pos + len("alter")
            alters.extend(_sql_alter_table(stmt, path, line))
            continue
        kind = _stmt_kind(stmt)
        if kind is None:
            continue
        line, pos = _locate(text, [kind], offset)
        if pos >= 0:
            offset = pos + len(kind)
        end_line, end_pos = _locate(text, [";"], offset)
        tables_in = list(dict.fromkeys(t.name for t in stmt.find_all(exp.Table)))
        queries.append(ParsedQuery(kind=kind, tables=tables_in, line=line, line_end=end_line if end_pos >= 0 else line, path=path))
    return FileExtraction(path=path, language="sql", text=text, tables=tables, queries=queries, alters=alters)


def _sql_rename_table(stmt: exp.Alter) -> tuple[str, str] | None:
    """`ALTER TABLE antiga RENAME TO nova` -> (antiga, nova); qualquer outra coisa -> None.

    O sqlglot representa isso como uma ação `exp.AlterRename` (ou `exp.RenameTable`,
    conforme a versão) dentro do ALTER, então cobrir os dois nomes evita depender
    da versão instalada.
    """
    antiga = getattr(stmt.this, "name", None)
    if not antiga:
        return None
    for action in stmt.args.get("actions") or []:
        classe = type(action).__name__
        if classe in ("AlterRename", "RenameTable"):
            alvo = action.this if hasattr(action, "this") else None
            nova = getattr(alvo, "name", None) or getattr(action.args.get("to"), "name", None)
            if nova:
                return antiga, nova
    return None


def _sql_alter_table(stmt: exp.Alter, path: str, line: int) -> list[ParsedAlter]:
    """Extrai ADD/DROP/RENAME COLUMN de um ALTER TABLE (sqlglot já estrutura isso)."""
    table_name = getattr(stmt.this, "name", None)
    if not table_name:
        return []
    out: list[ParsedAlter] = []
    for action in stmt.args.get("actions") or []:
        if isinstance(action, exp.ColumnDef):
            column = _sql_column(action)
            if column is not None:
                out.append(ParsedAlter(table=table_name, action="add_column", column=column, line=line, path=path))
        elif isinstance(action, exp.Drop) and (action.args.get("kind") or "").upper() == "COLUMN":
            col_name = getattr(action.this, "name", None)
            if col_name:
                out.append(ParsedAlter(table=table_name, action="drop_column", column_name=col_name, line=line, path=path))
        elif isinstance(action, exp.RenameColumn):
            old_name = getattr(action.this, "name", None)
            new_name = getattr(action.args.get("to"), "name", None)
            if old_name and new_name:
                out.append(
                    ParsedAlter(table=table_name, action="rename_column", old_name=old_name, new_name=new_name, line=line, path=path)
                )
    return out


def _stmt_kind(stmt) -> str | None:
    if isinstance(stmt, exp.Select):
        return "select"
    if isinstance(stmt, exp.Insert):
        return "insert"
    if isinstance(stmt, exp.Update):
        return "update"
    if isinstance(stmt, exp.Delete):
        return "delete"
    return None


def _sql_create_table(stmt: exp.Create, path: str, text: str, offset: int) -> ParsedTable | None:
    schema = stmt.this
    table = schema.this if isinstance(schema, exp.Schema) else schema
    name = getattr(table, "name", None)
    if not name:
        return None
    line, pos = _locate(text, [name], offset)
    columns: list[ParsedColumn] = []
    if isinstance(schema, exp.Schema):
        for entry in schema.expressions:
            if isinstance(entry, exp.ColumnDef):
                column = _sql_column(entry)
                if column is not None:
                    columns.append(column)
            else:
                _apply_sql_constraint(entry, columns)
    if not columns:
        return None
    # Sem `ensure_primary_key` aqui, de propósito: o DDL é autoritativo sobre as
    # chaves, inclusive sobre a ausência delas. `vet_specialties` do
    # spring-petclinic não declara PRIMARY KEY (a chave é `UNIQUE (vet_id,
    # specialty_id)`), e sintetizar um `id` inventava uma coluna que o banco real
    # não tem. Os outros chamadores continuam: lá a chave é modelagem nossa
    # (junção de `@JoinTable`, formulário HTML) e não declaração de ninguém.
    end_line, end_pos = _locate(text, [";"], pos)
    if end_pos < 0:
        end_line = line
    return ParsedTable(name=name, columns=columns, line_start=line, line_end=end_line, path=path)


def _sql_column(entry: exp.ColumnDef) -> ParsedColumn | None:
    name = getattr(entry, "name", None)
    if not name:
        return None
    column = ParsedColumn(name=name, data_type=sql_type_to_generic(entry.kind.sql()) if entry.kind else "string")
    for constraint in entry.constraints:
        kind = constraint.kind if isinstance(constraint, exp.ColumnConstraint) else constraint
        if isinstance(kind, exp.PrimaryKeyColumnConstraint):
            column.primary_key = True
            column.nullable = False
        elif isinstance(kind, exp.NotNullColumnConstraint):
            column.nullable = False
        elif isinstance(kind, exp.UniqueColumnConstraint):
            column.unique = True
        elif isinstance(kind, exp.Reference):
            table, col = _ref_target(kind)
            column.fk_table = table
            column.fk_column = col
    return column


def _apply_sql_constraint(entry, columns: list[ParsedColumn]) -> None:
    for pk in entry.find_all(exp.PrimaryKey):
        for col_expr in pk.args.get("expressions") or []:
            col = _col_by_name(columns, col_expr.name)
            if col is not None:
                col.primary_key = True
                col.nullable = False
    for fk in entry.find_all(exp.ForeignKey):
        ref = fk.args.get("reference")
        if ref is None:
            continue
        table, col = _ref_target(ref)
        for col_expr in fk.args.get("expressions") or []:
            target = _col_by_name(columns, col_expr.name)
            if target is not None:
                target.fk_table = table
                target.fk_column = col
    for unique in entry.find_all(exp.UniqueColumnConstraint):
        schema = unique.this
        if isinstance(schema, exp.Schema):
            for col_expr in schema.expressions:
                target = _col_by_name(columns, col_expr.name)
                if target is not None:
                    target.unique = True


def _col_by_name(columns: list[ParsedColumn], name: str) -> ParsedColumn | None:
    for column in columns:
        if column.name.lower() == name.lower():
            return column
    return None


def _ref_target(ref: exp.Reference) -> tuple[str | None, str | None]:
    target = ref.this
    if isinstance(target, exp.Schema):
        table_node = target.this
        table = getattr(table_node, "name", None) or str(table_node)
        cols = [c.name for c in target.expressions if isinstance(c, exp.Identifier)]
        return table, (cols[0] if cols else None)
    return getattr(target, "name", None) or str(target), None


def _fim_do_statement(text: str, nome: str, offset: int) -> int:
    """Posição de caractere logo após o `;` que fecha o statement de `nome`."""
    _, pos_nome = _locate(text, [nome], offset)
    if pos_nome < 0:
        return offset
    _, pos_fim = _locate(text, [";"], pos_nome)
    return pos_fim + 1 if pos_fim >= 0 else pos_nome + len(nome)


def _locate(text: str, needles: list[str], start: int = 0) -> tuple[int, int]:
    lowered = text.lower()
    best = -1
    for needle in needles:
        idx = lowered.find(needle.lower(), start)
        if idx != -1 and (best == -1 or idx < best):
            best = idx
    if best == -1:
        return 1, -1
    return text.count("\n", 0, best) + 1, best


# --------------------------------------------------------------------------
# JSON (stdlib)
# --------------------------------------------------------------------------


# Acima desta fração de valores aninhados, o objeto é um documento e não um
# registro. Medido: dado de exemplo de entidade real (`data/categoria.json`) tem
# **0%** de valores aninhados; dashboard do Grafana, 39%; template de aplicação,
# 100%. A folga entre os dois grupos é larga.
_MAX_FRACAO_ANINHADA = 1 / 3


def _dentro_de_diretorio_de_teste(path: str) -> bool:
    from importlib import import_module

    # `1_scan` comeca com digito e nao e identificador valido: `from ..1_scan`
    # nao compila, e `from ..ignore` aponta para um modulo que nao existe.
    ignore = import_module("app.pipeline.steps.1_scan.ignore")
    DIRETORIOS_DE_TESTE = ignore.DIRETORIOS_DE_TESTE

    partes = path.replace("\\", "/").split("/")[:-1]
    return any(parte.lower() in DIRETORIOS_DE_TESTE for parte in partes)


def _e_documento_e_nao_registro(data: dict) -> bool:
    """Distingue um registro de dado de um documento de configuração.

    O parser de JSON vira qualquer objeto em tabela, com cada chave de topo
    virando coluna. Isso está certo para `data/categoria.json`, que é uma amostra
    de entidade real, e errado para um dashboard do Grafana — que virava a
    entidade `battery_healths`, com `panels` e `templating` como colunas. Eram 23
    tabelas falsas no teslamate, que versiona 19 dashboards.

    O sinal é estrutural, como o limite de colunas logo acima, e não conhecimento
    de ferramenta: **registro tem valor escalar, documento tem valor aninhado.**
    Um registro com um campo de lista continua passando; um objeto em que mais de
    um terço das chaves aponta para outro objeto ou lista, não.
    """
    if not data:
        return False
    aninhados = sum(1 for valor in data.values() if isinstance(valor, (dict, list)))
    return aninhados / len(data) > _MAX_FRACAO_ANINHADA


def _parse_json(path: str, text: str) -> FileExtraction:
    try:
        data = json.loads(text)
    except (ValueError, json.JSONDecodeError):
        return FileExtraction(path=path, language="json", text=text)
    if not isinstance(data, dict):
        return FileExtraction(path=path, language="json", text=text)
    # Arquivo de dados não é entidade. `locales/en.json` do mastodon virou uma
    # tabela de 1.471 colunas e `emoji_map.json` de 5.043 — tabela real raramente
    # passa de algumas dezenas. É sinal estrutural, não conhecimento de framework.
    if len(data) > _MAX_COLUNAS_DE_JSON:
        return FileExtraction(path=path, language="json", text=text)
    if _e_documento_e_nao_registro(data):
        return FileExtraction(path=path, language="json", text=text)
    if _dentro_de_diretorio_de_teste(path):
        # Dado de teste informa, mas não AFIRMA. A fixture volta ao scan de
        # propósito — ela declara nomes de coluna, e é a evidência que sobra
        # quando o projeto não tem schema. Mas quem a lê é o LLM.
        #
        # No Rails isso já acontecia por acidente: Ruby não tem parser, então a
        # fixture caía em evidência bruta. Em JSON há parser, e `test-user.json`
        # virava a entidade `test_users` — nome que não existe no banco. O
        # contrato do sistema é o mesmo dos dois lados: evidência não vira tabela
        # sozinha.
        return FileExtraction(path=path, language="json", text=text)
    stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    columns = [ParsedColumn(name="id", data_type="integer", nullable=False, primary_key=True, line=1)]
    for key, value in data.items():
        columns.append(ParsedColumn(name=to_snake(key), data_type=_json_type(value), line=1))
    table = ParsedTable(name=table_name_for(stem), columns=columns, line_start=1, line_end=max(1, len(text.splitlines())), path=path)
    return FileExtraction(path=path, language="json", text=text, tables=[table])


# --------------------------------------------------------------------------
# SQL embutido em strings (Python/TS)
# --------------------------------------------------------------------------


def _sql_from_string(string_node: Node, path: str) -> list[ParsedQuery]:
    text = _node_text(string_node)
    inner = _unquote(text)
    if not inner or not _SQL_KEYWORD_RE.search(inner):
        return []
    try:
        statements = sqlglot.parse(inner)
    except Exception:  # noqa: BLE001 - string não-SQL não deve quebrar o parse
        return []
    out: list[ParsedQuery] = []
    for stmt in statements or []:
        if stmt is None:
            continue
        kind = _stmt_kind(stmt)
        if kind is None:
            continue
        tables = list(dict.fromkeys(t.name for t in stmt.find_all(exp.Table)))
        line = string_node.start_point.row + 1
        out.append(ParsedQuery(kind=kind, tables=tables, line=line, line_end=line, path=path))
    return out
