"""Consenso entre amostras da modelagem (auto-consistência).

Medido no corpus, o mesmo projeto com a mesma entrada dá resultados diferentes
entre execuções: o laravel varia de 78,7% a 100% em colunas, o aspnetcore de
87,5% a 100% em tabelas. **Essa faixa é maior que qualquer ganho de acurácia
perseguível** — enquanto ela existir, melhoria pequena não é detectável e o
número reportado depende de sorte.

A ideia é a de sempre em auto-consistência: amostrar N vezes e ficar com o que a
maioria disse. Isso não sobe o teto (o melhor caso continua o mesmo); sobe o
**piso**, que é o que importa para confiabilidade — e é o piso que aparece numa
demonstração ao vivo.

O voto é por elemento, não por resposta inteira: uma amostra pode acertar as
tabelas e errar uma FK, e descartá-la por inteiro jogaria fora o que ela tem de
bom. Tabela, coluna e relação são votadas separadamente.
"""

from __future__ import annotations

from collections import Counter

from app.pipeline.types import ColumnDef, ConceptualModel, RelationshipDef, TableDef


def _maioria(total: int) -> int:
    """Quantos votos bastam. Com 3 amostras, 2; com 2, 2 (não 1)."""
    return total // 2 + 1


def _voto_de_atributo(valores: list, padrao):
    """Valor mais votado; empate fica com o primeiro que apareceu."""
    if not valores:
        return padrao
    return Counter(valores).most_common(1)[0][0]


def _consolidar_colunas(
    versoes: list[TableDef], quorum: int, uniao: bool = False
) -> list[ColumnDef]:
    """Quais colunas entram, e por qual política.

    **A política de voto tem que seguir o perfil de erro do elemento votado**, e
    para coluna ele é o oposto do de tabela.

    Medido no corpus: a precisão de colunas é 100% nas células inspecionadas — o
    modelo não inventa coluna, ele **omite**. O que varia entre amostras é o
    recall (59% a 66,7% no rails sem schema). Logo, uma coluna vista por 1 de 3
    amostras é quase certamente correta, e exigir maioria a apagaria: a
    auto-consistência consertaria a cauda de tabelas e derrubaria o recall de
    colunas ao mesmo tempo.

    A hipótese acima levou a implementar a **união** das amostras, que funcionaria
    como um passe de completude sem nenhuma chamada além das já pagas. Ela foi
    **medida contra a maioria nas 12 configurações, com as mesmas amostras**, e o
    resultado rejeitou a hipótese:

    | | união | maioria |
    |---|---|---|
    | colunas F1 (média das 12) | 87,4% | 86,4% |
    | precisão (média) | 96,2% | **97,2%** |
    | células com precisão 100% | 4 | **8** |

    A união ganha 0,9 ponto de F1 — dentro da variância do próprio corpus — e perde
    1,0 de precisão. Pior: derruba de 8 para 4 o número de células onde vale
    "a ferramenta não inventa coluna nenhuma", que é uma afirmação mais forte que o
    F1 mede mal. **Por isso o padrão é maioria.**

    O ganho previsto existiu onde a hipótese dizia: no rails sem schema, a união
    levou as colunas de 69,0% para 75,0%. Só não se sustentou no agregado.

    `uniao=True` fica disponível para a ablação — comparar as duas políticas não
    pode exigir editar código.

    Os ATRIBUTOS da coluna (tipo, FK, PK) continuam por maioria nas duas
    políticas: ali a pergunta é "qual valor", não "existe ou não".
    """
    contagem: Counter[str] = Counter()
    ordem: list[str] = []
    por_nome: dict[str, list[ColumnDef]] = {}
    for tabela in versoes:
        vistas = set()
        for coluna in tabela.columns:
            if coluna.name in vistas:
                continue
            vistas.add(coluna.name)
            contagem[coluna.name] += 1
            if coluna.name not in por_nome:
                por_nome[coluna.name] = []
                ordem.append(coluna.name)
            por_nome[coluna.name].append(coluna)

    saida: list[ColumnDef] = []
    for nome in ordem:
        if not uniao and contagem[nome] < quorum:
            continue
        candidatas = por_nome[nome]
        saida.append(
            ColumnDef(
                name=nome,
                data_type=_voto_de_atributo([c.data_type for c in candidatas], "string"),
                nullable=_voto_de_atributo([c.nullable for c in candidatas], True),
                primary_key=_voto_de_atributo([c.primary_key for c in candidatas], False),
                unique=_voto_de_atributo([c.unique for c in candidatas], False),
                fk_table=_voto_de_atributo([c.fk_table for c in candidatas], None),
                fk_column=_voto_de_atributo([c.fk_column for c in candidatas], None),
                line=next((c.line for c in candidatas if c.line), None),
            )
        )
    return saida


def _chave_de_relacao(rel: RelationshipDef) -> tuple[frozenset[str], str | None]:
    """Mesma chave usada na reconciliação: par não-ordenado mais o `through`.

    O nome da relação é inventado a cada amostra e a ordem table_a/table_b varia,
    então votar por nome faria toda relação ficar abaixo do quorum.
    """
    return frozenset({rel.table_a, rel.table_b}), rel.through


def consolidar(amostras: list[ConceptualModel], uniao_de_colunas: bool = False) -> ConceptualModel:
    """Consolida N modelos conceituais, com política por tipo de elemento.

    | elemento | política | por quê |
    |---|---|---|
    | tabela | maioria | uma amostra degenerada perde o voto |
    | coluna | maioria | **medido**: a união não compensou — ver `_consolidar_colunas` |
    | atributo (tipo, FK, PK) | maioria | a pergunta é "qual valor", não "existe" |

    A maioria em tabela é o que conserta a cauda de confiabilidade: cerca de 5% das
    execuções devolvem um modelo degenerado (medido em 19 execuções), e uma amostra
    assim perde o voto.
    """
    if len(amostras) == 1:
        return amostras[0]

    quorum = _maioria(len(amostras))

    tabelas_por_nome: dict[str, list[TableDef]] = {}
    ordem_tabelas: list[str] = []
    for amostra in amostras:
        for tabela in amostra.tables:
            if tabela.name not in tabelas_por_nome:
                tabelas_por_nome[tabela.name] = []
                ordem_tabelas.append(tabela.name)
            tabelas_por_nome[tabela.name].append(tabela)

    tabelas: list[TableDef] = []
    for nome in ordem_tabelas:
        versoes = tabelas_por_nome[nome]
        if len(versoes) < quorum:
            continue
        modelo = versoes[0]
        tabelas.append(
            TableDef(
                name=nome,
                columns=_consolidar_colunas(versoes, _maioria(len(versoes)), uniao_de_colunas),
                source_hint=modelo.source_hint,
                location=modelo.location,
                confidence=modelo.confidence,
            )
        )

    nomes_finais = {t.name for t in tabelas}
    relacoes_por_chave: dict[tuple, list[RelationshipDef]] = {}
    ordem_relacoes: list[tuple] = []
    for amostra in amostras:
        vistas = set()
        for rel in amostra.relationships:
            chave = _chave_de_relacao(rel)
            if chave in vistas:
                continue
            vistas.add(chave)
            if chave not in relacoes_por_chave:
                relacoes_por_chave[chave] = []
                ordem_relacoes.append(chave)
            relacoes_por_chave[chave].append(rel)

    relacoes: list[RelationshipDef] = []
    for chave in ordem_relacoes:
        versoes = relacoes_por_chave[chave]
        if len(versoes) < quorum:
            continue
        # Relação cujas pontas não sobreviveram ao voto não pode entrar: seria
        # apontar para tabela que não existe, e a Fase 5 acusaria como erro.
        modelo = versoes[0]
        if modelo.table_a not in nomes_finais or modelo.table_b not in nomes_finais:
            continue
        relacoes.append(
            RelationshipDef(
                name=modelo.name,
                table_a=modelo.table_a,
                table_b=modelo.table_b,
                kind=_voto_de_atributo([r.kind for r in versoes], "one-to-many"),
                through=modelo.through,
                source_hint=modelo.source_hint,
                location=modelo.location,
                confidence=modelo.confidence,
                fk_column=_voto_de_atributo([r.fk_column for r in versoes], None),
            )
        )

    # `notes` e `queries` ficam da primeira amostra: são texto livre e lista de
    # consultas, onde votar não faz sentido — o racional de uma amostra é coerente
    # consigo mesmo, e costurar pedaços de várias produziria explicação picotada.
    return ConceptualModel(
        tables=tabelas,
        relationships=relacoes,
        queries=amostras[0].queries,
        notes=amostras[0].notes,
    )
