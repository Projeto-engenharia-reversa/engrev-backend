"""Uma análise completa pela API real, com provedor de LLM de verdade.

O `avaliar.py` chama as etapas da pipeline direto, em processo. Isso pula a
camada inteira que o usuário de fato atravessa: HTTP, autenticação, upload do ZIP,
extração, persistência dos artefatos e o cálculo de custo gravado no banco.

Nenhuma medição cobre esse caminho — e é justamente onde um defeito seria
invisível para o corpus e visível para quem usa.

    docker compose up -d db
    LLM_PROVIDER=gemini PYTHONPATH=. python scripts/ponta_a_ponta.py 02-loja-python
"""

from __future__ import annotations

import io
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

AVALIACAO = Path(__file__).resolve().parents[1] / "avaliacao"


def _zip_da_pasta(pasta: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for arquivo in pasta.rglob("*"):
            if arquivo.is_file() and ".git" not in arquivo.parts:
                zf.write(arquivo, arquivo.relative_to(pasta).as_posix())
    return buffer.getvalue()


def main() -> int:
    from fastapi.testclient import TestClient

    from app.core.config import settings
    from app.main import app

    nome = sys.argv[1] if len(sys.argv) > 1 else "02-loja-python"
    pasta = AVALIACAO / "projetos" / nome
    if not pasta.exists():
        pasta = AVALIACAO / "projetos-externos" / nome
    if not pasta.exists():
        print(f"projeto não encontrado: {nome}")
        return 1

    print(f"projeto: {nome} | provedor: {settings.LLM_PROVIDER} | modelo: {settings.LLM_MODEL}")
    if settings.LLM_PROVIDER == "mock":
        print("AVISO: rodando em mock — isto não exercita o provedor real.")

    with TestClient(app) as client:
        email = f"e2e{int(time.time())}@engrev.dev"
        r = client.post("/api/auth/register", json={"email": email, "password": "senha12345"})
        assert r.status_code == 201, r.text
        headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

        projeto = client.post("/api/projects", json={"name": f"e2e {nome}"}, headers=headers).json()
        print(f"  projeto criado: id={projeto['id']}")

        upload = client.post(
            f"/api/projects/{projeto['id']}/upload",
            headers=headers,
            files={"file": (f"{nome}.zip", _zip_da_pasta(pasta), "application/zip")},
        )
        assert upload.status_code == 200, upload.text
        print(f"  upload: {upload.json()['accepted_files']}/{upload.json()['total_files']} arquivos aceitos")

        run = client.post(f"/api/runs/{projeto['id']}/analyze", headers=headers)
        assert run.status_code == 202, run.text
        run_id = run.json()["id"]

        estado = ""
        for _ in range(200):
            estado = client.get(f"/api/runs/{run_id}/status", headers=headers).json()["status"]
            if estado in ("done", "failed"):
                break
            time.sleep(1)
        print(f"  run {run_id}: {estado}")
        if estado != "done":
            detalhe = client.get(f"/api/runs/{run_id}", headers=headers).json()
            print(f"  erro: {detalhe.get('error_message')}")
            return 1

        artefatos = client.get(f"/api/artifacts/{run_id}", headers=headers).json()
        print(f"  artefatos: {', '.join(sorted(a['filename'] for a in artefatos))}")

        metricas = client.get(f"/api/runs/{run_id}/metrics", headers=headers).json()
        custo = metricas["total_cost_usd"]
        print(f"  tokens: {metricas['total_tokens']:,} | custo: USD {custo:.4f} = R$ {custo * 5.15:.3f}")
        for etapa in metricas["steps"]:
            print(f"    {etapa['step']:<12} {etapa['model']:<24} "
                  f"{etapa['input_tokens']:>7,} in / {etapa['output_tokens']:>6,} out  "
                  f"USD {etapa['cost_usd']:.4f}")

        # O que este script existe para pegar: custo zerado no banco com provedor
        # pago. Era o estado real até a tabela de preços do Gemini entrar.
        if settings.LLM_PROVIDER != "mock" and custo <= 0:
            print("\nFALHOU: provedor pago e custo gravado como zero.")
            return 1
        if not artefatos:
            print("\nFALHOU: run concluída sem artefato nenhum.")
            return 1

    print("\nponta a ponta OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
