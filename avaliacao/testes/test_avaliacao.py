"""Porteiro de regressão: a extração determinística contra os gabaritos.

Mede a extração inteira contra o modelo que um analista extrairia lendo o
código, que é o que a ferramenta promete entregar.

Os pisos abaixo são o **medido hoje**, não uma meta: existem para acusar queda,
não para dar nota. Ao melhorar a extração, suba o piso junto — um piso frouxo
deixa passar exatamente a regressão que ele deveria pegar.

Só as Fases 1-3: determinístico, sem LLM, sem cota. A avaliação com a Fase 4
(`scripts/avaliar.py --com-llm`) varia entre rodadas e por isso não serve de
porteiro.
"""

import json
from importlib import import_module
from pathlib import Path

import pytest

avaliar_mod = import_module("scripts.avaliar")

GABARITOS = Path(__file__).resolve().parents[1] / "gabaritos"

# Os projetos de terceiros não são distribuídos com o repositório, cada um tem a
# sua licença. Sem eles estes testes pulam em vez de falhar, para que um clone
# limpo não acuse erro que não existe.
AUSENTE = "projeto não presente em avaliacao/; ver o README para clonar o corpus"

# (projeto, f1 mínimo de tabelas, de colunas, de fks)
#
# Os pisos são o **medido hoje**, não uma meta: existem para acusar queda. Ao
# melhorar a extração, suba o piso junto — piso frouxo deixa passar exatamente a
# regressão que ele deveria pegar.
#
# Metade do corpus ficava de fora desta lista, e justamente a metade que mais
# importa: os projetos externos. Uma regressão em qualquer um deles passava pela
# suíte em silêncio.
_PISOS = [
    # Autorais — extração determinística resolve inteiro.
    ("01-helpdesk-frontend", 1.0, 0.97, 1.0),
    ("02-loja-python", 1.0, 1.0, 1.0),
    ("03-biblioteca-java", 1.0, 1.0, 1.0),
    ("04-catalogo-streaming", 1.0, 1.0, 1.0),
    # Externos com parser dedicado. Os números são mais baixos porque aqui o
    # determinístico sozinho não dá conta, é o LLM que fecha a conta. O piso
    # trava a contribuição determinística.
    ("spring-petclinic", 1.0, 1.0, 1.0),
    ("aspnetcore-realworld-example-app", 0.75, 0.66, 0.55),
    ("nestjs-realworld-example-app", 0.66, 0.72, 0.0),
    # 0.62 -> 0.66 quando a regra de nome de MODULO passou a descartar
    # `exceptions.py` inteiro (`profile_does_not_exists` era entidade).
    # 0.66 -> 0.71 quando os catálogos de tradução (`locale/*.po`) sairam do scan.
    ("django-realworld-example-app", 0.71, 0.68, 0.0),
    # Braço de generalização: fora do domínio Conduit, 36 tabelas contra 7. O
    # determinístico acha TODAS as 36 (recall 100%); o que segura a precisão são
    # nomes do `grocy.openapi.json` que descrevem recursos da API e não tabelas
    # (`StockEntry` para `stock`, `habits` de antes do rename para `chores`).
    # FK é None: o projeto não declara constraint nenhuma (ver o gabarito).
    ("grocy", 0.84, 0.95, None),
    # Testes limpos: projetos tomados como vieram da internet, sem esconder nem
    # acrescentar nada. Entraram depois e nao estavam travados por teste nenhum.
    #
    # mall: 76 tabelas e 669 colunas resolvidas SEM LLM, o maior do corpus. Foi
    # 52.8% ate o filtro de `resultMap` do MyBatis separar o que o mapper declara
    # do que ele so projeta em JOIN. FK e None: o schema nao declara constraint.
    ("mall", 1.0, 1.0, None),
    ("vaultwarden", 0.96, 0.98, 0.80),
    # marzban: a precisao baixa de tabela e o custo de ler modelos Pydantic da
    # API como se fossem entidades; o LLM fecha em 100%.
    ("marzban", 0.60, 0.93, 0.80),
    # laravel, rails e golang-gin NÃO entram: PHP, Ruby e Go não têm parser, o
    # determinístico é zero por contrato, e um piso de 0.0 pareceria portão sem
    # ser. Quem trava aquele comportamento é
    # `test_linguagem_sem_parser_cai_no_raw_fallback`, que falha nos dois sentidos
    # (se ganharem parser ou se o raw-fallback parar).
]


@pytest.mark.parametrize(("projeto", "min_tabelas", "min_colunas", "min_fks"), _PISOS)
def test_extracao_nao_regride(projeto, min_tabelas, min_colunas, min_fks):
    gabarito = json.loads((GABARITOS / f"{projeto}.json").read_text(encoding="utf-8"))
    pasta = avaliar_mod.pasta_do_projeto(gabarito)
    if not pasta.exists():
        pytest.skip(AUSENTE)
    obtidas = avaliar_mod.extrair(pasta, com_llm=False)
    r = avaliar_mod.avaliar(
        gabarito["tabelas"], obtidas, gabarito.get("fks_avaliaveis", True)
    )

    assert r["tabelas"].f1 >= min_tabelas, (
        f"tabelas F1={r['tabelas'].f1:.1%} — faltando {r['tabelas'].exemplos_faltando}, "
        f"a mais {r['tabelas'].exemplos_a_mais}"
    )
    assert r["colunas"].f1 >= min_colunas, (
        f"colunas F1={r['colunas'].f1:.1%} — faltando {r['colunas'].exemplos_faltando[:8]}, "
        f"a mais {r['colunas'].exemplos_a_mais[:8]}"
    )
    if min_fks is None:
        assert not r.get("fks_avaliaveis", True), (
            "o gabarito passou a declarar FKs avaliáveis — dar um piso a elas"
        )
        return
    assert r["fks"].f1 >= min_fks, (
        f"fks F1={r['fks'].f1:.1%} — faltando {r['fks'].exemplos_faltando[:8]}, "
        f"a mais {r['fks'].exemplos_a_mais[:8]}"
    )


def test_gabaritos_declaram_procedencia():
    """Gabarito sem origem declarada é opinião. Se ninguém sabe de onde a verdade
    veio, o número que ele produz não é defensável."""
    for arquivo in GABARITOS.glob("*.json"):
        gabarito = json.loads(arquivo.read_text(encoding="utf-8"))
        assert gabarito.get("fonte_da_verdade"), f"{arquivo.name} sem fonte_da_verdade"
        assert gabarito.get("confianca"), f"{arquivo.name} sem confianca"
        assert gabarito.get("tabelas"), f"{arquivo.name} sem tabelas"


@pytest.mark.parametrize(
    "projeto",
    [
        "laravel-realworld-example-app",
        "rails-realworld-example-app",
        "golang-gin-realworld-example-app",
        # Elixir/Ecto e migration Knex: mesmo contrato, causa diferente. Nao e
        # que falte parser para a linguagem -- o parser de JS existe e nao ve
        # entidade em `knex.schema.createTable(...)`, que e CODIGO e nao
        # declaracao. Sao os dois projetos do corpus onde nenhuma rota
        # deterministica funciona e so o LLM entrega (e entrega 100%).
        "teslamate",
        "matterwiki",
    ],
)
def test_linguagem_sem_parser_cai_no_raw_fallback(projeto):
    """PHP, Ruby e Go nao tem parser dedicado. O contrato e explicito: RawEvidence
    nunca vira TableDef, entao o deterministico devolve ZERO tabelas e o arquivo
    vai inteiro como texto bruto para o LLM avaliar.

    Este teste trava esse contrato nos dois sentidos: se alguem adicionar um
    parser para essas linguagens, ele falha e obriga a revisar o gabarito; e se o
    raw-fallback parar de coletar evidencia, ele acusa o silencio -- que seria
    pior, porque o projeto simplesmente sumiria da analise sem erro nenhum.
    """
    from pathlib import Path

    from app.pipeline.steps import build_structural, parse, scan

    pasta = Path(avaliar_mod.EXTERNOS) / projeto
    if not pasta.exists():
        pytest.skip(AUSENTE)
    modelo = build_structural(parse(scan(pasta), pasta), pasta)
    assert modelo.tables == [], "surgiu parser dedicado: revisar o gabarito e este teste"
    assert len(modelo.raw_evidence) > 20, "o raw-fallback parou de coletar evidencia"


def test_metrica_nao_reporta_acerto_vacuo():
    """Com nenhuma tabela casada, colunas e FKs precisam dar 0%, nao 100%. Os
    contadores ficavam vazios e `Contagem` devolve 1.0 para o caso vazio -- o
    numero mentia justamente no cenario mais critico."""
    gabarito = {"users": {"colunas": {"id": "integer", "email": "string"}, "fks": {}}}
    r = avaliar_mod.avaliar(gabarito, {})
    assert r["tabelas"].f1 == 0.0
    assert r["colunas"].revocacao == 0.0
    assert r["colunas"].faltando == 2


def _tabela(colunas, fks=None):
    return {"colunas": colunas, "fks": fks or {}}


def test_fk_com_nome_divergente_conta_como_acerto_e_e_reportada():
    """`from_profile_id` e `follower_id` sao a MESMA FK para `profiles`. Sem
    casar, uma divergencia de nomenclatura virava quatro penalidades: faltando e
    sobrando nas colunas, e o mesmo par nas FKs."""
    gabarito = {
        "profiles": _tabela({"id": "integer"}),
        "profile_follows": _tabela(
            {"id": "integer", "from_profile_id": "integer", "to_profile_id": "integer"},
            {"from_profile_id": "profiles", "to_profile_id": "profiles"},
        ),
    }
    obtidas = {
        "profiles": _tabela({"id": "integer"}),
        "profile_follows": _tabela(
            {"id": "integer", "follower_id": "integer", "followed_id": "integer"},
            {"follower_id": "profiles", "followed_id": "profiles"},
        ),
    }
    r = avaliar_mod.avaliar(gabarito, obtidas)
    assert r["colunas"].f1 == 1.0, f"faltando={r['colunas'].exemplos_faltando}"
    assert r["fks"].f1 == 1.0
    # E a divergencia aparece: nada e perdoado em silencio.
    assert len(r["divergencias_de_coluna"]) == 2


def test_coluna_comum_com_nome_diferente_continua_sendo_erro():
    """A guarda que impede a regra de virar maquiagem: sem FK nao ha sinal
    estrutural nenhum, e casar por semelhanca de nome seria inventar acerto."""
    gabarito = {"users": _tabela({"id": "integer", "bio": "string"})}
    obtidas = {"users": _tabela({"id": "integer", "biography": "string"})}
    r = avaliar_mod.avaliar(gabarito, obtidas)
    assert r["colunas"].faltando == 1
    assert r["colunas"].a_mais == 1
    assert r["divergencias_de_coluna"] == []


def test_fk_para_tabela_alvo_diferente_nao_casa():
    """So casa FK que aponta para o MESMO alvo. `author_id->users` e
    `owner_id->accounts` sao coisas distintas, por mais parecidas que pareçam."""
    gabarito = {
        "users": _tabela({"id": "integer"}),
        "accounts": _tabela({"id": "integer"}),
        "posts": _tabela({"id": "integer", "author_id": "integer"}, {"author_id": "users"}),
    }
    obtidas = {
        "users": _tabela({"id": "integer"}),
        "accounts": _tabela({"id": "integer"}),
        "posts": _tabela({"id": "integer", "owner_id": "integer"}, {"owner_id": "accounts"}),
    }
    r = avaliar_mod.avaliar(gabarito, obtidas)
    assert r["divergencias_de_coluna"] == []
    assert r["fks"].f1 == 0.0


def test_tabela_oficial_carrega_a_configuracao_que_a_produziu():
    """A tabela em Markdown é usada fora do console, então o carimbo da
    configuração precisa estar no corpo dela e não só no cabeçalho da execução.
    Sem isso, duas tabelas de configurações diferentes ficam indistinguíveis.
    """
    from types import SimpleNamespace

    carimbo = avaliar_mod._carimbo_da_configuracao(
        SimpleNamespace(sem_reconcile=False), repeticoes=3
    )
    assert "AMOSTRAS_MODELAGEM=" in carimbo, "o N precisa aparecer no carimbo"
    assert "reconciliação ligada" in carimbo
    assert "colunas por" in carimbo

    ablacao = avaliar_mod._carimbo_da_configuracao(
        SimpleNamespace(sem_reconcile=True), repeticoes=3
    )
    assert "reconciliação DESLIGADA" in ablacao, (
        "sem isto as duas tabelas ficam indistinguíveis"
    )


def test_projeto_isolado_sobrevive_a_falha_de_uma_rodada(monkeypatch, capsys):
    """`--oficial` captura a falha de uma rodada e segue; `--projeto` deixava a
    exceção subir e perdia as repetições já concluídas. As duas rotas precisam da
    mesma robustez.
    """
    import sys
    from types import SimpleNamespace

    chamadas = {"n": 0}

    def extrair_instavel(*args, **kwargs):
        chamadas["n"] += 1
        if chamadas["n"] == 2:
            raise RuntimeError("provedor caiu")
        return {"users": {"colunas": {"id": "integer"}, "fks": {}}}

    monkeypatch.setattr(avaliar_mod, "extrair", extrair_instavel)
    monkeypatch.setattr(
        sys, "argv",
        ["avaliar.py", "--projeto", "02-loja-python", "--repeticoes", "3"],
    )
    codigo = avaliar_mod.main()
    saida = capsys.readouterr().out

    assert codigo == 0, "uma rodada que cai nao pode derrubar o comando"
    assert "rodada falhou" in saida, "a falha tem que ser reportada, nao engolida"
    assert chamadas["n"] == 3, "as repeticoes seguintes precisam acontecer"


def test_total_nao_reporta_acerto_vacuo_quando_tudo_falha(monkeypatch, capsys):
    """O mesmo `100% vacuo` do teste acima, mas no agregado.

    A resiliencia acrescentada ao `--projeto` (o teste anterior) criou o caminho
    em que nenhuma rodada completa e mesmo assim o TOTAL imprime. Como `Contagem`
    devolve 1.0 para o caso vazio, a saida era `tabelas 100%` com codigo 0 -- uma
    falha total com cara de sucesso perfeito. O projeto ja tinha corrigido este
    bug por projeto; a correcao de robustez o reintroduziu um nivel acima.
    """
    import sys

    def sempre_cai(*args, **kwargs):
        raise RuntimeError("provedor caiu")

    monkeypatch.setattr(avaliar_mod, "extrair", sempre_cai)
    monkeypatch.setattr(sys, "argv", ["avaliar.py", "--projeto", "02-loja-python"])
    codigo = avaliar_mod.main()
    saida = capsys.readouterr().out

    assert codigo != 0, "medicao sem nenhum dado nao pode sair com sucesso"
    assert "nenhum projeto foi medido" in saida
    assert "100.0%" not in saida, "o TOTAL vacuo voltou a mentir"
