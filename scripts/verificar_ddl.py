"""Aplica o DDL gerado num PostgreSQL de verdade e falha se ele não subir.

Existe porque dois defeitos passaram por toda a suíte de testes e só apareceram
aqui: uma FK invertida (a tabela referenciada ainda não existia no momento do
`REFERENCES`) e um tipo incompatível entre as pontas de uma chave estrangeira.
Nenhum teste unitário pega isso — só o banco.

Usa o provedor `mock` de propósito: a pergunta é se o **gerador** produz SQL
válido, não se o LLM acerta o modelo. Mock é determinístico e não gasta cota.

    docker run -d --name engrev-ddl -e POSTGRES_PASSWORD=x -p 55432:5432 postgres:16-alpine
    PYTHONPATH=. python scripts/verificar_ddl.py
    docker rm -f engrev-ddl
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("LLM_PROVIDER", "mock")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from scripts.avaliar import GABARITOS, pasta_do_projeto  # noqa: E402

DSN_PADRAO = "postgresql://postgres:x@localhost:55432/postgres"


def ddl_do_projeto(pasta: Path) -> str:
    from app.pipeline.steps import build_structural, generate_artifacts, model as modelar, parse, scan
    from app.pipeline.types import AnalysisContext

    ctx = AnalysisContext(run_id=0, project_id=0, project_name=pasta.name, root_path=pasta)
    ctx.structural = build_structural(parse(scan(pasta), pasta), pasta)
    asyncio.run(modelar(ctx))
    ctx = generate_artifacts(ctx)
    return ctx.artifacts.get("schema.sql", "")


def main() -> int:
    import psycopg

    dsn = os.environ.get("DDL_DSN", DSN_PADRAO)
    falhas = 0
    projetos = []
    for arquivo in sorted(GABARITOS.glob("*.json")):
        gabarito = json.loads(arquivo.read_text(encoding="utf-8"))
        if gabarito.get("escopo") == "escala":
            continue
        pasta = pasta_do_projeto(gabarito)
        if pasta.exists():
            projetos.append((gabarito["projeto"], pasta))

    for nome, pasta in projetos:
        sql = ddl_do_projeto(pasta)
        if not sql.strip():
            print(f"  {nome:<40} sem DDL (0 tabelas no determinístico)")
            continue
        esquema = "s_" + nome.replace("-", "_").replace(".", "_")[:40]
        try:
            with psycopg.connect(dsn, autocommit=True) as con, con.cursor() as cur:
                cur.execute(f'DROP SCHEMA IF EXISTS "{esquema}" CASCADE')
                cur.execute(f'CREATE SCHEMA "{esquema}"')
                cur.execute(f'SET search_path TO "{esquema}"')
                cur.execute(sql)
                cur.execute(
                    "SELECT count(*) FROM information_schema.tables WHERE table_schema = %s",
                    (esquema,),
                )
                criadas = cur.fetchone()[0]
            print(f"  {nome:<40} OK — {criadas} tabelas criadas")
        except Exception as exc:  # noqa: BLE001 - o ponto do script é reportar a falha
            falhas += 1
            print(f"  {nome:<40} FALHOU: {str(exc).splitlines()[0]}")

    print()
    print(f"{falhas} projeto(s) com DDL que não aplica")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
