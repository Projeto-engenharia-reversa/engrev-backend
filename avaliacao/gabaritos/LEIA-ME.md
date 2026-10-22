# Gabaritos — corpus de avaliação

Cada `<projeto>.json` descreve o modelo de dados que **um analista competente
extrairia lendo o código-fonte**, não o que a pipeline produz hoje. Essa
distinção é o ponto: um gabarito derivado da saída da ferramenta não mede nada,
só congela os defeitos atuais como se fossem o esperado.

Por isso cada arquivo declara de onde a verdade veio (`fonte_da_verdade`) e o
quanto ela é discutível (`confianca`):

| Projeto | Fonte da verdade | Confiança |
|---|---|---|
| 01-helpdesk-frontend | classes em `js/models.js` | média — sem schema formal |
| 02-loja-python | DDL em `migrations/*.sql`, com os ALTER aplicados | alta |
| 03-biblioteca-java | anotações JPA (`@Table`, `@Column`, `@JoinColumn`) | alta |
| 04-catalogo-streaming | Prisma, GraphQL, Protobuf, OpenAPI, Liquibase, C# | alta, exceto nomes |

## O que é e o que não é erro da ferramenta

**Projeto 1** não tem schema declarado em lugar nenhum: o gabarito é a leitura
das cinco classes de `js/models.js`. Campos que só existem em formulário HTML
(`senha`, `lembrar_acesso` na tela de login) **não entram** — são controle de
interface, não atributo de domínio. É uma decisão de julgamento, e está anotada.

**Projeto 4** mistura seis formatos, e três entidades (`PerfilGosto`,
`Recomendacao`, `CampanhaEditorial`, em C#) não declaram nome de tabela. O nome
canônico aqui usa o plural português, que é o correto para um domínio escrito em
português — mas a ferramenta só chega nele com `NAMING_PLURAL=pt`. O avaliador
trata isso à parte: casa a entidade pelas colunas e reporta divergência de nome
como métrica separada, para o número de extração não ficar dominado por uma
questão de configuração.

## Como o avaliador casa as entidades

1. Nome exato.
2. Se não casar, maior sobreposição de colunas (Jaccard ≥ 0.5) — conta como
   acerto de extração e divergência de nome.

Uma entidade é identificada pelos atributos que carrega, não pelo rótulo. Separar
as duas coisas é o que permite ver se uma queda veio de extração pior ou só de
uma regra de pluralização.

## Como rodar

```
cd backend
PYTHONPATH=. .venv/Scripts/python scripts/avaliar.py            # Fases 1-3, sem LLM, sem cota
PYTHONPATH=. .venv/Scripts/python scripts/avaliar.py --projeto 03-biblioteca-java
```
