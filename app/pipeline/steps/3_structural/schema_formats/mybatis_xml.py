"""Mapper do MyBatis: declara quais classes Java são entidades persistidas.

O MyBatis não anota a classe. Um projeto inteiro pode não ter um único `@Entity`
— e aí o parser de Java cai no modo permissivo e transforma **todo** POJO em
tabela. No `macrozheng/mall` isso produzia 212 entidades falsas contra 76 reais,
sendo 77 delas classes `*Example`, que o MyBatis Generator cria só para montar
consulta dinâmica.

Mas a declaração existe: ela está no `<resultMap type="com.x.Model">` do XML. É o
mesmo `@Entity`, escrito noutro arquivo. Este parser só extrai esses nomes; quem
os aplica é o grafo, que é onde os arquivos se encontram.

Não produz tabela: um `resultMap` diz *que* a classe é entidade, não quais são as
colunas dela com tipo — isso continua vindo do DDL ou da própria classe.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from ..parsed_types import FileExtraction


def _e_projecao_de_join(result_map) -> bool:
    """Distingue o resultMap que mapeia UMA tabela do que monta uma projeção.

    Nem todo `resultMap` corresponde a uma tabela. Os gerados pelo MyBatis
    Generator sim — só têm `<id>` e `<result>`, um por coluna. Os escritos à mão
    para consulta com JOIN montam um tipo composto, e se declaram assim:

        <resultMap type="...PmsProductResult" extends="...ResultMapWithBLOBs">
            <collection property="productLadderList" resultMap="..." />

    `extends` diz que ele acrescenta a outro; `<collection>` e `<association>`
    dizem que ele embute uma lista ou um objeto. Nos dois casos o tipo é uma
    projeção de consulta, não uma entidade persistida.

    O sinal é a forma do XML, não o nome do arquivo. `PmsProductDao.xml` contra
    `PmsProductMapper.xml` também separaria estes casos no `macrozheng/mall`, mas
    seria convenção daquele projeto; `extends` e `<collection>` são do MyBatis.
    """
    if result_map.get("extends"):
        return True
    return any(filho.tag in ("collection", "association") for filho in result_map)


def parse_mybatis(path: str, text: str) -> FileExtraction | None:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    if root.tag != "mapper":
        return None
    declaradas: list[str] = []
    for elemento in root.iter():
        if elemento.tag != "resultMap":
            continue
        if _e_projecao_de_join(elemento):
            continue
        tipo = elemento.get("type") or elemento.get("ofType")
        if tipo:
            # `com.macro.mall.model.CmsHelpCategory` -> `CmsHelpCategory`
            declaradas.append(tipo.rsplit(".", 1)[-1])
    if not declaradas:
        return None
    return FileExtraction(
        path=path, language="mybatis", text=text,
        entidades_declaradas=sorted(set(declaradas)),
    )
