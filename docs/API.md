# EngRev API

Base URL: `/api` (produção servida pelo nginx; desenvolvimento `http://localhost:8000/api`).

## Autenticação

- Registro e login retornam `{ "access_token", "token_type", "user" }`.
- Envie o token em toda chamada protegida: `Authorization: Bearer <token>`.
- Tokens JWT expiram conforme `JWT_EXPIRE_MINUTES` (padrão 1440 min).
- Sem token válido, os endpoints retornam `401` com `{ "code": "unauthorized", "message": "Não autorizado" }`.

## Erros

Toda exceção controlada retorna `{ "code": string, "message": string }`.

| HTTP | code            | Descrição                     |
|------|-----------------|-------------------------------|
| 400  | `app_error`, `upload_error`, `llm_invalid_response` | Requisição ou upload inválido |
| 401  | `unauthorized`  | Credenciais inválidas / token ausente |
| 404  | `not_found`     | Recurso inexistente           |
| 409  | `conflict`      | Conflito (ex.: e-mail duplicado) |

## Endpoints

### Autenticação (`/api/auth`)

#### POST `/api/auth/register` — 201

```json
{ "email": "user@example.com", "password": "senha123", "name": "João" }
```

- `password`: mínimo 8 caracteres.
- Resposta: `TokenResponse` (veja acima).

#### POST `/api/auth/login`

```json
{ "email": "user@example.com", "password": "senha123" }
```

Resposta: `TokenResponse`. Erro: `401 unauthorized`.

#### GET `/api/auth/me`

Retorna `UserPublic`:

```json
{ "id": 1, "email": "user@example.com", "name": "João", "role": "user", "created_at": "..." }
```

#### PATCH `/api/auth/me`

Corpo opcional: `{ "name"?: string, "password"?: string }`. Retorna `UserPublic` atualizado.

### Projetos (`/api/projects`)

#### POST `/api/projects` — 201

```json
{ "name": "Sistema de Pedidos", "language_hint": "Python" }
```

Resposta: `ProjectPublic` (`id`, `name`, `language_hint`, `status`, `created_at`).

#### GET `/api/projects`

Lista projetos do usuário logado, mais recentes primeiro.

#### GET `/api/projects/{project_id}`

Resposta: `ProjectPublic` + campo `runs` (resumo de runs do projeto).

#### PATCH `/api/projects/{project_id}`

Renomeia o projeto:

```json
{ "name": "Sistema de Pedidos v2" }
```

Resposta: `ProjectPublic` atualizado.

#### DELETE `/api/projects/{project_id}` — 204

Exclui o projeto (e seus runs, uploads e arquivos armazenados).

#### POST `/api/projects/{project_id}/upload`

Multipart: campo `file` (ZIP). Limites:

- ZIP ≤ `MAX_UPLOAD_SIZE_MB` (padrão 20 MB).
- Arquivo individual ≤ 5 MB.
- Aceita qualquer arquivo de texto legível, independente de extensão/linguagem; arquivos binários ou ilegíveis são `excluded` (não quebram o upload).

Resposta `UploadResult`:

```json
{
  "project_id": 1,
  "original_filename": "legado.zip",
  "total_files": 120,
  "accepted_files": 115,
  "items": [ { "path": "src/main.py", "size_bytes": 2048, "status": "ok", "reason": null } ]
}
```

### Runs de análise (`/api/runs`)

#### POST `/api/runs/{project_id}/analyze` — 202

Dispara a análise em background (precisa de um upload prévio). Retorna `RunPublic`.
Acompanhe via `GET /status` ou `GET /stream`.

#### GET `/api/runs`

Lista runs do usuário logado.

#### GET `/api/runs/{run_id}`

`RunDetail`:

```json
{
  "id": 12, "project_id": 1, "status": "done", "stage": "done",
  "progress": 1.0, "error_message": null, "created_at": "...",
  "scanned_files": 115, "entities": 8, "relationships": 6,
  "artifacts": [ { "id": 3, "run_id": 12, "kind": "sql", "filename": "schema.sql", "size_bytes": 1024, "created_at": "..." } ]
}
```

#### GET `/api/runs/{run_id}/status`

`{ "id", "status", "stage", "progress", "error_message" }`.

#### GET `/api/runs/{run_id}/metrics`

`{ "total_tokens", "total_cost_usd", "steps": [{ "step", "model", "input_tokens", "output_tokens", "cost_usd" }] }`.

#### GET `/api/runs/{run_id}/stream` — SSE

Eventos `data: {...}\n\n`:

| type       | Campos                                   |
|------------|------------------------------------------|
| `snapshot` | estado atual (enviado imediatamente)      |
| `stage`    | `stage`, `progress`, `message`            |
| `finished` | progresso 1.0 (encerra o stream)          |
| `failed`   | `message` com o erro (encerra o stream)   |

Todos os eventos incluem `run_id`. Se nenhum evento chegar em 30s, o stream é fechado.

### Artefatos (`/api/artifacts`)

#### GET `/api/artifacts/{run_id}`

Lista artefatos do run (`.sql`, `.mmd`, `.json`, `.md`).

#### GET `/api/artifacts/{artifact_id}/download`

Baixa o conteúdo com `Content-Disposition: attachment`. Media type conforme o `kind`:

| kind | media type |
|------|------------|
| `sql` | `application/sql` |
| `mmd` | `text/plain` |
| `md`  | `text/markdown` |
| `json`| `application/json` |

### Health check

#### GET `/health`

Resposta: `{ "status": "ok" }` (sem autenticação).
