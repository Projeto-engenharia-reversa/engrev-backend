"""Submete uma pasta ao pipeline real, pelos mesmos endpoints que o front usa.

Faz login, cria o projeto, zipa a pasta em memoria, envia, dispara a analise,
acompanha o progresso e baixa os artefatos gerados. Nada aqui atalha o
orquestrador: e o mesmo caminho de um upload feito pela interface.

Uso:
    PYTHONPATH=. python scripts/submit_project.py avaliacao/projetos/03-biblioteca-java
    PYTHONPATH=. python scripts/submit_project.py <pasta> --url http://localhost:8000
"""

import argparse
import io
import json
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.core.config import settings  # noqa: E402

TIMEOUT_ANALISE_SEGUNDOS = 600
INTERVALO_POLL_SEGUNDOS = 3
# Artefatos vao para storage/, que ja esta no .gitignore -- gravar dentro da
# pasta analisada contaminaria a proxima rodada, porque o scan leria os
# proprios resultados como se fossem codigo-fonte do projeto.
DESTINO_PADRAO = Path(__file__).resolve().parents[1] / "storage" / "analises"


def zipar(pasta: Path) -> bytes:
    """Compacta a pasta em memoria, com caminhos relativos a ela.

    Nao filtra nada: o `extract_zip` do servidor ja aplica o `should_ignore` e o
    limite por arquivo, e devolve o manifesto do que aceitou ou excluiu.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as arquivo:
        for caminho in sorted(pasta.rglob("*")):
            if caminho.is_file():
                arquivo.write(caminho, caminho.relative_to(pasta).as_posix())
    return buffer.getvalue()


# Conta propria do script, usada quando as credenciais do seed nao servem --
# tipicamente um .env antigo que ainda tem `admin@engrev.local`, recusado com 422
# pelo proprio login (`EmailStr` rejeita `.local` por ser dominio reservado).
# O padrao ja foi corrigido em config.py, mas .env de quem clonou antes nao muda
# sozinho.
EMAIL_FALLBACK = "scripts@engrev.dev"
SENHA_FALLBACK = "engrev-scripts-2026"


def _tentar_par(cliente: httpx.Client, email: str, senha: str) -> str | None:
    """Tenta logar; registra a conta se ela ainda nao existir."""
    credenciais = {"email": email, "password": senha}
    resposta = cliente.post("/api/auth/login", json=credenciais)
    if resposta.status_code == 401:
        resposta = cliente.post("/api/auth/register", json={**credenciais, "name": "EngRev Scripts"})
    if resposta.status_code == 422:
        return None
    resposta.raise_for_status()
    return resposta.json()["access_token"]


def autenticar(cliente: httpx.Client) -> str:
    token = _tentar_par(cliente, settings.SEED_ADMIN_EMAIL, settings.SEED_ADMIN_PASSWORD)
    if token is not None:
        return token

    print(f"  aviso: a API recusou '{settings.SEED_ADMIN_EMAIL}' como e-mail valido;")
    print(f"         usando a conta propria do script ({EMAIL_FALLBACK})")
    token = _tentar_par(cliente, EMAIL_FALLBACK, SENHA_FALLBACK)
    if token is None:
        raise RuntimeError("nao foi possivel autenticar com nenhuma das credenciais")
    return token


def enviar(cliente: httpx.Client, pasta: Path) -> int:
    projeto = cliente.post("/api/projects", json={"name": pasta.name})
    projeto.raise_for_status()
    projeto_id = projeto.json()["id"]
    print(f"  projeto #{projeto_id} criado")

    conteudo = zipar(pasta)
    print(f"  zip com {len(conteudo) / 1024:.1f} KB")

    upload = cliente.post(
        f"/api/projects/{projeto_id}/upload",
        files={"file": (f"{pasta.name}.zip", conteudo, "application/zip")},
    )
    upload.raise_for_status()
    resultado = upload.json()
    print(f"  {resultado['accepted_files']}/{resultado['total_files']} arquivos aceitos")
    for item in resultado["items"]:
        if item["status"] != "ok":
            print(f"    excluido: {item['path']} ({item['reason']})")
    return projeto_id


def analisar(cliente: httpx.Client, projeto_id: int) -> dict:
    inicio = cliente.post(f"/api/runs/{projeto_id}/analyze")
    inicio.raise_for_status()
    run_id = inicio.json()["id"]
    print(f"  run #{run_id} iniciada")

    limite = time.monotonic() + TIMEOUT_ANALISE_SEGUNDOS
    ultimo_estagio = None
    while time.monotonic() < limite:
        status = cliente.get(f"/api/runs/{run_id}/status")
        status.raise_for_status()
        dados = status.json()
        if dados["stage"] != ultimo_estagio:
            ultimo_estagio = dados["stage"]
            print(f"    [{dados['progress']:.0%}] {dados['stage']}")
        if dados["status"] == "done":
            return {"run_id": run_id, "ok": True}
        if dados["status"] == "failed":
            print(f"  FALHOU: {dados.get('error_message')}")
            return {"run_id": run_id, "ok": False}
        time.sleep(INTERVALO_POLL_SEGUNDOS)

    print(f"  tempo esgotado apos {TIMEOUT_ANALISE_SEGUNDOS}s")
    return {"run_id": run_id, "ok": False}


def relatar(cliente: httpx.Client, run_id: int, destino: Path) -> None:
    # GET /api/runs/{id} responde 500 hoje (RunDetail.model_validate le a relacao
    # ORM scanned_files onde o schema espera um int). Nao e fatal para o que
    # interessa aqui, entao seguimos para as metricas e os artefatos.
    detalhe = cliente.get(f"/api/runs/{run_id}")
    if detalhe.status_code == 200:
        dados = detalhe.json()
        print(f"\n  {dados['scanned_files']} arquivos | {dados['entities']} entidades | {dados['relationships']} relacionamentos")
    else:
        print(f"\n  aviso: GET /api/runs/{run_id} devolveu {detalhe.status_code}; seguindo sem o resumo")

    metricas = cliente.get(f"/api/runs/{run_id}/metrics")
    if metricas.status_code == 200:
        m = metricas.json()
        print(f"  {m['total_tokens']} tokens (US$ {m['total_cost_usd']:.4f})")
        for passo in m["steps"]:
            print(f"    {passo['step']}: {passo['model']} | {passo['input_tokens']} in / {passo['output_tokens']} out")

    artefatos = cliente.get(f"/api/artifacts/{run_id}")
    artefatos.raise_for_status()
    destino.mkdir(parents=True, exist_ok=True)
    print(f"\n  artefatos em {destino}")
    for artefato in artefatos.json():
        download = cliente.get(f"/api/artifacts/{artefato['id']}/download")
        download.raise_for_status()
        (destino / artefato["filename"]).write_bytes(download.content)
        print(f"    {artefato['filename']} ({artefato['size_bytes']} bytes)")

    modelo = destino / "model.json"
    if modelo.exists():
        _resumir_modelo(json.loads(modelo.read_text(encoding="utf-8")))


def _lados(modelo: dict, rel: dict) -> tuple[str, str]:
    """Lado "one" primeiro numa relacao 1:N, achando quem carrega a coluna de FK."""
    a, b = rel["table_a"], rel["table_b"]
    if rel.get("through") or rel.get("kind") != "one-to-many":
        return a, b
    colunas_de = {t["name"]: t.get("columns", []) for t in modelo.get("tables", [])}
    for many, one in ((a, b), (b, a)):
        if any(c.get("fk_table") == one for c in colunas_de.get(many, [])):
            return one, many
    return a, b


def _resumir_modelo(modelo: dict) -> None:
    print("\n  Modelo conceitual:")
    for tabela in modelo.get("tables", []):
        colunas = ", ".join(c["name"] for c in tabela.get("columns", []))
        print(f"    {tabela['name']} [{tabela.get('confidence') or '?'}]: {colunas}")
    relacionamentos = modelo.get("relationships", [])
    if relacionamentos:
        print("\n  Relacionamentos:")
        for rel in relacionamentos:
            through = f" via {rel['through']}" if rel.get("through") else ""
            # A ordem table_a/table_b do LLM nao indica a direcao -- quem manda e a
            # tabela que tem a coluna de FK. Imprimir cru mostrava a relacao invertida
            # em relacao ao report.md, que resolve os lados de verdade.
            esquerda, direita = _lados(modelo, rel)
            print(f"    {esquerda} -({rel['kind']})-> {direita}{through}")
    issues = modelo.get("issues", [])
    if issues:
        print(f"\n  Issues ({len(issues)}):")
        for issue in issues:
            print(f"    [{issue['severity']}] {issue['message']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pasta", type=Path, help="pasta do projeto a analisar")
    parser.add_argument("--url", default="http://localhost:8000", help="base da API")
    parser.add_argument("--destino", type=Path, default=None, help="onde gravar os artefatos")
    args = parser.parse_args()

    pasta = args.pasta.resolve()
    if not pasta.is_dir():
        print(f"Pasta nao encontrada: {pasta}")
        return 1

    destino = args.destino or (DESTINO_PADRAO / pasta.name)
    print(f"Analisando {pasta.name} via {args.url}")

    with httpx.Client(base_url=args.url, timeout=120) as cliente:
        try:
            token = autenticar(cliente)
        except httpx.ConnectError:
            print(f"Nao consegui conectar em {args.url}. O backend esta rodando?")
            return 1
        cliente.headers["Authorization"] = f"Bearer {token}"

        projeto_id = enviar(cliente, pasta)
        resultado = analisar(cliente, projeto_id)
        relatar(cliente, resultado["run_id"], destino)

    return 0 if resultado["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
