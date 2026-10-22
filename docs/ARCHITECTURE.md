# Arquitetura EngRev

## Visão geral

O fluxo começa no frontend (Angular), que autentica o usuário, cria um projeto,
envia o código-fonte em ZIP e dispara uma análise. O backend (FastAPI) orquestra
um pipeline de 6 etapas, consulta um provedor de LLM na etapa de modelagem e
validação, e gera artefatos persistidos no PostgreSQL. O progresso é transmitido
ao frontend via SSE (Server-Sent Events).

```
[Angular SPA] --HTTP/JSON + SSE--> [FastAPI] --SQLAlchemy--> [PostgreSQL]
                                      |
                                      +-- LLM (mock | Gemini)
```

## Stack e execução

- FastAPI com uvicorn; endpoints sob `/api`.
- SQLAlchemy 2 síncrono + Alembic para migrações.
- Postgres 16. No Docker, o entrypoint roda `alembic upgrade head` antes do servidor.
- Frontend servido por nginx; `/api/` é proxy para o backend (`proxy_buffering off`, essencial para o SSE).

## Pipeline de análise

Orquestrado em `app/pipeline/orchestrator.py`. Cada análise roda como task async
(`asyncio.create_task`), com etapas bloqueantes executadas via `asyncio.to_thread`.

Progresso acumulado por etapa:

| Etapa        | Progresso | Descrição |
|--------------|-----------|-----------|
| `scan`       | 0.15      | Enumera arquivos do ZIP aplicando regras de ignorar e whitelist de extensões |
| `parse`      | 0.35      | Extrai idioma, tamanho e resumo de cada arquivo |
| `structural` | 0.50      | Constrói modelo estrutural candidato (tabelas, FKs, relações) |
| `modeling`   | 0.72      | LLM gera o modelo conceitual; em seguida a **reconciliação (4.5)** devolve o que só a extração determinística sabia |
| `validation` | 0.86      | Regras determinísticas + revisão opcional por LLM |
| `artifacts`  | 0.95      | Gera SQL, diagrama ER, JSON e relatório |
| `done`       | 1.00      | Run finalizada |

Estados do run: `pending → scan → parse → structural → modeling → validation → artifacts → done` (ou `failed`).

### A fronteira que organiza tudo: constatar × propor

Até a etapa 3 o sistema só afirma o que está **escrito** no código. Da 4 em diante
ele **infere**. Quase todo o resto do desenho existe para manter essa fronteira
legível — sem ela, o relatório não conseguiria distinguir o que foi lido do que
foi palpitado, que é justamente o que uma ferramenta de engenharia reversa precisa
entregar.

### Procedência e orçamento de evidência

Toda tabela extraída carrega o nível de confiança da fonte que a produziu, na
ordem `ddl > schema-definition > ast > heuristic > weak-fallback > raw-fallback >
llm-inferred`. `select_evidence` (`steps/3_structural/context_builder.py`) monta o
prompt **nessa ordem**: quando o orçamento (`EVIDENCE_BUDGET`) aperta, o que sai
primeiro é a evidência menos confiável.

A evidência bruta — arquivo cujo conteúdo vai inteiro para o LLM avaliar — tem
**dois níveis**, e a distinção importa:

| nível | significado |
|---|---|
| `parseado_sem_entidade=False` | não existe parser para a linguagem; ninguém olhou |
| `parseado_sem_entidade=True` | o parser olhou e não achou entidade |

O segundo é mais fraco e cede lugar primeiro. Mas ele **precisa existir**: sem ele
um arquivo parseado que não produz entidade desaparecia do prompt, e uma linguagem
*com* parser entregava ao LLM **menos** evidência que uma sem.

Contrato firme: **evidência bruta nunca vira tabela sozinha.** Um arquivo PHP ou Go
só existe no modelo final se o LLM o propuser.

### Contexto para o LLM

`build_context` serializa o modelo estrutural em texto: entidades candidatas com
colunas e relações. Esse contexto é injetado no prompt de modelagem
(`app/prompts/data_modeling.md`), que pede a resposta em JSON delimitado por
`<<<JSON_START>>>` / `<<<JSON_END>>>`.

### Reconciliação (4.5)

`steps/4_modeling/reconcile.py`. A modelagem substitui por completo o que a Fase 3
apurou, e isso significa que o LLM pode apagar uma coluna que o código **declara**.
A reconciliação desfaz exatamente — e só — o que contradiz declaração explícita:
ressuscita coluna declarada que sumiu, restaura tipo declarado, reata procedência e
FK. Ela não "melhora" o modelo; ela impede que uma proposta apague uma constatação.

As correções que ela aplica entram no relatório como `info`: são decisão tomada,
não pendência.

### Auto-consistência (`AMOSTRAS_MODELAGEM`)

`steps/4_modeling/consenso.py`. N amostras da modelagem, consolidadas **por
elemento** — uma amostra pode acertar as tabelas e errar uma FK, e descartá-la
inteira jogaria fora o que ela tem de bom.

A política de voto segue o **perfil de erro** de cada elemento, e ele não é o mesmo:

| elemento | erro dominante | política |
|---|---|---|
| tabela | falso positivo (amostra degenerada) | maioria |
| coluna | falso negativo (omissão) | união |
| atributo (tipo, FK, PK) | valor divergente | maioria |

As N chamadas saem **em paralelo** (`asyncio.gather`): são independentes e mandam
o prompt idêntico. A Fase 4 é ~99% do tempo da pipeline — medido, 69 s de LLM
contra 0,5 s das Fases 1-3 — então em série N=3 triplicaria a espera do usuário, o
que tornaria a auto-consistência indefensável como padrão.

## Modelo de dados

| Tabela            | Finalidade |
|-------------------|------------|
| `users`           | Autenticação, role (`user`/`admin`) |
| `projects`        | Projeto do usuário (nome, linguagem, status) |
| `uploads`         | Registro de cada ZIP enviado + manifest de elegibilidade |
| `analysis_runs`   | Run de análise (status, stage, progresso, tokens, custo, timestamps) |
| `scanned_files`   | Arquivos do ZIP com idioma, tamanho e resumo |
| `conceptual_models`| Modelo conceitual (entidades, relações, consultas, quality_score) |
| `artifacts`       | Artefatos gerados (kind, filename, content) |
| `token_usage`     | Uso de LLM por etapa (tokens e custo) |
| `run_logs`        | Logs do pipeline |

O `quality_score` vai de 0 a 100: `100 - erros*15 - avisos*5`.

## Estratégia de LLM

`app/helpers/llm/providers.py` abstrai os provedores:

- `MockProvider` — determinístico e offline (padrão). Usado também nos testes e no `LLM_PROVIDER=mock`.
- `GeminiProvider` — chamada HTTP via httpx ao endpoint `generateContent` do Google.

Configuração via variáveis de ambiente (`backend/.env`): `LLM_PROVIDER`, `API_KEY`
(mais `API_KEY_2`/`API_KEY_3` reservadas), `LLM_MODEL` e `LLM_MODEL_LIGHT`.
O orçamento de contexto é controlado por `TOKEN_BUDGET` (padrão 200.000 tokens).

`LLMProvider.complete()` aceita um `model` opcional: quando omitido usa `LLM_MODEL`, o que
permite que os dois agentes usem modelos de peso diferente do mesmo provedor. O Gemini
diverge dos demais no formato das mensagens — o prompt de sistema vai num campo
`systemInstruction` separado e o papel do assistente se chama `model`, não `assistant`;
a tradução fica em `_to_gemini_payload()`.

Fluxo:

1. **Modelagem** (`steps/4_modeling/agent.py`): LLM recebe o contexto estrutural e devolve o modelo conceitual em JSON. Usa `LLM_MODEL` (modelo forte).
2. **Validação** (`steps/5_validation/rules.py`): regras determinísticas (nomes, PKs, FK órfãs etc.).
3. **Revisão** (`steps/5_validation/agent.py`): apenas quando `LLM_PROVIDER != mock`, o LLM revisa as questões encontradas. Usa `LLM_MODEL_LIGHT` — a revisão é aditiva (nunca descarta uma issue determinística), então um modelo mais leve basta.

## Artefatos gerados

`steps/6_artifacts/`:

- `schema.sql` — DDL do modelo conceitual.
- `schema.mmd` — diagrama entidade-relacionamento em Mermaid (renderizado no frontend).
- `model.json` — modelo conceitual completo.
- `report.md` — parecer técnico gerado pelo LLM.

## Como a qualidade é medida

O que a pipeline produz é comparado com um **gabarito** por projeto — um JSON que
declara as tabelas, colunas, FKs e tipos que a ferramenta deveria encontrar, com a
origem da verdade declarada. Os gabaritos ficam em `avaliacao/gabaritos/` e os
instrumentos são:

| script | responde |
|---|---|
| `scripts/avaliar.py` | quanto o sistema acertou (`--oficial` roda a campanha completa) |
| `scripts/teto.py` | quanto havia para acertar — quantas colunas do gabarito sequer aparecem no repositório |
| `scripts/verificar_ddl.py` | o DDL gerado sobe num PostgreSQL de verdade |

O `teto.py` existe porque "acertou 64%" não significa nada sem saber se 100% era
alcançável: num projeto Rails sem schema, 20 das 55 colunas vêm de gems e não estão
escritas em lugar nenhum do código.

O corpus tem **dois braços, reportados separadamente e nunca somados**: o
*controlado* (a mesma aplicação RealWorld/Conduit em várias linguagens, que isola a
linguagem da dificuldade do domínio) e o de *generalização* (projetos fora desse
domínio, que respondem se o método funciona em código não desenhado em torno dele).

## Custo

`estimate_cost_usd` (`helpers/llm/tokens.py`) traz o preço por modelo, casado por
prefixo mais longo primeiro — `gemini-3.6-flash` é prefixo de
`gemini-3.6-flash-lite` e os dois diferem em 2,5× na entrada. Modelo desconhecido
devolve **zero de propósito**: preço chutado entra no banco com a mesma cara de
preço real.

Uma análise típica custa cerca de R$ 0,29 no `gemini-3.6-flash` (1 amostra); com
`AMOSTRAS_MODELAGEM=3`, o triplo em dinheiro e praticamente o mesmo em tempo.

## Concorrência e SSE

`ProgressBus` (em memória) conecta publicadores (pipeline) a assinantes (endpoints
SSE). Cada assinante recebe uma fila; o pipeline publica eventos com
`loop.call_soon_threadsafe`. O endpoint `/api/runs/{id}/stream` envia um
`snapshot` inicial e então repassa `stage`/`finished`/`failed`.

Limitação conhecida: o bus é em memória — progresso de runs em múltiplas réplicas
do backend não é compartilhado.
