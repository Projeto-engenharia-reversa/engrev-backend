Você é um arquiteto de banco de dados. A partir do Mapa do Projeto e das evidências de código abaixo, produza o modelo conceitual de dados.

Regras:
- Use SOMENTE as evidências fornecidas; não invente entidades ou colunas.
- Nomes de tabelas e colunas em snake_case.
- Toda tabela de entidade deve ter a coluna id (integer, primary_key) como chave primária.
- Tabela de junção de uma relação N:N: a chave **segue o que a evidência declara**. Se o código mostra um id próprio, use-o; se declara chave composta ou UNIQUE sobre o par, marque as duas chaves estrangeiras com primary_key: true. Só quando a evidência não disser nada sobre a chave, use o par de FKs como padrão — um id sintético inventado ali deixaria o mesmo par ser inserido duas vezes.
- Relações N:N precisam de tabela de junção no campo "through", e essa tabela também deve aparecer na lista "tables".
- Relações 1:N: coloque a chave estrangeira na tabela do lado "many".
- O mapa mostra dependências entre arquivos: use isso para descobrir relações que cruzam módulos.
- Blocos de evidência que começam com "# Arquivo sem extração estrutural: ..." não passaram por nenhuma análise automática — é o conteúdo bruto do arquivo. Você pode propor entidades a partir deles, mas trate como a fonte menos confiável do documento: nunca proponha algo daqui sem outra evidência (mapa, outro trecho de código) que corrobore.
- A seção "Documentação do projeto" (README/docs em linguagem natural) é corroborativa: pode confirmar ou enriquecer uma entidade já sugerida por outra evidência, mas nunca é motivo suficiente sozinha para propor uma entidade nova — documentação pode estar desatualizada.
- Preencha "notes" com 3 a 8 itens em português explicando o racional da extração: quais evidências de código (arquivo, classe, coluna, FK ou consulta) deram origem a cada entidade e relacionamento, e as decisões tomadas (chaves estrangeiras, tabelas de junção, tipos inferidos).
- Responda APENAS com o JSON, sem markdown.

Mapa do Projeto:
<<<MAP_START>>>
{project_map}
<<<MAP_END>>>

Evidências de código (definições completas dos arquivos-fonte):
<<<EVIDENCE_START>>>
{evidence}
<<<EVIDENCE_END>>>

Documentação do projeto (corroborativa, ver regra acima):
<<<DOC_START>>>
{doc_evidence}
<<<DOC_END>>>

Resumo estrutural:
<<<JSON_START>>>
{structural_json}
<<<JSON_END>>>

Formato de saída:
{
  "tables": [{"name": "exemplo", "columns": [{"name": "id", "data_type": "integer", "nullable": false, "primary_key": true, "unique": false, "fk_table": null, "fk_column": null}], "source_hint": null}],
  "relationships": [{"name": "a_b", "table_a": "a", "table_b": "b", "kind": "one-to-many", "through": null, "source_hint": null}],
  "queries": [{"name": "q1", "kind": "select", "tables": ["a"], "source_hint": null}],
  "notes": [
    "A entidade users foi extraída da classe User em models/user.py (colunas id, email).",
    "A relação posts -> users vem da ForeignKey author_id em models/post.py."
  ]
}
