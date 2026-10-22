"""Quanto da acurácia era POSSÍVEL em cada configuração.

`avaliar.py` responde "quanto o sistema acertou". Este responde a pergunta que
vem antes dela e que vinha ficando sem resposta: **quanto havia para acertar**.

O método é deliberadamente burro, e a burrice é o que o torna defensável: uma
coluna do gabarito só é considerada recuperável se o nome dela **aparece
literalmente** em algum arquivo que a ferramenta enxerga. Se `encrypted_password`
não está escrito em lugar nenhum do repositório, nenhuma leitura do código o
produziria — ele veio da gem Devise, que não está ali.

Com precisão de 100% (o que o corpus mostra na maioria das células), o teto de F1
é `2r/(1+r)`, onde `r` é a fração recuperável. É um teto de informação, não de
modelo: nem um LLM perfeito passaria dele sem adivinhar.

**Limite do método, e ele é sério:** o teste é literal, então só vale para
linguagens que escrevem a coluna com o mesmo nome que o campo — Ruby, PHP,
Python. Em C# e Java o campo é `FirstName` e a coluna é `first_name`, e o teste
declara "não recuperável" algo que qualquer leitor recupera. Nessas linguagens o
número sai abaixo do real e **não deve ser usado**; o script marca quais são.

    PYTHONPATH=. python scripts/teto.py
    PYTHONPATH=. python scripts/teto.py --sem-schema
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from scripts.avaliar import GABARITOS, pasta_do_projeto  # noqa: E402

# Linguagens em que o nome do campo no código difere do nome da coluna por
# convenção de capitalização. O teste literal subestima nelas, então o número sai
# marcado em vez de sair errado em silêncio.
_CAPITALIZACAO_DIVERGENTE = {
    "aspnetcore-realworld-example-app": "C# (PascalCase -> snake_case)",
    "spring-petclinic": "Java (camelCase -> snake_case)",
    "03-biblioteca-java": "Java (camelCase -> snake_case)",
    "04-catalogo-streaming": "C# e Protobuf misturados",
}


def _texto_visivel(pasta: Path, esconder: list[str]) -> str:
    """Tudo que a ferramenta poderia ler, com os arquivos de schema fora.

    Deliberadamente NÃO usa `scan()`: a pergunta é o que existe no repositório,
    não o que o filtro de scan deixa passar. Usar o scan aqui misturaria o teto de
    informação com as decisões da Fase 1, e o objetivo é justamente poder comparar
    as duas coisas.
    """
    partes: list[str] = []
    for arquivo in pasta.rglob("*"):
        if not arquivo.is_file():
            continue
        rel = arquivo.relative_to(pasta).as_posix()
        if rel.startswith(".git") or any(e in rel for e in esconder):
            continue
        try:
            partes.append(arquivo.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n".join(partes)


def teto_de(gabarito: dict, sem_schema: bool) -> tuple[int, int, list[str]]:
    """(recuperáveis, total, exemplos do que não aparece em lugar nenhum)."""
    pasta = pasta_do_projeto(gabarito)
    esconder = gabarito.get("arquivos_de_schema", []) if sem_schema else []
    texto = _texto_visivel(pasta, esconder)

    recuperaveis = total = 0
    ausentes: list[str] = []
    for nome, tabela in gabarito["tabelas"].items():
        for coluna in tabela["colunas"]:
            total += 1
            if coluna in texto:
                recuperaveis += 1
            else:
                ausentes.append(f"{nome}.{coluna}")
    return recuperaveis, total, ausentes


def main() -> int:
    parser = argparse.ArgumentParser(description="Teto de acurácia por configuração")
    parser.add_argument("--projeto", help="avalia só este projeto")
    parser.add_argument(
        "--sem-schema",
        action="store_true",
        help="esconde os `arquivos_de_schema` declarados, como em avaliar.py",
    )
    parser.add_argument("--detalhes", action="store_true", help="lista o que não é recuperável")
    args = parser.parse_args()

    arquivos = sorted(GABARITOS.glob("*.json"))
    if args.projeto:
        arquivos = [a for a in arquivos if a.stem == args.projeto]
        if not arquivos:
            print(f"Nenhum gabarito para '{args.projeto}'")
            return 1

    print(f"{'configuração':<42} {'recuperável':>12} {'teto F1':>9}")
    print("-" * 66)
    marcados = []
    for arquivo in arquivos:
        gabarito = json.loads(arquivo.read_text(encoding="utf-8"))
        if gabarito.get("escopo") == "escala":
            continue
        if args.sem_schema and not gabarito.get("arquivos_de_schema"):
            continue
        recuperaveis, total, ausentes = teto_de(gabarito, args.sem_schema)
        if not total:
            continue
        r = recuperaveis / total
        teto = 2 * r / (1 + r)
        marca = ""
        if gabarito["projeto"] in _CAPITALIZACAO_DIVERGENTE:
            marca = " (*)"
            marcados.append(gabarito["projeto"])
        rotulo = gabarito["projeto"] + (" (sem schema)" if args.sem_schema else "")
        print(f"{rotulo:<42} {recuperaveis:>4}/{total:<3} {r:>4.0%} {teto:>8.1%}{marca}")
        if args.detalhes and ausentes:
            print(f"    não aparece no repositório: {', '.join(ausentes[:14])}")

    if marcados:
        print()
        print("(*) teste literal subestima nestes — o nome do campo no código difere")
        print("    do nome da coluna por capitalização. Não usar o número:")
        for projeto in marcados:
            print(f"      {projeto}: {_CAPITALIZACAO_DIVERGENTE[projeto]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
