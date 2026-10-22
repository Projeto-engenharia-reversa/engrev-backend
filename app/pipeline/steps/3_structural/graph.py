"""Grafo de código: resolve referências entre arquivos e monta o StructuralModel."""

from __future__ import annotations

from pathlib import Path

from app.helpers.naming import table_name_for, to_snake
from app.pipeline.types import (
    CodeLocation,
    ColumnDef,
    ModuleEdge,
    QueryDef,
    RelationshipDef,
    RemovedColumn,
    StructuralModel,
    TableDef,
    confidence_rank,
)

from .parsed_types import FileExtraction, ParsedAlter, ParsedTable

# Confiança de uma TableDef/RelationshipDef conforme a linguagem/formato de origem
# do FileExtraction que a gerou. "sql" = DDL real; "json" = heurística de forma de
# dados; formatos de schema estruturado (Camada 2) ficam em "schema-definition";
# qualquer outra linguagem (python/typescript/...) é extração via AST.
_TABLE_CONFIDENCE_BY_LANGUAGE = {
    "sql": "ddl",
    "json": "heuristic",
    "prisma": "schema-definition",
    "protobuf": "schema-definition",
    "graphql": "schema-definition",
    "openapi": "schema-definition",
    "liquibase-xml": "schema-definition",
    "java": "ast",
    "csharp": "ast",
    "html": "weak-fallback",
}

# Nomes que terminam em "_id" mas normalmente não são FK pra uma entidade do
# domínio (IDs de sistema externo, sessão, tracing) — reduz falso positivo da
# heurística de convenção de nome (1.3).
_FK_NAME_STOPWORDS = {"session", "external", "google", "stripe", "request", "trace", "correlation"}


_LINGUAGENS_DE_CLASSE = {"java", "csharp", "c_sharp"}


def _entidades_declaradas_fora(extractions: list[FileExtraction]) -> set[str]:
    """Classes que algum OUTRO arquivo declara serem entidades persistidas.

    O MyBatis é o caso: o mapeamento vive no `<resultMap type="...">` de um XML e
    a classe, num `.java` sem anotação nenhuma. Um projeto MyBatis inteiro pode
    não ter um único `@Entity`, e aí o parser de Java cai no modo permissivo e
    transforma **todo** POJO em tabela — no `macrozheng/mall` eram 212 entidades
    falsas contra 76 reais, 77 delas classes `*Example` que o MyBatis Generator
    cria só para montar consulta dinâmica.

    A declaração existe; ela só não cabia na fronteira do arquivo. Aqui é onde os
    arquivos se encontram.
    """
    declaradas: set[str] = set()
    for extraction in extractions:
        declaradas.update(extraction.entidades_declaradas)
    return declaradas


def build_structural(extractions: list[FileExtraction]) -> StructuralModel:
    tables: list[TableDef] = []
    relationships: list[RelationshipDef] = []
    queries: list[QueryDef] = []
    edges: list[ModuleEdge] = []
    modules: list[str] = []

    table_paths: dict[str, str] = {}
    symbol_tables: dict[str, str] = {}
    # Herança: nome de classe -> tabela, e tabela -> superclasses. Coletado aqui
    # porque a superclasse quase sempre mora noutro arquivo (`model/Person.java`
    # -> `owner/Owner.java`), então só dá para resolver depois de ver tudo.
    classe_para_tabela: dict[str, str] = {}
    bases_por_tabela: dict[str, list[str]] = {}
    colunas_de_base: dict[str, list[ColumnDef]] = {}

    # Só filtra se ALGUÉM declarou: num projeto sem MyBatis o conjunto é vazio e
    # nada muda. E só vale para linguagem que declara entidade por anotação — se
    # o projeto usa JPA e MyBatis juntos, a anotação continua mandando, porque o
    # parser de Java já resolveu isso antes de chegar aqui.
    declaradas_fora = _entidades_declaradas_fora(extractions)

    for extraction in extractions:
        modules.append(extraction.path)
        for table in extraction.tables:
            if (
                declaradas_fora
                and extraction.language in _LINGUAGENS_DE_CLASSE
                and table.classe
                and table.classe not in declaradas_fora
            ):
                continue
            table_def = _table_from_parsed(table, extraction)
            if table.classe:
                classe_para_tabela.setdefault(table.classe, table.name)
            if table.bases:
                bases_por_tabela.setdefault(table.name, []).extend(table.bases)
            if table.apenas_heranca:
                # Classe-base: entra só no acervo de herança, nunca na lista de
                # tabelas. Não virar tabela e emprestar colunas são coisas
                # separadas — tratá-las como uma só apagava as colunas junto.
                colunas_de_base[table.name] = table_def.columns
                continue
            tables.append(table_def)
            table_paths.setdefault(table.name, extraction.path)
        for symbol in extraction.symbols:
            table_name = symbol.table_name_override or table_name_for(symbol.name)
            symbol_tables[symbol.name] = table_name
            classe_para_tabela.setdefault(symbol.name, table_name)
            if symbol.bases:
                bases_por_tabela.setdefault(table_name, []).extend(symbol.bases)
            table_def = _table_from_symbol(symbol, extraction, table_name)
            if table_def is not None:
                tables.append(table_def)
                table_paths.setdefault(table_name, extraction.path)

    tables, table_sources = _merge_tables(tables)
    table_paths = {name: path for name, path in table_sources.items() if path}

    _herdar_colunas(tables, classe_para_tabela, bases_por_tabela, colunas_de_base)

    # 1.5: aplica ADD/DROP/RENAME COLUMN de migrations em cima do estado já
    # mesclado, na ordem em que os arquivos foram processados (ordem do scan,
    # alfabética — compatível com convenções comuns tipo V1__/V2__/AAAAMMDD_...,
    # mas não é garantia absoluta pra migrations nomeadas fora de padrão).
    tables_by_name = {t.name: t for t in tables}

    # Tabela criada e descartada dentro do MESMO arquivo nunca existiu como
    # entidade final — ver `_tabelas_efemeras`.
    for efemera in _tabelas_efemeras(extractions):
        tables_by_name.pop(efemera, None)
    tables = [t for t in tables if t.name in tables_by_name]

    alter_relationships, alter_edges, removed_columns = _apply_alters(tables_by_name, extractions)
    relationships.extend(alter_relationships)
    edges.extend(alter_edges)

    # 1.3: heurística de FK por convenção de nome (roda depois dos alters, pra
    # também cobrir colunas *_id adicionadas via ALTER TABLE).
    table_names = set(tables_by_name.keys())
    naming_relationships, naming_edges = _apply_naming_convention_fks(list(tables_by_name.values()), table_names)
    relationships.extend(naming_relationships)
    edges.extend(naming_edges)

    for extraction in extractions:
        for import_str in extraction.imports:
            resolved = _resolve_import(extraction.path, import_str)
            if resolved:
                edges.append(
                    ModuleEdge(kind="import", source=extraction.path, target=resolved, source_hint=extraction.path)
                )

    for extraction in extractions:
        for symbol in extraction.symbols:
            table_name = symbol_tables.get(symbol.name) or table_name_for(symbol.name)
            for field in symbol.fields:
                if field.fk_target is None:
                    continue
                target_table = _resolve_fk_target(field.fk_target, table_paths, symbol_tables)
                if not target_table:
                    continue
                relationships.append(
                    RelationshipDef(
                        name=f"{table_name}_{target_table}_{field.name}",
                        table_a=table_name,
                        table_b=target_table,
                        kind="one-to-many",
                        source_hint=extraction.path,
                        confidence="ast",
                        fk_column=field.name,
                        location=_symbol_location(symbol, extraction.path),
                    )
                )
                edges.append(
                    ModuleEdge(
                        kind="references",
                        source=extraction.path,
                        target=target_table,
                        source_hint=extraction.path,
                    )
                )

        table_confidence = _TABLE_CONFIDENCE_BY_LANGUAGE.get(extraction.language, "ast")
        for table in extraction.tables:
            for column in table.columns:
                if column.fk_table is None:
                    continue
                target = column.fk_table
                relationships.append(
                    RelationshipDef(
                        name=f"{table.name}_{target}_{column.name}",
                        table_a=table.name,
                        table_b=target,
                        kind="one-to-many",
                        source_hint=extraction.path,
                        confidence=table_confidence,
                        fk_column=column.name,
                        location=CodeLocation(
                            path=extraction.path,
                            line_start=column.line or table.line_start,
                            line_end=table.line_end,
                            symbol=table.name,
                        ),
                    )
                )
                edges.append(
                    ModuleEdge(kind="references", source=extraction.path, target=target, source_hint=extraction.path)
                )

    for extraction in extractions:
        for parsed in extraction.queries:
            tables_in = list(parsed.tables)
            query = QueryDef(
                name=f"{parsed.kind}_{parsed.line}",
                kind=parsed.kind,
                tables=tables_in,
                source_hint=extraction.path,
                location=CodeLocation(
                    path=extraction.path,
                    line_start=parsed.line,
                    line_end=parsed.line_end,
                    symbol=parsed.kind,
                ),
                evidence=_snippet(extraction.text, parsed.line, parsed.line_end),
            )
            queries.append(query)
            for table in tables_in:
                edges.append(ModuleEdge(kind="uses", source=extraction.path, target=table, source_hint=extraction.path))

    relationships = _dedup_relationships(relationships)
    return StructuralModel(
        tables=tables,
        relationships=relationships,
        queries=queries,
        modules=sorted(modules),
        edges=edges,
        removed_columns=removed_columns,
    )


def _table_from_parsed(table: ParsedTable, extraction: FileExtraction) -> TableDef:
    columns = [
        ColumnDef(
            name=column.name,
            data_type=column.data_type,
            nullable=column.nullable,
            primary_key=column.primary_key,
            unique=column.unique,
            fk_table=column.fk_table,
            fk_column=column.fk_column,
            line=column.line or None,
        )
        for column in table.columns
    ]
    return TableDef(
        name=table.name,
        columns=columns,
        source_hint=extraction.path,
        location=CodeLocation(path=extraction.path, line_start=table.line_start, line_end=table.line_end, symbol=table.name),
        evidence=_snippet(extraction.text, table.line_start, table.line_end),
        confidence=_TABLE_CONFIDENCE_BY_LANGUAGE.get(extraction.language, "ast"),
    )


def _table_from_symbol(symbol, extraction: FileExtraction, table_name: str) -> TableDef | None:
    fields = [f for f in symbol.fields if f.name not in ("id",)]
    columns = [ColumnDef(name="id", data_type="integer", nullable=False, primary_key=True)]
    for field in fields:
        columns.append(
            ColumnDef(
                name=field.name,
                data_type=field.data_type,
                nullable=field.nullable,
                primary_key=field.primary_key,
                unique=field.unique,
                fk_table=field.fk_target.split(".")[0] if field.fk_target else None,
                fk_column=field.fk_target.split(".", 1)[1] if field.fk_target and "." in field.fk_target else None,
                line=field.line,
            )
        )
    if not fields:
        return None
    return TableDef(
        name=table_name,
        columns=columns,
        source_hint=extraction.path,
        location=CodeLocation(
            path=extraction.path,
            line_start=symbol.line_start,
            line_end=symbol.line_end,
            symbol=symbol.name,
        ),
        evidence=_snippet(extraction.text, symbol.line_start, symbol.line_end),
        confidence="ast",
    )


def _herdar_colunas(
    tables: list[TableDef],
    classe_para_tabela: dict[str, str],
    bases_por_tabela: dict[str, list[str]],
    colunas_de_base: dict[str, list[ColumnDef]] | None = None,
) -> None:
    """Desce para a subclasse as colunas declaradas na classe-base.

    Sem isto, coluna de classe-base simplesmente sumia: as 3 que o django-realworld
    perdia (`password`, `last_login`, `is_superuser`) vêm de `AbstractBaseUser`, e
    o petclinic sem o `schema.sql` perderia `first_name`/`last_name` de `Person`.
    É um conceito só servindo Java, C#, Python e TypeScript — nenhum deles precisa
    de tratamento próprio.

    Só herda de base que virou tabela. Interface, mixin de framework e classe fora
    do projeto não estão em `classe_para_tabela` e são ignoradas — é o que faz a
    lista indistinta de `class X : Base, IFoo` do C# funcionar sem resolver tipos.

    Conflito de nome: **a subclasse vence**, porque redeclarar é decisão
    deliberada de quem escreveu o código.
    """
    # Tabela normal e classe-base marcada como `apenas_heranca` são fontes
    # igualmente válidas de coluna herdada — a diferença é só que a segunda não
    # aparece no resultado.
    acervo: dict[str, list[ColumnDef]] = {t.name: t.columns for t in tables}
    acervo.update(colunas_de_base or {})

    def colunas_herdadas(tabela: str, visitados: set[str]) -> list:
        # `visitados` corta ciclo de herança: código real tem coisa estranha, e
        # recursão infinita aqui derrubaria a análise inteira.
        if tabela in visitados:
            return []
        visitados.add(tabela)
        acumulado: list = []
        for base in bases_por_tabela.get(tabela, []):
            nome_base = classe_para_tabela.get(base)
            if nome_base is None or nome_base == tabela or nome_base not in acervo:
                continue
            acumulado.extend(colunas_herdadas(nome_base, visitados))
            acumulado.extend(acervo[nome_base])
        return acumulado

    for tabela in tables:
        herdadas = colunas_herdadas(tabela.name, set())
        if not herdadas:
            continue
        existentes = {c.name for c in tabela.columns}
        for coluna in herdadas:
            if coluna.name in existentes:
                continue
            existentes.add(coluna.name)
            tabela.columns.append(coluna.model_copy(deep=True))


def _merge_tables(tables: list[TableDef]) -> tuple[list[TableDef], dict[str, str]]:
    merged: dict[str, TableDef] = {}
    for table in tables:
        existing = merged.get(table.name)
        if existing is None:
            merged[table.name] = table
            continue
        seen = {c.name for c in existing.columns}
        for column in table.columns:
            if column.name in seen:
                _merge_column(existing, column, table.confidence)
            else:
                existing.columns.append(column)
                seen.add(column.name)
        if existing.location is None and table.location is not None:
            existing.location = table.location
        if existing.evidence is None and table.evidence is not None:
            existing.evidence = table.evidence
        if confidence_rank(table.confidence) < confidence_rank(existing.confidence):
            existing.confidence = table.confidence
    sources: dict[str, str] = {}
    for table in merged.values():
        if table.location is not None:
            sources[table.name] = table.location.path
    return list(merged.values()), sources


# Fontes que declaram o tipo da coluna explicitamente. Nas demais, "string" é o
# default de "não sei" (campo de classe JS sem anotação, `<input>` sem `type`) —
# não uma afirmação de que a coluna é textual.
_FONTES_COM_TIPO_DECLARADO = {"ddl", "schema-definition"}


def _melhor_tipo(atual: str, conf_atual: str, novo: str, conf_novo: str) -> str:
    """Escolhe entre dois tipos para a mesma coluna vista em fontes diferentes.

    Antes o tipo era simplesmente o da primeira fonte processada — ou seja, a
    ordem alfabética do scan decidia. O efeito era jogar fora informação que o
    pipeline já tinha extraído certo: `html_forms` lê `type="number"` como
    decimal e `type="date"` como date, e isso se perdia porque a versão da mesma
    entidade lida do JS (sem tipo, tudo "string") vinha antes.

    A regra: "string" vindo de fonte que não declara tipo é ausência de
    informação e perde para qualquer tipo concreto. "string" vindo de DDL ou de
    schema declarado é uma declaração e se mantém — senão um `<input
    type="number">` num formulário de CPF transformaria um VARCHAR em NUMERIC.
    """
    if atual == novo:
        return atual
    atual_e_palpite = atual == "string" and conf_atual not in _FONTES_COM_TIPO_DECLARADO
    novo_e_palpite = novo == "string" and conf_novo not in _FONTES_COM_TIPO_DECLARADO
    if atual_e_palpite and not novo_e_palpite:
        return novo
    if novo_e_palpite and not atual_e_palpite:
        return atual
    # Dois tipos concretos em desacordo: decide a confiança da fonte; empate
    # mantém o que já estava, pra saída não depender da ordem do scan.
    return novo if confidence_rank(conf_novo) < confidence_rank(conf_atual) else atual


def _merge_column(existing: TableDef, column: ColumnDef, conf_novo: str) -> None:
    target = next((c for c in existing.columns if c.name == column.name), None)
    if target is None:
        return
    target.data_type = _melhor_tipo(target.data_type, existing.confidence, column.data_type, conf_novo)
    if column.primary_key:
        target.primary_key = True
    if not column.nullable:
        target.nullable = False
    if column.unique:
        target.unique = True
    if column.fk_table:
        target.fk_table = column.fk_table
        target.fk_column = column.fk_column


def _tabelas_efemeras(extractions: list[FileExtraction]) -> set[str]:
    """Tabelas que o DDL cria e descarta dentro do mesmo arquivo.

    O SQLite não suporta alterar coluna, então a receita canônica é criar uma
    tabela nova, copiar os dados, dropar a antiga e renomear:

        CREATE TABLE devices_new (...);
        INSERT INTO devices_new SELECT ... FROM devices;
        DROP TABLE devices;
        ALTER TABLE devices_new RENAME TO devices;

    Sem isto, `devices_new` sobrevive no modelo final como uma entidade a mais —
    foram 4 tabelas falsas de 32 no vaultwarden, que usa a receita várias vezes.
    Não é heurística: **o DDL diz literalmente que a tabela deixou de existir**, e
    a aplicação de ALTER era incompleta, cobrindo só o nível de coluna.

    **O escopo é o arquivo**, e isso importa: migrations costumam vir em pares
    `up.sql`/`down.sql`, e o `down.sql` dropa tudo que o `up.sql` criou — aplicar
    aqueles DROPs globalmente apagaria o schema inteiro. Restringir ao arquivo
    cobre a receita do SQLite, que é sempre local.

    **E a ORDEM importa tanto quanto o escopo.** A primeira versão desta regra
    ignorava a linha e apagou quatro tabelas legítimas do vaultwarden, porque o
    projeto abre várias migrations com um DROP defensivo:

        DROP TABLE IF EXISTS archives;   -- antes
        CREATE TABLE archives (...);

    Drop *antes* do create é proteção contra reexecução; drop *depois* é descarte.
    Só o segundo torna a tabela efêmera.
    """
    efemeras: set[str] = set()
    for extraction in extractions:
        criacao = {t.name: t.line_start for t in extraction.tables}
        if not criacao:
            continue
        for alter in extraction.alters:
            if alter.action not in ("drop_table", "rename_table"):
                continue
            linha_da_criacao = criacao.get(alter.table)
            if linha_da_criacao is not None and alter.line > linha_da_criacao:
                efemeras.add(alter.table)
    return efemeras


def _apply_alters(
    tables_by_name: dict[str, TableDef], extractions: list[FileExtraction]
) -> tuple[list[RelationshipDef], list[ModuleEdge], list[RemovedColumn]]:
    """Aplica ADD/DROP/RENAME COLUMN e FK-em-coluna-existente (`add_fk`, usado pelo
    `addForeignKeyConstraint` do Liquibase) de migrations em cima das tabelas já
    mescladas. Ignora ALTER de tabela que nunca foi vista via CREATE TABLE/schema
    (não inventa tabela nova a partir de um ALTER isolado).

    Devolve também as colunas que saíram: aplicar o alter destrói a evidência de
    que a coluna existiu e foi retirada, e a Fase 4.5 precisa dela — o LLM recebe
    o CREATE original e o DROP na mesma evidência e tende a manter a coluna."""
    relationships: list[RelationshipDef] = []
    edges: list[ModuleEdge] = []
    removed: list[RemovedColumn] = []
    for extraction in extractions:
        if not extraction.alters:
            continue
        confidence = _TABLE_CONFIDENCE_BY_LANGUAGE.get(extraction.language, "ddl")
        for alter in extraction.alters:
            table = tables_by_name.get(alter.table)
            if table is None:
                continue
            if alter.action == "add_column" and alter.column is not None:
                _apply_add_column(table, alter, extraction.path, confidence, relationships, edges)
            elif alter.action == "drop_column" and alter.column_name:
                table.columns = [c for c in table.columns if c.name != alter.column_name]
                removed.append(
                    RemovedColumn(
                        table=table.name,
                        column=alter.column_name,
                        path=extraction.path,
                        line=alter.line,
                    )
                )
            elif alter.action == "rename_column" and alter.old_name and alter.new_name:
                for column in table.columns:
                    if column.name == alter.old_name:
                        column.name = alter.new_name
                # O nome antigo também deixou de existir: sem isto o LLM devolve as
                # duas versões da coluna, a renomeada e a original.
                removed.append(
                    RemovedColumn(
                        table=table.name,
                        column=alter.old_name,
                        path=extraction.path,
                        line=alter.line,
                        motivo="rename",
                        renomeada_para=alter.new_name,
                    )
                )
            elif alter.action == "add_fk" and alter.column_name and alter.fk_table:
                _apply_add_fk(table, alter, extraction.path, confidence, relationships, edges)

    # Uma migration posterior pode ter trazido a coluna de volta (DROP e depois ADD,
    # ou um RENAME que desfaz outro). Só conta como removida a que não está no
    # estado final da tabela — senão a Fase 4.5 apagaria uma coluna que existe.
    removed = [
        r
        for r in removed
        if not any(c.name == r.column for c in tables_by_name[r.table].columns)
    ]
    return relationships, edges, removed


def _apply_add_column(
    table: TableDef,
    alter: ParsedAlter,
    path: str,
    confidence: str,
    relationships: list[RelationshipDef],
    edges: list[ModuleEdge],
) -> None:
    parsed = alter.column
    if parsed is None:
        return
    new_column = ColumnDef(
        name=parsed.name,
        data_type=parsed.data_type,
        nullable=parsed.nullable,
        primary_key=parsed.primary_key,
        unique=parsed.unique,
        fk_table=parsed.fk_table,
        fk_column=parsed.fk_column,
        line=parsed.line or None,
    )
    existing = next((c for c in table.columns if c.name == new_column.name), None)
    if existing is not None:
        table.columns.remove(existing)
    table.columns.append(new_column)
    if new_column.fk_table:
        relationships.append(
            RelationshipDef(
                name=f"{table.name}_{new_column.fk_table}_{new_column.name}",
                table_a=table.name,
                table_b=new_column.fk_table,
                kind="one-to-many",
                source_hint=path,
                confidence=confidence,
                fk_column=new_column.name,
                location=CodeLocation(path=path, line_start=alter.line, line_end=alter.line, symbol=table.name),
            )
        )
        edges.append(ModuleEdge(kind="references", source=path, target=new_column.fk_table, source_hint=path))


def _apply_add_fk(
    table: TableDef,
    alter: ParsedAlter,
    path: str,
    confidence: str,
    relationships: list[RelationshipDef],
    edges: list[ModuleEdge],
) -> None:
    """`add_fk`: liga FK a uma coluna que já existe (ex.: `addForeignKeyConstraint`
    do Liquibase, que referencia uma coluna definida num changeset anterior)."""
    column = next((c for c in table.columns if c.name == alter.column_name), None)
    if column is None or not alter.fk_table:
        return
    column.fk_table = alter.fk_table
    column.fk_column = alter.fk_column
    relationships.append(
        RelationshipDef(
            name=f"{table.name}_{alter.fk_table}_{column.name}",
            table_a=table.name,
            table_b=alter.fk_table,
            kind="one-to-many",
            source_hint=path,
            confidence=confidence,
            fk_column=column.name,
            location=CodeLocation(path=path, line_start=alter.line, line_end=alter.line, symbol=table.name),
        )
    )
    edges.append(ModuleEdge(kind="references", source=path, target=alter.fk_table, source_hint=path))


def _tabela_candidata(base: str, table_names: set[str]) -> str | None:
    """Tabela alvo de uma coluna `<base>_id`, ou None se não houver certeza.

    `to_plural` é anglófono, então `autor` vira `autors` e a tabela real
    (`autores`, declarada por `@Table`) não é encontrada. Quando o plural inglês
    falha, procura-se uma tabela que comece por `base` — mas só se houver
    **exatamente uma**: com `conta_id` e as tabelas `contas` e `contatos` a
    escolha seria arbitrária, e ligar errado é pior que não ligar.
    """
    candidate = table_name_for(base)
    if candidate in table_names:
        return candidate
    if base in table_names:
        return base
    por_prefixo = [nome for nome in table_names if nome.startswith(base)]
    if len(por_prefixo) == 1:
        return por_prefixo[0]

    # Nome composto qualificado: `genero_pai_id` aponta para `generos`, e
    # `usuario_aprovador_id` para `usuarios` — o primeiro token é o substantivo,
    # o resto é papel. Sem isto a auto-referência de `generos` ficava sem FK.
    # Só a primeira posição, e só se ela sozinha resolver sem ambiguidade.
    cabeca = base.split("_", 1)[0]
    if cabeca and cabeca != base:
        candidato_cabeca = table_name_for(cabeca)
        if candidato_cabeca in table_names:
            return candidato_cabeca
        if cabeca in table_names:
            return cabeca
    return None


def _apply_naming_convention_fks(
    tables: list[TableDef], table_names: set[str]
) -> tuple[list[RelationshipDef], list[ModuleEdge]]:
    """Heurística de FK por convenção de nome (`xxx_id` -> tabela `xxx`), sem
    regex: só `to_snake()` (já existente) + slicing de string. Só liga se a
    tabela candidata já existir no modelo (não inventa tabela a partir da
    heurística) e o nome não estiver na lista de stopwords."""
    relationships: list[RelationshipDef] = []
    edges: list[ModuleEdge] = []
    for table in tables:
        for column in table.columns:
            if column.fk_table:
                continue
            normalized = to_snake(column.name)
            if normalized == "id" or not normalized.endswith("_id"):
                continue
            base = normalized[: -len("_id")]
            if not base or base in _FK_NAME_STOPWORDS:
                continue
            candidate = _tabela_candidata(base, table_names)
            if candidate is None:
                continue
            column.fk_table = candidate
            column.fk_column = "id"
            relationships.append(
                RelationshipDef(
                    name=f"{table.name}_{candidate}_{column.name}",
                    table_a=table.name,
                    table_b=candidate,
                    kind="one-to-many",
                    source_hint=table.source_hint,
                    confidence="heuristic",
                    fk_column=column.name,
                )
            )
            edges.append(
                ModuleEdge(
                    kind="references",
                    source=table.source_hint or "",
                    target=candidate,
                    source_hint="heuristic:naming_convention",
                )
            )
    return relationships, edges


def _dedup_relationships(relationships: list[RelationshipDef]) -> list[RelationshipDef]:
    """Chave inclui `fk_column` (5.3) -- antes só `(table_a, table_b)` colapsava
    múltiplas FKs distintas entre o mesmo par de tabelas (ex.: `orders.customer_id`
    e `orders.approved_by` -> `customers`) numa relação só."""
    seen: set[tuple[str, str, str | None]] = set()
    unique: list[RelationshipDef] = []
    for relationship in relationships:
        key = (relationship.table_a, relationship.table_b, relationship.fk_column)
        if key in seen:
            continue
        seen.add(key)
        unique.append(relationship)
    return unique


def _resolve_fk_target(target: str, table_paths: dict[str, str], symbol_tables: dict[str, str]) -> str | None:
    parts = [p for p in target.split(".") if p]
    if not parts:
        return None
    first = parts[0]
    if first in table_paths:
        return first
    if first in symbol_tables:
        return symbol_tables[first]
    resolved = table_name_for(first)
    if resolved in table_paths:
        return resolved
    return None


def _resolve_import(source_path: str, import_str: str) -> str:
    if not import_str:
        return ""
    if import_str.startswith("."):
        base = Path(source_path).parent
        relative = import_str
        level = 0
        while relative.startswith("."):
            level += 1
            relative = relative[1:]
        relative = relative.lstrip("/")
        parts = list(base.parts)
        for _ in range(level - 1):
            if parts:
                parts.pop()
        module = ".".join(p for p in [*parts, *relative.split(".")] if p)
        return module or import_str
    return import_str


def _symbol_location(symbol, path: str) -> CodeLocation:
    return CodeLocation(path=path, line_start=symbol.line_start, line_end=symbol.line_end, symbol=symbol.name)


def _snippet(text: str, line_start: int, line_end: int, max_lines: int = 500) -> str:
    lines = text.splitlines()
    start = max(0, line_start - 1)
    end = min(len(lines), line_end)
    if end - start > max_lines:
        end = start + max_lines
    return "\n".join(lines[start:end])
