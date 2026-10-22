"""Parser para Protocol Buffers (.proto) -- sem regex: parsing manual linha-a-linha
com rastreio simples de profundidade de chaves (`str.count`), já que a sintaxe de
campo (`[repeated] tipo nome = N;`) é regular o suficiente pra não precisar de AST
completa. Mensagens aninhadas (message dentro de message) não são extraídas
separadamente -- limitação conhecida, aceitável pro escopo (entidades de domínio
raramente são mensagens aninhadas).
"""

from __future__ import annotations

from app.helpers.naming import table_name_for

from ..column_utils import ensure_primary_key
from ..parsed_types import FileExtraction, ParsedColumn, ParsedTable

_TYPE_MAP = {
    "double": "decimal",
    "float": "decimal",
    "int32": "integer",
    "int64": "integer",
    "uint32": "integer",
    "uint64": "integer",
    "sint32": "integer",
    "sint64": "integer",
    "fixed32": "integer",
    "fixed64": "integer",
    "sfixed32": "integer",
    "sfixed64": "integer",
    "bool": "boolean",
    "string": "string",
    "bytes": "string",
}


def parse_protobuf(path: str, text: str) -> FileExtraction | None:
    lines = text.splitlines()
    blocks = _find_message_blocks(lines)
    if not blocks:
        return None
    message_names = {name for name, _, _, _ in blocks}
    # Mesma ideia do filtro de entidade de domínio do Java (`domain_entity.py`),
    # com o sinal que o Protobuf oferece: mensagem que só existe como entrada ou
    # saída de um `rpc` é envelope de transporte, não entidade.
    entradas, retornos = _tipos_usados_em_rpc(lines)
    tables: list[ParsedTable] = []
    for name, body, line_start, line_end in blocks:
        if _e_envelope(name, body, message_names, entradas, retornos):
            continue
        table = _message_to_table(name, body, message_names, path, line_start, line_end)
        if table is not None:
            tables.append(table)
    if not tables:
        return None
    return FileExtraction(path=path, language="protobuf", text=text, tables=tables)


def _tipos_usados_em_rpc(lines: list[str]) -> tuple[set[str], set[str]]:
    """Tipos citados em `rpc Nome(Entrada) returns (Saida);`, separados por posição.

    A posição importa: o parâmetro de entrada é sempre envelope de transporte,
    mas o retorno com frequência é a própria entidade (`returns (Artista)`).
    """
    entradas: set[str] = set()
    retornos: set[str] = set()
    for raw in lines:
        texto = raw.split("//", 1)[0].strip()
        if not texto.startswith("rpc "):
            continue
        partes = texto.split("(")
        if len(partes) >= 2:
            entradas.add(partes[1].split(")")[0].strip().split(".")[-1])
        if len(partes) >= 3:
            retornos.add(partes[2].split(")")[0].strip().split(".")[-1])
    return entradas - {""}, retornos - {""}


def _e_envelope(
    name: str, body: list[tuple[int, str]], message_names: set[str], entradas: set[str], retornos: set[str]
) -> bool:
    """Se a mensagem é transporte de RPC em vez de entidade de domínio.

    Duas regras, ambas conservadoras — na dúvida, mantém como entidade, porque
    perder uma entidade real é pior que deixar passar um envelope (que o estágio
    do LLM ainda pode descartar):

    1. **Parâmetro de entrada de um `rpc`** — sempre envelope.
    2. **Retorno que só embrulha uma lista de outra mensagem** — o formato
       `repeated Album albuns; int32 total;` é paginação, não entidade. Exige o
       campo repetido de outra mensagem; entidade devolvida direto pelo rpc
       (`returns (Artista)`, campos escalares) não se encaixa e é preservada.
    """
    if name in entradas:
        return True
    if name not in retornos:
        return False
    return any(
        parsed is not None and parsed[2] and parsed[1] in message_names
        for parsed in (_field_line(raw) for _, raw in body)
    )


def _find_message_blocks(lines: list[str]) -> list[tuple[str, list[tuple[int, str]], int, int]]:
    blocks: list[tuple[str, list[tuple[int, str]], int, int]] = []
    i = 0
    n = len(lines)
    while i < n:
        stripped = lines[i].strip()
        if stripped.startswith("message ") and stripped.endswith("{"):
            name = stripped[len("message "):-1].strip()
            depth = 1
            body: list[tuple[int, str]] = []
            j = i + 1
            while j < n and depth > 0:
                line = lines[j]
                s = line.strip()
                opens = s.count("{")
                closes = s.count("}")
                if depth == 1 and opens == 0:
                    body.append((j + 1, line))
                depth += opens - closes
                j += 1
            blocks.append((name, body, i + 1, j))
            i = j
            continue
        i += 1
    return blocks


def _message_to_table(
    name: str, body: list[tuple[int, str]], message_names: set[str], path: str, line_start: int, line_end: int
) -> ParsedTable | None:
    columns: list[ParsedColumn] = []
    for line_no, raw in body:
        parsed = _field_line(raw)
        if parsed is None:
            continue
        field_name, field_type, is_repeated = parsed
        if field_type in message_names:
            continue  # campo de relação (objeto/lista) -- sem coluna própria
        data_type = "json" if is_repeated else _TYPE_MAP.get(field_type, "string")
        columns.append(ParsedColumn(name=field_name, data_type=data_type, line=line_no))
    if not columns:
        return None
    ensure_primary_key(columns)
    return ParsedTable(name=table_name_for(name), columns=columns, line_start=line_start, line_end=line_end, path=path)


def _field_line(line: str) -> tuple[str, str, bool] | None:
    text = line.split("//", 1)[0].strip()  # remove comentário de fim de linha (split simples, não regex)
    if not text or not text.endswith(";"):
        return None
    if text.startswith(("option ", "reserved ", "oneof ", "message ", "enum ")):
        return None
    text = text[:-1].strip()
    if text.startswith("map<") or " map<" in text:
        return None  # tipo map<K,V> tem sintaxe própria -- fora de escopo, não vira coluna
    tokens = text.replace("=", " = ").split()
    is_repeated = False
    if tokens and tokens[0] == "repeated":
        is_repeated = True
        tokens = tokens[1:]
    if len(tokens) < 3 or tokens[-2] != "=":
        return None
    field_type, field_name = tokens[0], tokens[1]
    return field_name, field_type, is_repeated
