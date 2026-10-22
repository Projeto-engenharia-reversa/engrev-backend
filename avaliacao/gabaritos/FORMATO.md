# Gabaritos

Cada `<projeto>.json` traz o modelo de dados esperado de um projeto, lido do
código-fonte dele.

## Campos

| campo | conteúdo |
|---|---|
| `projeto` | nome da pasta do projeto |
| `tabelas` | o modelo esperado, com colunas, chaves estrangeiras e tipos |
| `fonte_da_verdade` | de onde o modelo foi lido |
| `confianca` | `alta` ou `media` |
| `notas` | decisões de julgamento, como coluna removida por migração |
| `externo` | `true` nos 14 projetos de terceiros |
| `origem` | URL do repositório, nos externos |
| `commit` | revisão usada, quando registrada |
| `arquivos_de_schema` | caminhos que `--sem-schema` esconde do scan |
| `nota_sem_schema` | o que sobra no projeto com esses caminhos escondidos |
| `fks_avaliaveis` | `false` quando o projeto não declara chave estrangeira |
| `escopo` | `escala` exclui o projeto da média |

## Pareamento de entidades

O avaliador casa uma tabela do gabarito com uma da análise pelo nome exato. Sem
nome igual, casa pela maior sobreposição de colunas, com Jaccard de 0,5 ou mais.
Nesse caso conta acerto de extração e registra divergência de nome, que é uma
métrica separada.

## Projetos de terceiros

Os projetos com `externo: true` não são distribuídos aqui, cada um tem a sua
licença. Clone cada um em `avaliacao/projetos-externos/`, com o nome do campo
`projeto`, a partir da URL de `origem`.

## Como rodar

Ver a seção Avaliação do `README.md` na raiz.
