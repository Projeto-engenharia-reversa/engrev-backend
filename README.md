# engrev-backend

Recupera o modelo de dados relacional de um sistema a partir do código-fonte.

Recebe um `.zip` com o repositório e devolve três artefatos: o script SQL de
criação do banco, o diagrama entidade-relacionamento e um parecer que informa de
onde veio cada tabela e cada coluna.

A análise tem seis etapas. Nas três primeiras, interpretadores determinísticos
leem o que o código declara de forma explícita, percorrendo o código por árvore
sintática, os arquivos SQL e as migrações, e os formatos declarativos como Prisma
e Liquibase. Na quarta, um modelo de linguagem recebe essa evidência ordenada por
confiança e deduz o que não está declarado. As duas últimas validam a estrutura
gerada e produzem os artefatos. Por isso o parecer consegue dizer, para cada
elemento, se ele foi lido do código, com arquivo e linha, ou deduzido.

A interface web fica em outro repositório, `engrev-frontend`.

## Rodar com Docker

Requer o `engrev-frontend` clonado como pasta irmã.

```bash
git clone https://github.com/Projeto-engenharia-reversa/engrev-backend
git clone https://github.com/Projeto-engenharia-reversa/engrev-frontend
cd engrev-backend
cp .env.example .env     # preencha API_KEY se for usar o provedor real
docker compose up -d --build
```

| serviço | endereço |
|---|---|
| interface | http://localhost |
| API e documentação | http://localhost:8000/docs |
| banco | localhost:5432 |

Para subir só a API e o banco, sem a interface: `docker compose up -d db backend`.

O usuário inicial é criado por `python scripts/seed.py`, com as credenciais de
`SEED_ADMIN_EMAIL` e `SEED_ADMIN_PASSWORD`.

## Rodar local

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

Precisa de Python 3.13 e de um PostgreSQL acessível em `DATABASE_URL`.

## Configuração

Tudo em `.env`, a partir de `.env.example`. O que mais importa:

| variável | para quê |
|---|---|
| `LLM_PROVIDER` | `mock` roda sem rede e sem custo; `gemini` usa o provedor real |
| `API_KEY` | chave do provedor, necessária apenas com `gemini` |
| `DATABASE_URL` | conexão do PostgreSQL |
| `AMOSTRAS_MODELAGEM` | acima de 1, amostra a modelagem e consolida por maioria |

## Testes

`avaliacao/testes/` compara a extração determinística com os gabaritos e acusa
queda em relação ao resultado medido.

```bash
pytest
```

Os casos que dependem dos projetos de terceiros pulam quando o corpus não está
presente, então um clone limpo passa sem precisar de banco nem de chave.

## Avaliação

`avaliacao/gabaritos/` traz, para cada projeto avaliado, um JSON com as tabelas,
colunas, chaves estrangeiras e tipos que a ferramenta deveria encontrar, mais a
origem de onde o projeto foi obtido. Os quatro projetos autorais estão em
`avaliacao/projetos/`.

Os projetos de terceiros não são distribuídos aqui, cada um tem a sua licença.
Para reproduzir as medições que os envolvem, clone cada um em
`avaliacao/projetos-externos/` usando a URL do campo `origem` do seu gabarito.

```bash
python scripts/avaliar.py --projeto 02-loja-python     # um projeto
python scripts/avaliar.py --com-llm                    # inclui a dedução
python scripts/teto.py                                 # quanto havia para acertar
```

## Documentação

- [`docs/API.md`](docs/API.md) — endpoints
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — etapas da análise e modelo de dados
