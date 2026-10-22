# Loja

Loja online interna. Flask + SQLAlchemy + PostgreSQL.

## Instalacao

```
python -m venv .venv
.venv/bin/activate
pip install -r requirements.txt
```

## Banco

Aplique as migracoes na ordem numerica:

```
psql $DATABASE_URL -f migrations/001_schema.sql
psql $DATABASE_URL -f migrations/002_add_desconto.sql
```

## Executando

```
export FLASK_APP=app:criar_app
flask run
```

A aplicacao sobe em http://localhost:5000.

## Convencoes

- Listagens em SQL direto (`app/db.py:executar`), escrita pelo ORM.
- Migracoes sao sempre aditivas em producao; `DROP COLUMN` so entra depois de
  duas semanas com a coluna sem uso.
- Nada de credencial em codigo: tudo por variavel de ambiente (`app/config.py`).
