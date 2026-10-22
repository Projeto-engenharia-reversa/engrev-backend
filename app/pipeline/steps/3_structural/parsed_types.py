"""Estruturas intermediárias compartilhadas por todos os parsers da etapa `structural`
(AST por linguagem em `parsers.py` e os parsers de formato de schema em
`schema_formats/`). Vive num módulo neutro pra evitar import circular: os parsers de
formato importam daqui, e `parsers.py` importa os parsers de formato pra despachar.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ParsedField:
    name: str
    data_type: str = "string"
    line: int = 1
    primary_key: bool = False
    nullable: bool = True
    unique: bool = False
    fk_target: str | None = None


@dataclass
class ParsedSymbol:
    kind: str
    name: str
    fields: list[ParsedField] = field(default_factory=list)
    bases: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    table_name_override: str | None = None
    line_start: int = 1
    line_end: int = 1
    path: str = ""


@dataclass
class ParsedColumn:
    name: str
    data_type: str = "string"
    line: int = 1
    nullable: bool = True
    primary_key: bool = False
    unique: bool = False
    fk_table: str | None = None
    fk_column: str | None = None


@dataclass
class ParsedTable:
    name: str
    columns: list[ParsedColumn] = field(default_factory=list)
    line_start: int = 1
    line_end: int = 1
    path: str = ""
    # Herança: `classe` é o nome do tipo que originou a tabela e `bases` são as
    # superclasses dele. Guardados como nome de CLASSE, não de tabela, porque a
    # superclasse costuma morar noutro arquivo e o nome de tabela dela só se
    # conhece depois que tudo foi coletado — a resolução acontece no grafo.
    # `ParsedSymbol` já tinha `bases`; aqui faltava, e por isso Java e C# não
    # herdavam coluna nenhuma.
    classe: str | None = None
    bases: list[str] = field(default_factory=list)
    # Classe-base (`@MappedSuperclass`) existe SÓ para emprestar colunas: ela não
    # é tabela, mas as colunas dela pertencem a quem herda. Sem este canal a
    # exclusão apagava as colunas junto — `first_name`/`last_name` de `Person`
    # sumiam de `owners` e `vets` no petclinic sem DDL.
    apenas_heranca: bool = False


@dataclass
class ParsedQuery:
    kind: str = "select"
    tables: list[str] = field(default_factory=list)
    line: int = 1
    line_end: int = 1
    path: str = ""


@dataclass
class ParsedAlter:
    """Uma ação de ALTER TABLE / operação incremental de migration (add/drop/rename
    coluna, ou adicionar FK a uma coluna já existente — usado pelo `addForeignKeyConstraint`
    do Liquibase, que referencia uma coluna definida em outro changeset)."""

    table: str
    # "add_column" | "drop_column" | "rename_column" | "add_fk"
    # | "drop_table" | "rename_table"  -- ver `_tabelas_efemeras` em graph.py
    action: str
    column: ParsedColumn | None = None  # para add_column (reaproveita o parser de coluna)
    column_name: str | None = None  # para drop_column e add_fk (nome da coluna alvo)
    old_name: str | None = None  # para rename_column
    new_name: str | None = None  # para rename_column
    fk_table: str | None = None  # para add_fk
    fk_column: str | None = None  # para add_fk
    line: int = 1
    path: str = ""


@dataclass
class FileExtraction:
    path: str
    language: str
    text: str = ""
    imports: list[str] = field(default_factory=list)
    symbols: list[ParsedSymbol] = field(default_factory=list)
    tables: list[ParsedTable] = field(default_factory=list)
    queries: list[ParsedQuery] = field(default_factory=list)
    alters: list[ParsedAlter] = field(default_factory=list)
    # Classes que ESTE arquivo declara serem entidades persistidas, mas que são
    # DEFINIDAS em outro. É o caso do MyBatis: o mapeamento vive num XML e a
    # classe, num `.java`. Sem esse canal a declaração não atravessa a fronteira
    # do arquivo, e o parser de Java cai no modo permissivo.
    entidades_declaradas: list[str] = field(default_factory=list)
