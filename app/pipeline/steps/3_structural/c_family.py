"""Extração estrutural para Java e C# via tree-sitter.

Java e C# têm formato de AST bem diferente pra campo/propriedade + anotação
(confirmado empiricamente antes de escrever este módulo -- Java aninha anotações
dentro de um nó `modifiers`; C# tem `attribute_list` como irmão do `modifier`, não
aninhado), então cada linguagem tem sua própria função de extração em vez de um
único "walker" genérico forçado a servir as duas. O que É de fato compartilhado e
genérico entre as duas: o mapeamento de nome de anotação/atributo -> papel
semântico (PK/FK/relação), e os utilitários de tipo/coluna.

Cobre o estilo de anotação/atributo direto no campo (JPA em Java, Data
Annotations em C#). NÃO cobre EF Core Fluent API (relação declarada em corpo de
método via `modelBuilder.Entity<T>()...`) -- isso exigiria análise de corpo de
método, fora de escopo desta fase (documentado no plano).
"""

from __future__ import annotations

import tree_sitter_c_sharp
import tree_sitter_java
from tree_sitter import Language, Node, Parser

from app.helpers.naming import fk_name_for, table_name_for, to_snake

from .column_utils import ensure_primary_key
from .domain_entity import ANOTACOES_DE_ENTIDADE, ANOTACOES_DE_SUPERCLASSE, selecionar_por_anotacao
from .parsed_types import FileExtraction, ParsedColumn, ParsedTable

_JAVA_LANGUAGE = Language(tree_sitter_java.language())
_CSHARP_LANGUAGE = Language(tree_sitter_c_sharp.language())

# Anotação/atributo -> papel semântico (nome sem prefixo de pacote/namespace).
_PK_NAMES = {"Id", "Key"}
_RELATION_NAMES = {"ManyToOne", "OneToOne"}
_COLLECTION_RELATION_NAMES = {"OneToMany", "ManyToMany"}
_FK_COLUMN_NAMES = {"JoinColumn", "ForeignKey"}

_JAVA_TYPE_MAP = {
    "String": "string",
    "int": "integer",
    "Integer": "integer",
    "long": "integer",
    "Long": "integer",
    "short": "integer",
    "Short": "integer",
    "float": "decimal",
    "Float": "decimal",
    "double": "decimal",
    "Double": "decimal",
    "BigDecimal": "decimal",
    "boolean": "boolean",
    "Boolean": "boolean",
    "LocalDate": "date",
    "LocalDateTime": "datetime",
    "Date": "datetime",
    "Instant": "datetime",
    "UUID": "uuid",
}

_CSHARP_TYPE_MAP = {
    "string": "string",
    "int": "integer",
    "long": "integer",
    "short": "integer",
    "byte": "integer",
    "float": "decimal",
    "double": "decimal",
    "decimal": "decimal",
    "bool": "boolean",
    "DateTime": "datetime",
    "DateOnly": "date",
    "DateTimeOffset": "datetime",
    "Guid": "uuid",
}


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


def _collection_element_type(raw_type: str) -> str | None:
    """`List<Pedido>`/`Set<Pedido>`/`ICollection<Pedido>`/`Pedido[]` -> `Pedido`."""
    raw_type = raw_type.strip()
    if raw_type.endswith("[]"):
        return raw_type[:-2].strip() or None
    if "<" in raw_type and raw_type.endswith(">"):
        return raw_type[raw_type.find("<") + 1 : -1].strip() or None
    return None


# --------------------------------------------------------------------------
# Java (tree-sitter-java, anotações estilo JPA/Hibernate)
# --------------------------------------------------------------------------


def parse_java(path: str, text: str) -> FileExtraction | None:
    parser = Parser(_JAVA_LANGUAGE)
    tree = parser.parse(text.encode("utf-8"))
    root = tree.root_node
    class_nodes = _find_all(root, "class_declaration")
    class_names = {_java_class_name(cd) for cd in class_nodes} - {None}

    # Sem esse filtro, `@Service` e `@RestController` viravam tabelas com as
    # dependências injetadas como colunas.
    anotacoes_por_classe = {
        nome: _java_class_annotations(cd)
        for cd in class_nodes
        if (nome := _java_class_name(cd)) is not None
    }
    de_dominio = selecionar_por_anotacao(anotacoes_por_classe, path)

    # `@Table(name = "...")` dá o nome autoritativo; sem ele sobra pluralizar o
    # nome da classe, e `to_plural` é anglófono (`Autor` -> `autors`).
    nomes_de_tabela = {
        nome: _java_class_annotation_args(cd).get("Table") or table_name_for(nome)
        for cd in class_nodes
        if (nome := _java_class_name(cd)) is not None
    }

    tables: list[ParsedTable] = []
    for cd in class_nodes:
        nome_classe = _java_class_name(cd)
        if nome_classe not in de_dominio:
            # Classe-base entra assim mesmo, marcada: não vira tabela, mas as
            # colunas dela precisam chegar ao grafo para descer às subclasses.
            if anotacoes_por_classe.get(nome_classe, set()) & ANOTACOES_DE_SUPERCLASSE:
                base = _java_class_to_table(cd, class_names, nomes_de_tabela, path)
                if base is not None:
                    base.apenas_heranca = True
                    tables.append(base)
            continue
        marcada = bool(anotacoes_por_classe.get(nome_classe, set()) & ANOTACOES_DE_ENTIDADE)
        table = _java_class_to_table(cd, class_names, nomes_de_tabela, path, permitir_sem_colunas=marcada)
        if table is not None:
            tables.append(table)
        tables.extend(_java_tabelas_de_juncao(cd, class_names, nomes_de_tabela, path))
    if not tables:
        return None
    return FileExtraction(path=path, language="java", text=text, tables=tables)


def _java_tabelas_de_juncao(
    cd: Node, class_names: set[str], nomes_de_tabela: dict[str, str], path: str
) -> list[ParsedTable]:
    """Materializa a tabela de junção de um `@ManyToMany` com `@JoinTable`.

    Antes o lado "many" só devolvia `[]` e o relacionamento N:N sumia por
    completo do modelo. Em vez de inventar um tipo novo de relacionamento,
    sintetiza-se a tabela de junção — que existe de fato no banco. As duas FKs
    então percorrem a mesma máquina de qualquer outra tabela, e o resultado tem
    a mesma forma de uma associativa declarada explicitamente (como
    `itens_pedido`), que o pipeline já sabe interpretar.

    Só o lado dono da relação declara `@JoinTable`; o lado inverso usa
    `mappedBy`, então não há risco de gerar a junção duas vezes.

    A chave é o par das duas FKs. Sem marcá-la, a junção saía sem PK nenhuma — a
    Fase 5 acusava "tabela sem chave primária" num erro que o próprio pipeline
    tinha produzido, e o DDL aceitava o mesmo par repetido.
    """
    dono = _java_class_name(cd)
    if dono is None:
        return []
    body = cd.child_by_field_name("body")
    juncoes: list[ParsedTable] = []
    for field_decl in (body.children if body is not None else []):
        if field_decl.type != "field_declaration":
            continue
        # Capturado antes de descer nos filhos, pelo mesmo motivo de
        # `_java_class_to_table`: depois disso o nó não é mais confiável.
        linha = field_decl.start_point.row + 1
        linha_fim = field_decl.end_point.row + 1
        modifiers = next((c for c in field_decl.children if c.type == "modifiers"), None)
        if modifiers is None or "ManyToMany" not in _java_annotation_names(modifiers):
            continue
        join = _java_join_table(modifiers)
        if join is None:
            continue
        nome_juncao, coluna_dono, coluna_alvo = join
        type_node = field_decl.child_by_field_name("type")
        alvo = _collection_element_type(_node_text(type_node)) if type_node is not None else None
        if alvo is None:
            continue
        juncoes.append(
            ParsedTable(
                name=nome_juncao,
                columns=[
                    _java_coluna_de_juncao(coluna_dono, dono, nomes_de_tabela, linha),
                    _java_coluna_de_juncao(coluna_alvo, alvo, nomes_de_tabela, linha),
                ],
                line_start=linha,
                line_end=linha_fim,
                path=path,
            )
        )
    return juncoes


def _java_coluna_de_juncao(
    nome_coluna: str | None, entidade: str, nomes_de_tabela: dict[str, str], linha: int
) -> ParsedColumn:
    """Coluna de FK da junção apontando para `entidade`.

    Só preenche `fk_table` quando o nome real da tabela é conhecido — ou seja,
    quando a entidade está declarada neste mesmo arquivo e o `@Table` dela foi
    lido. Numa referência entre arquivos não dá para saber se a classe declara
    `@Table(name=...)`, e chutar com `table_name_for` produziria um alvo
    inexistente (`Autor` -> `autors`, quando a tabela é `autores`). Sem
    `fk_table`, a coluna fica e a heurística de nome tenta ligar — melhor que
    apontar para uma tabela que não existe.
    """
    return ParsedColumn(
        name=nome_coluna or fk_name_for(entidade),
        data_type="integer",
        nullable=False,
        primary_key=True,  # metade da chave composta da junção
        fk_table=nomes_de_tabela.get(entidade),
        fk_column="id" if entidade in nomes_de_tabela else None,
        line=linha,
    )


def _java_join_table(modifiers: Node) -> tuple[str, str | None, str | None] | None:
    """`@JoinTable(name=..., joinColumns=@JoinColumn(name=...), inverseJoinColumns=...)`.

    Os `@JoinColumn` internos são aninhados dentro do `@JoinTable`, e não irmãos
    dele — `_java_annotation_args`, que só olha os filhos diretos de `modifiers`,
    não os alcança.
    """
    for ann in modifiers.children:
        if ann.type != "annotation":
            continue
        nome_node = next((c for c in ann.children if c.type == "identifier"), None)
        if nome_node is None or _node_text(nome_node) != "JoinTable":
            continue
        arg_list = next((c for c in ann.children if c.type == "annotation_argument_list"), None)
        if arg_list is None:
            return None
        nome_juncao = None
        colunas: dict[str, str] = {}
        for pair in arg_list.children:
            if pair.type != "element_value_pair":
                continue
            chave_node = pair.child_by_field_name("key")
            valor_node = pair.child_by_field_name("value")
            if chave_node is None or valor_node is None:
                continue
            chave = _node_text(chave_node)
            if chave == "name":
                nome_juncao = _node_text(valor_node).strip('"')
            elif chave in ("joinColumns", "inverseJoinColumns"):
                interno = _java_nome_de_join_column(valor_node)
                if interno:
                    colunas[chave] = interno
        if nome_juncao:
            return nome_juncao, colunas.get("joinColumns"), colunas.get("inverseJoinColumns")
        return None
    return None


def _java_nome_de_join_column(node: Node) -> str | None:
    """Extrai `name` de um `@JoinColumn(name = "...")` aninhado."""
    for ann in _find_all(node, "annotation"):
        nome_node = next((c for c in ann.children if c.type == "identifier"), None)
        if nome_node is None or _node_text(nome_node) != "JoinColumn":
            continue
        arg_list = next((c for c in ann.children if c.type == "annotation_argument_list"), None)
        if arg_list is None:
            continue
        for pair in arg_list.children:
            if pair.type != "element_value_pair":
                continue
            chave_node = pair.child_by_field_name("key")
            valor_node = pair.child_by_field_name("value")
            if chave_node is not None and valor_node is not None and _node_text(chave_node) == "name":
                return _node_text(valor_node).strip('"')
    return None


def _java_class_annotations(cd: Node) -> set[str]:
    """Anotações da própria classe (irmãs da declaração, não dos campos)."""
    modifiers = next((c for c in cd.children if c.type == "modifiers"), None)
    return _java_annotation_names(modifiers) if modifiers is not None else set()


def _java_class_annotation_args(cd: Node) -> dict[str, str]:
    modifiers = next((c for c in cd.children if c.type == "modifiers"), None)
    return _java_annotation_args(modifiers) if modifiers is not None else {}


def _java_superclasses(cd: Node) -> list[str]:
    """Superclasse de `class X extends Y`. Em Java a herança de implementação é
    simples, então é no máximo uma — mas a lista mantém a forma igual à do C# e
    à do Python, que podem ter várias."""
    alvo = cd.child_by_field_name("superclass")
    if alvo is None:
        return []
    # O nó `superclass` inclui a palavra `extends`; o tipo é o filho identificador.
    tipos = [c for c in alvo.children if c.type in ("type_identifier", "scoped_type_identifier", "generic_type")]
    return [_node_text(t).split("<")[0].strip() for t in tipos] or []


def _csharp_bases(cd: Node) -> list[str]:
    """`class X : Base, IFoo` — o C# mistura superclasse e interface na mesma
    lista. Não dá para distinguir sem resolver os tipos, então voltam todas: a
    resolução no grafo só usa as que existirem como tabela, e interface não vira
    tabela."""
    lista = next((c for c in cd.children if c.type == "base_list"), None)
    if lista is None:
        return []
    nomes = []
    for filho in lista.children:
        if filho.type in ("identifier", "qualified_name", "generic_name"):
            nomes.append(_node_text(filho).split("<")[0].strip())
    return nomes


def _java_class_name(cd: Node) -> str | None:
    name_node = cd.child_by_field_name("name")
    return _node_text(name_node) if name_node is not None else None


def _java_class_to_table(
    cd: Node,
    class_names: set[str],
    nomes_de_tabela: dict[str, str],
    path: str,
    permitir_sem_colunas: bool = False,
) -> ParsedTable | None:
    name = _java_class_name(cd)
    if name is None:
        return None
    # Ler os pontos de `cd` ANTES de percorrer os filhos. Nesta versão do
    # py-tree-sitter, iterar `body.children` invalida o nó pai, e acessar
    # `cd.start_point` depois lê memória já liberada — segmentation fault, não
    # exceção. Só aparece com volume: precisa de alocação suficiente para o
    # bloco liberado ser reaproveitado, o que nenhum dos projetos de teste
    # pequenos alcançava. Reproduzido de forma consistente com 49 arquivos Java.
    linha_inicial = cd.start_point.row + 1
    linha_final = cd.end_point.row + 1
    body = cd.child_by_field_name("body")
    columns: list[ParsedColumn] = []
    for field_decl in (body.children if body is not None else []):
        if field_decl.type != "field_declaration":
            continue
        columns.extend(_java_field_columns(field_decl, class_names, nomes_de_tabela))
    # Classe marcada como entidade que só tem colunas herdadas (o `Vet` do
    # petclinic estende `Person` e declara só a relação N:N) precisa virar tabela
    # mesmo assim: descartá-la aqui é decidir antes de a herança acontecer, e ela
    # sumia do modelo inteira.
    if not columns and not permitir_sem_colunas:
        return None
    ensure_primary_key(columns)
    return ParsedTable(
        name=nomes_de_tabela.get(name, table_name_for(name)),
        columns=columns,
        line_start=linha_inicial,
        line_end=linha_final,
        path=path,
        classe=name,
        bases=_java_superclasses(cd),
    )


def _java_field_columns(
    field_decl: Node, class_names: set[str], nomes_de_tabela: dict[str, str]
) -> list[ParsedColumn]:
    modifiers = next((c for c in field_decl.children if c.type == "modifiers"), None)
    if modifiers is not None and _java_e_constante(modifiers):
        return []  # `static final` é constante da classe, não coluna
    annotation_names = _java_annotation_names(modifiers) if modifiers is not None else set()
    annotation_args = _java_annotation_args(modifiers) if modifiers is not None else {}

    type_node = field_decl.child_by_field_name("type")
    declarator = field_decl.child_by_field_name("declarator")
    name_node = declarator.child_by_field_name("name") if declarator is not None else None
    if name_node is None or type_node is None:
        return []
    field_name = _node_text(name_node)
    raw_type = _node_text(type_node)
    line = field_decl.start_point.row + 1

    if annotation_names & _COLLECTION_RELATION_NAMES:
        return []  # lado "many" da relação -- sem coluna própria

    element_type = _collection_element_type(raw_type)
    if element_type is not None:
        if element_type in class_names:
            return []  # coleção de outra entidade sem anotação -- mesmo assim, sem coluna
        return [ParsedColumn(name=to_snake(field_name), data_type="json", line=line)]  # coleção de tipo não reconhecido

    if annotation_names & _RELATION_NAMES or raw_type in class_names:
        fk_column_name = annotation_args.get("JoinColumn") or to_snake(field_name) + "_id"
        return [
            ParsedColumn(
                name=fk_column_name,
                data_type="integer",
                # Respeita o `@Table(name=...)` da entidade alvo em vez de
                # pluralizar o nome da classe.
                fk_table=nomes_de_tabela.get(raw_type, table_name_for(raw_type)),
                fk_column="id",
                line=line,
            )
        ]

    column_name = annotation_args.get("Column") or to_snake(field_name)
    return [
        ParsedColumn(
            name=column_name,
            data_type=_JAVA_TYPE_MAP.get(raw_type, "string"),
            primary_key="Id" in annotation_names,
            line=line,
        )
    ]


def _java_e_constante(modifiers: Node) -> bool:
    palavras = {c.type for c in modifiers.children}
    return "static" in palavras and "final" in palavras


def _java_annotation_names(modifiers: Node) -> set[str]:
    names: set[str] = set()
    for ann in modifiers.children:
        if ann.type not in ("annotation", "marker_annotation"):
            continue
        name_node = next((c for c in ann.children if c.type == "identifier"), None)
        if name_node is not None:
            names.add(_node_text(name_node))
    return names


def _java_annotation_args(modifiers: Node) -> dict[str, str]:
    """Extrai `name = "valor"` de dentro de `@Anotacao(name = "valor")` -- só o
    argumento `name`, que é o que usamos (nome de coluna/FK)."""
    args: dict[str, str] = {}
    for ann in modifiers.children:
        if ann.type != "annotation":
            continue
        name_node = next((c for c in ann.children if c.type == "identifier"), None)
        arg_list = next((c for c in ann.children if c.type == "annotation_argument_list"), None)
        if name_node is None or arg_list is None:
            continue
        ann_name = _node_text(name_node)
        for pair in arg_list.children:
            if pair.type != "element_value_pair":
                continue
            key_node = pair.child_by_field_name("key")
            value_node = pair.child_by_field_name("value")
            if key_node is None or value_node is None or _node_text(key_node) != "name":
                continue
            value = _node_text(value_node).strip("\"")
            args[ann_name] = value
    return args


# --------------------------------------------------------------------------
# C# (tree-sitter-c-sharp, atributos estilo EF Core Data Annotations)
# --------------------------------------------------------------------------


def parse_csharp(path: str, text: str) -> FileExtraction | None:
    parser = Parser(_CSHARP_LANGUAGE)
    tree = parser.parse(text.encode("utf-8"))
    root = tree.root_node
    class_nodes = _find_all(root, "class_declaration")
    class_names = {_csharp_class_name(cd) for cd in class_nodes} - {None}

    # `[Table("nome")]` é o nome autoritativo, como o `@Table` no Java.
    nomes_de_tabela = {
        nome: _csharp_class_table_name(cd) or table_name_for(nome)
        for cd in class_nodes
        if (nome := _csharp_class_name(cd)) is not None
    }

    # O C# não passava por filtro nenhum: DTO, envelope, o próprio DbContext e
    # classe de opções viravam entidade. Mesma política do Java — atributo quando
    # existe, nome quando não existe.
    de_dominio = selecionar_por_anotacao(
        {
            nome: _csharp_class_annotations(cd)
            for cd in class_nodes
            if (nome := _csharp_class_name(cd)) is not None
        },
        path,
    )

    tables: list[ParsedTable] = []
    for cd in class_nodes:
        if _csharp_class_name(cd) not in de_dominio:
            continue
        table = _csharp_class_to_table(cd, class_names, nomes_de_tabela, path)
        if table is not None:
            tables.append(table)
    if not tables:
        return None
    return FileExtraction(path=path, language="csharp", text=text, tables=tables)


def _csharp_class_annotations(cd: Node) -> set[str]:
    """Nomes dos atributos declarados na classe (`[Table]`, `[ApiController]`...)."""
    nomes: set[str] = set()
    for attr_list in (c for c in cd.children if c.type == "attribute_list"):
        encontrados, _args = _csharp_attributes(attr_list)
        nomes |= encontrados
    return nomes


def _csharp_class_table_name(cd: Node) -> str | None:
    """Valor de `[Table("nome")]` declarado na classe, se houver."""
    for attr_list in (c for c in cd.children if c.type == "attribute_list"):
        _nomes, args = _csharp_attributes(attr_list)
        if "Table" in args:
            return args["Table"]
    return None


def _csharp_class_name(cd: Node) -> str | None:
    name_node = cd.child_by_field_name("name")
    return _node_text(name_node) if name_node is not None else None


def _csharp_class_to_table(
    cd: Node, class_names: set[str], nomes_de_tabela: dict[str, str], path: str
) -> ParsedTable | None:
    name = _csharp_class_name(cd)
    if name is None:
        return None
    # Mesmo cuidado do caminho Java: pontos do nó lidos antes de tocar nos filhos.
    linha_inicial = cd.start_point.row + 1
    linha_final = cd.end_point.row + 1
    body = cd.child_by_field_name("body")
    properties = [c for c in (body.children if body is not None else []) if c.type in ("property_declaration", "field_declaration")]
    # Mapa nome-da-propriedade -> tipo bruto, usado pra resolver [ForeignKey("Nav")]
    # (o atributo referencia a propriedade de navegação, não a coluna FK em si).
    prop_types = {n: t for n, t in (_csharp_prop_name_type(p) for p in properties) if n is not None}
    columns: list[ParsedColumn] = []
    for prop in properties:
        columns.extend(_csharp_prop_columns(prop, class_names, prop_types, nomes_de_tabela))
    if not columns:
        return None
    ensure_primary_key(columns)
    return ParsedTable(
        name=nomes_de_tabela.get(name, table_name_for(name)),
        columns=columns,
        line_start=linha_inicial,
        line_end=linha_final,
        path=path,
        classe=name,
        bases=_csharp_bases(cd),
    )


def _csharp_prop_name_type(prop: Node) -> tuple[str | None, str | None]:
    name_node = prop.child_by_field_name("name")
    type_node = prop.child_by_field_name("type")
    if name_node is None or type_node is None:
        return None, None
    return _node_text(name_node), _node_text(type_node)


def _csharp_prop_columns(
    prop: Node, class_names: set[str], prop_types: dict[str, str], nomes_de_tabela: dict[str, str]
) -> list[ParsedColumn]:
    field_name, raw_type = _csharp_prop_name_type(prop)
    if field_name is None or raw_type is None:
        return []
    attr_list = next((c for c in prop.children if c.type == "attribute_list"), None)
    attribute_names, attribute_args = (_csharp_attributes(attr_list) if attr_list is not None else (set(), {}))
    line = prop.start_point.row + 1

    element_type = _collection_element_type(raw_type)
    if element_type is not None:
        if element_type in class_names:
            return []  # coleção de navegação (lado "many") -- sem coluna própria
        return [ParsedColumn(name=to_snake(field_name), data_type="json", line=line)]  # coleção de tipo não reconhecido
    if raw_type in class_names:
        return []  # propriedade de navegação (objeto) -- sem coluna própria

    if "ForeignKey" in attribute_args:
        nav_property = attribute_args["ForeignKey"]
        nav_type = prop_types.get(nav_property)
        return [
            ParsedColumn(
                name=to_snake(field_name),
                data_type=_CSHARP_TYPE_MAP.get(raw_type, "string"),
                # Respeita o `[Table]` da entidade de navegação.
                fk_table=nomes_de_tabela.get(nav_type, table_name_for(nav_type)) if nav_type else None,
                fk_column="id" if nav_type else None,
                line=line,
            )
        ]

    return [
        ParsedColumn(
            name=to_snake(field_name),
            data_type=_CSHARP_TYPE_MAP.get(raw_type, "string"),
            primary_key="Key" in attribute_names or to_snake(field_name) == "id",
            line=line,
        )
    ]


def _csharp_attributes(attr_list: Node) -> tuple[set[str], dict[str, str]]:
    """Retorna (nomes de atributo presentes, {nome_atributo: primeiro argumento
    posicional em string}) -- ex.: `[ForeignKey("Cliente")]` -> args={"ForeignKey": "Cliente"}."""
    names: set[str] = set()
    args: dict[str, str] = {}
    for attr in attr_list.children:
        if attr.type != "attribute":
            continue
        name_node = next((c for c in attr.children if c.type == "identifier"), None)
        if name_node is None:
            continue
        attr_name = _node_text(name_node)
        names.add(attr_name)
        arg_list = next((c for c in attr.children if c.type == "attribute_argument_list"), None)
        if arg_list is None:
            continue
        first_string = next((c for c in _find_all(arg_list, "string_literal")), None)
        if first_string is not None:
            args[attr_name] = _node_text(first_string).strip('"')
    return names, args
