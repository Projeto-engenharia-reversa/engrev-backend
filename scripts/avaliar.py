"""Mede a extração da pipeline contra os gabaritos de `avaliacao/gabaritos/`.

Por padrão roda só as Fases 1-3 (scan, parse, structural): determinístico,
repetível e sem gastar cota. É esse número que serve de porteiro contra
regressão — a variação do LLM tornaria a métrica ruidosa demais para isso.

Com `--com-llm` mede o que o usuário de fato recebe, passando pela modelagem e
pela reconciliação. Custa cota e varia entre rodadas; serve para responder
"quanto o LLM ajuda ou atrapalha", não para travar regressão.

    PYTHONPATH=. python scripts/avaliar.py
    PYTHONPATH=. python scripts/avaliar.py --projeto 03-biblioteca-java
    PYTHONPATH=. python scripts/avaliar.py --com-llm
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402

# O console do Windows usa cp1252 por padrão e engasga com os acentos do relatório.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

AVALIACAO = Path(__file__).resolve().parents[1] / "avaliacao"
GABARITOS = AVALIACAO / "gabaritos"
RAIZ = AVALIACAO / "projetos"
# Projetos de terceiros não são distribuídos aqui, cada um tem a sua licença.
# O campo `origem` de cada gabarito traz a URL para cloná-los nesta pasta.
EXTERNOS = AVALIACAO / "projetos-externos"


def pasta_do_projeto(gabarito: dict) -> Path:
    raiz = EXTERNOS if gabarito.get("externo") else RAIZ
    return raiz / gabarito["projeto"]

# Distinguir integer de decimal a partir de `horas_gastas = 0` num JS é chute, não
# medida. Agrupar por família mede o que dá para medir: se a coluna foi entendida
# como número, data, booleano ou texto.
_FAMILIA = {
    "integer": "numero",
    "decimal": "numero",
    "float": "numero",
    "date": "tempo",
    "datetime": "tempo",
    "timestamp": "tempo",
    "boolean": "booleano",
    "string": "texto",
    "text": "texto",
    "uuid": "texto",
    "json": "estrutura",
}

_LIMIAR_DE_CASAMENTO = 0.5


def familia(tipo: str) -> str:
    return _FAMILIA.get(tipo, tipo)


@dataclass
class Contagem:
    """Acertos, falsos positivos e falsos negativos de uma dimensão."""

    acertos: int = 0
    a_mais: int = 0
    faltando: int = 0
    exemplos_a_mais: list[str] = field(default_factory=list)
    exemplos_faltando: list[str] = field(default_factory=list)

    def somar(self, esperado: set[str], obtido: set[str], prefixo: str = "") -> None:
        self.acertos += len(esperado & obtido)
        extras = obtido - esperado
        ausentes = esperado - obtido
        self.a_mais += len(extras)
        self.faltando += len(ausentes)
        self.exemplos_a_mais.extend(f"{prefixo}{n}" for n in sorted(extras))
        self.exemplos_faltando.extend(f"{prefixo}{n}" for n in sorted(ausentes))

    @property
    def precisao(self) -> float:
        total = self.acertos + self.a_mais
        return self.acertos / total if total else 1.0

    @property
    def revocacao(self) -> float:
        total = self.acertos + self.faltando
        return self.acertos / total if total else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precisao, self.revocacao
        return 2 * p * r / (p + r) if (p + r) else 0.0


def casar_tabelas(gabarito: dict, obtidas: dict) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """Casa entidade do gabarito com entidade extraída.

    Primeiro por nome exato; o que sobrar, pela maior sobreposição de colunas.
    Uma entidade é identificada pelos atributos que carrega, não pelo rótulo —
    e separar as duas coisas evita que uma regra de pluralização errada afunde a
    métrica de extração, escondendo se o problema é de nome ou de conteúdo.
    """
    pares: dict[str, str] = {}
    divergencias: list[tuple[str, str]] = []

    for nome in gabarito:
        if nome in obtidas:
            pares[nome] = nome

    sobram_gab = [n for n in gabarito if n not in pares]
    sobram_obt = [n for n in obtidas if n not in pares.values()]

    for nome in sobram_gab:
        alvo_cols = set(gabarito[nome]["colunas"])
        melhor, melhor_score = None, 0.0
        for candidato in sobram_obt:
            cols = set(obtidas[candidato]["colunas"])
            uniao = alvo_cols | cols
            score = len(alvo_cols & cols) / len(uniao) if uniao else 0.0
            if score > melhor_score:
                melhor, melhor_score = candidato, score
        if melhor is not None and melhor_score >= _LIMIAR_DE_CASAMENTO:
            pares[nome] = melhor
            divergencias.append((nome, melhor))
            sobram_obt.remove(melhor)

    return pares, divergencias


def casar_colunas(esperado: dict, obtido: dict, traduz_tabela: dict) -> dict[str, str]:
    """Nome da coluna obtida -> nome equivalente no gabarito, quando divergem.

    Mesmo princípio que `casar_tabelas` já aplica às tabelas, e pelo mesmo motivo:
    `from_profile_id` e `follower_id` são a MESMA chave estrangeira para
    `profiles`, com nomes diferentes. Sem isto, uma divergência de nomenclatura
    vira quatro penalidades — uma faltando e uma sobrando nas colunas, e o mesmo
    par nas FKs.

    A regra é estreita **de propósito e estrutural**: só casa coluna que (a) não
    casou por nome exato, (b) é FK dos dois lados, e (c) aponta para a mesma
    tabela alvo. Coluna comum com nome diferente (`bio` vs `biography`) continua
    contando como erro — ali não há sinal nenhum, e casar por semelhança de nome
    seria maquiar o número em vez de medi-lo.
    """
    sobram_gab = set(esperado["colunas"]) - set(obtido["colunas"])
    sobram_obt = set(obtido["colunas"]) - set(esperado["colunas"])
    if not sobram_gab or not sobram_obt:
        return {}

    def por_alvo(fks: dict, candidatas: set, traduzir: bool) -> dict[str, list[str]]:
        agrupado: dict[str, list[str]] = {}
        for coluna, alvo in fks.items():
            if coluna in candidatas:
                chave = traduz_tabela.get(alvo, alvo) if traduzir else alvo
                agrupado.setdefault(chave, []).append(coluna)
        return agrupado

    esperadas = por_alvo(esperado["fks"], sobram_gab, traduzir=False)
    obtidas_por_alvo = por_alvo(obtido["fks"], sobram_obt, traduzir=True)

    traduz: dict[str, str] = {}
    for alvo, colunas_gab in esperadas.items():
        colunas_obt = obtidas_por_alvo.get(alvo, [])
        # Ordem estável só para o pareamento ser determinístico; qual é qual não
        # muda a contagem, porque as duas são FK para o mesmo alvo.
        for coluna_gab, coluna_obt in zip(sorted(colunas_gab), sorted(colunas_obt)):
            traduz[coluna_obt] = coluna_gab
    return traduz


def avaliar(gabarito: dict, obtidas: dict, fks_avaliaveis: bool = True) -> dict:
    """`fks_avaliaveis=False` tira a dimensão de FK da conta, sem contar acerto
    nem erro.

    Existe por causa do grocy: ele não declara nenhuma constraint FOREIGN KEY (no
    SQLite a checagem vem desligada por padrão) e implementa integridade
    referencial em TRIGGER. O gabarito então tem 60 colunas `_id` e zero FKs — e
    sem esta saída a ferramenta acharia as 60 por convenção de nome, cada uma
    contaria como falso positivo, e a métrica mediria o **oposto** do que
    aconteceu.

    Inferir as FKs eu mesmo, pelo nome, seria pior: é a própria heurística da
    ferramenta, e eu estaria comparando ela com a minha versão dela.
    """
    pares, divergencias = casar_tabelas(gabarito, obtidas)

    tabelas = Contagem()
    tabelas.acertos = len(pares)
    faltando = sorted(set(gabarito) - set(pares))
    a_mais = sorted(set(obtidas) - set(pares.values()))
    tabelas.faltando = len(faltando)
    tabelas.a_mais = len(a_mais)
    tabelas.exemplos_faltando = faltando
    tabelas.exemplos_a_mais = a_mais

    colunas, fks = Contagem(), Contagem()
    tipos_certos = tipos_total = 0

    # Coluna e FK de tabela NÃO encontrada também estão faltando. Sem isto, um
    # projeto onde nada casou reportava "colunas 100%" — os contadores ficavam
    # vazios e `Contagem` devolve 1.0 para o caso vazio. Era 100% vacuo, e
    # justamente no cenário mais crítico (linguagem sem parser, zero tabelas).
    for nome_gab in set(gabarito) - set(pares):
        perdida = gabarito[nome_gab]
        colunas.somar(set(perdida["colunas"]), set(), prefixo=f"{nome_gab}.")
        fks.somar({f"{c}->{t}" for c, t in perdida["fks"].items()}, set(), prefixo=f"{nome_gab}.")

    traduz = {v: k for k, v in pares.items()}
    divergencias_de_coluna: list[tuple[str, str, str]] = []

    for nome_gab, nome_obt in sorted(pares.items()):
        esperado = gabarito[nome_gab]
        obtido = obtidas[nome_obt]

        # FK com nome divergente dos dois lados apontando para a mesma tabela é a
        # mesma FK — traduzir antes de comparar evita contar a divergência quatro
        # vezes (colunas e FKs, faltando e sobrando).
        renomear = casar_colunas(esperado, obtido, traduz)
        divergencias_de_coluna.extend(
            (nome_obt, obt, gab) for obt, gab in sorted(renomear.items())
        )
        colunas_obtidas = {renomear.get(c, c) for c in obtido["colunas"]}
        colunas.somar(set(esperado["colunas"]), colunas_obtidas, prefixo=f"{nome_obt}.")

        # O alvo da FK também é traduzido: senão uma FK certa apontando para uma
        # tabela de nome divergente contaria como erro duas vezes.
        esperadas_fk = {f"{c}->{t}" for c, t in esperado["fks"].items()}
        obtidas_fk = {
            f"{renomear.get(c, c)}->{traduz.get(t, t)}" for c, t in obtido["fks"].items()
        }
        fks.somar(esperadas_fk, obtidas_fk, prefixo=f"{nome_obt}.")

        tipos_obtidos = {renomear.get(c, c): t for c, t in obtido["colunas"].items()}
        for coluna, tipo_esperado in esperado["colunas"].items():
            tipo_obtido = tipos_obtidos.get(coluna)
            if tipo_obtido is None:
                continue
            tipos_total += 1
            tipos_certos += familia(tipo_obtido) == familia(tipo_esperado)

    if not fks_avaliaveis:
        # Zerado, não vazio: `Contagem` devolve 1.0 para o caso vazio, e um 100%
        # vácuo aqui seria pior que não reportar.
        fks = Contagem()

    return {
        "tabelas": tabelas,
        "colunas": colunas,
        "fks": fks,
        "fks_avaliaveis": fks_avaliaveis,
        "divergencias_de_nome": divergencias,
        "divergencias_de_coluna": divergencias_de_coluna,
        "tipos_certos": tipos_certos,
        "tipos_total": tipos_total,
    }


def extrair(
    pasta: Path,
    com_llm: bool,
    sem_reconcile: bool = False,
    esconder: list[str] | None = None,
) -> dict:
    """`esconder` remove do scan os caminhos que contêm o schema já pronto.

    Serve para medir o quadrante que faltava: projeto **sem** schema declarado.
    Esconder em vez de apagar mantém o gabarito válido — ele foi derivado desses
    arquivos antes, então segue sendo verdade autoritativa enquanto a ferramenta
    deixa de ter acesso a ela. Uma variável de cada vez.
    """
    from app.pipeline.steps import build_structural, parse, scan

    arquivos = scan(pasta)
    if esconder:
        antes = len(arquivos)
        arquivos = [f for f in arquivos if not any(p in f.relative_path for p in esconder)]
        print(f"    [sem-schema] {antes - len(arquivos)} arquivo(s) escondido(s): {', '.join(esconder)}")
    modelo = build_structural(parse(arquivos, pasta), pasta)
    alternativa = None
    if com_llm:
        ctx = _passar_pelo_llm(pasta, modelo, sem_reconcile)
        modelo = ctx.conceptual
        alternativa = _consolidar_por_maioria(ctx)
    resultado = _como_dicionario(modelo)
    return (resultado, _como_dicionario(alternativa)) if alternativa is not None else resultado


def _como_dicionario(modelo) -> dict:
    return {
        t.name: {
            "colunas": {c.name: c.data_type for c in t.columns},
            "fks": {c.name: c.fk_table for c in t.columns if c.fk_table},
        }
        for t in modelo.tables
    }


def _consolidar_por_maioria(ctx):
    """O MESMO conjunto de amostras, consolidado pela política alternativa.

    A política de coluna do consenso é união (`consenso.consolidar`), escolhida
    porque a precisão medida é ~100% e o erro dominante é omissão. Mas isso
    precisa ser **verificado**, não assumido — e a verificação sai de graça: as
    amostras são as mesmas, só a consolidação muda. Zero chamadas a mais.
    """
    from importlib import import_module

    consenso = import_module("app.pipeline.steps.4_modeling.consenso")
    agent = import_module("app.pipeline.steps.4_modeling.agent")
    if len(ctx.amostras_de_modelagem) < 2:
        return None
    conceitual = consenso.consolidar(ctx.amostras_de_modelagem, uniao_de_colunas=False)
    agent.reconcile(ctx.structural, conceitual)
    return conceitual


def _passar_pelo_llm(pasta: Path, structural, sem_reconcile: bool = False):
    """Roda a Fase 4 sobre o modelo estrutural.

    `sem_reconcile` desliga a Fase 4.5 para medir a saída crua do LLM. Sem essa
    separação, "igual ao determinístico" é ambíguo: pode ser que o LLM não tenha
    mudado nada, ou que tenha mudado e a reconciliação tenha desfeito. As duas
    leituras levam a decisões opostas sobre manter ou não a etapa.
    """
    from importlib import import_module

    from app.pipeline.steps import model as modelar
    from app.pipeline.types import AnalysisContext

    agent = import_module("app.pipeline.steps.4_modeling.agent")
    original = agent.reconcile
    if sem_reconcile:
        agent.reconcile = lambda estrutural, conceitual: []
    try:
        ctx = AnalysisContext(run_id=0, project_id=0, project_name=pasta.name, root_path=pasta)
        ctx.structural = structural
        asyncio.run(modelar(ctx))
    finally:
        agent.reconcile = original
    for uso in ctx.usages:
        print(f"    [{uso.step}] {uso.model}: {uso.input_tokens} in / {uso.output_tokens} out")
    return ctx


def _mediana(rodadas: list[dict]) -> dict:
    """A rodada mediana pelo F1 de tabelas — representa o caso típico.

    Escolher a rodada mediana em vez de calcular a média campo a campo mantém o
    detalhamento (`--detalhes`) coerente: as listas de faltando/sobrando
    continuam sendo de uma execução real, e não uma colagem impossível de várias.
    A média propriamente dita sai em `_imprimir_dispersao`.
    """
    if len(rodadas) == 1:
        return rodadas[0]
    return sorted(rodadas, key=lambda r: r["tabelas"].f1)[len(rodadas) // 2]


def _imprimir_dispersao(rodadas: list[dict]) -> None:
    """Media, minimo e maximo por metrica entre repeticoes.

    Um numero solto de uma rodada so nao e resultado: a variacao do LLM entre
    execucoes ja teve a mesma magnitude do efeito que se tentava medir, e uma
    conclusao foi tirada errada por causa disso.
    """
    print(f"  {len(rodadas)} repeticoes:")
    for chave in ("tabelas", "colunas", "fks"):
        if chave == "fks" and not rodadas[0].get("fks_avaliaveis", True):
            continue
        valores = [r[chave].f1 for r in rodadas]
        media = sum(valores) / len(valores)
        marca = "  <- varia" if max(valores) - min(valores) > 0.001 else ""
        print(
            f"    {chave:<9} F1 media {media:5.1%}  min {min(valores):5.1%}  "
            f"max {max(valores):5.1%}{marca}"
        )
    tipos = [r["tipos_certos"] / r["tipos_total"] for r in rodadas if r["tipos_total"]]
    if tipos:
        media = sum(tipos) / len(tipos)
        print(f"    {'tipos':<9}    media {media:5.1%}  min {min(tipos):5.1%}  max {max(tipos):5.1%}")


def _linha(rotulo: str, c: Contagem) -> str:
    return (
        f"  {rotulo:<9} P {c.precisao:5.1%}  R {c.revocacao:5.1%}  F1 {c.f1:5.1%}"
        f"   (+{c.a_mais} a mais, -{c.faltando} faltando)"
    )


# As configurações que valem a pena medir com LLM. Os 4 projetos autorais ficam
# de fora: dão 100% estável no determinístico, e gastariam cota confirmando o que
# já se sabe.
#
# São 8 × 3 = 24 chamadas contra RPD 20 no tier gratuito: **não cabe num dia**.
# Por isso existe `--somente`, e por isso a ordem abaixo é a ordem de prioridade,
# não a alfabética — quem vem primeiro é quem tem número pendente ou inexistente.
#
# O eixo que estas configurações medem não é "tem schema ou não": é *o que resta
# quando a declaração some*, que varia por idioma de ORM e não por linguagem.
# Esconder as migrations do Rails deixa `article.rb`, que não declara coluna
# nenhuma; esconder as do Django deixaria `models.py`, que declara coluna E tipo.
# Por isso o `arquivos_de_schema` do django inclui `models.py` e o do petclinic
# inclui as classes `@Entity`: sem isso as duas células não seriam comparáveis
# com a do rails, e a matriz estaria somando coisas diferentes.
_CONFIGURACOES_OFICIAIS = [
    # Célula com defeito conhecido: as fixtures voltaram ao scan (test de dado
    # vs. código, em `1_scan/ignore.py`) e o número da seção 4 é anterior a isso.
    ("rails-realworld-example-app", True),
    # Novas: "sem declaração" numa linguagem que TEM parser dedicado. É a célula
    # que faltava para separar o efeito do parser do efeito da declaração.
    ("django-realworld-example-app", True),
    ("spring-petclinic", True),
    # Entrada mudou (fixtures no rails; `exceptions.py` fora no django), então o
    # número anterior passou a ser de outra entrada.
    ("rails-realworld-example-app", False),
    ("django-realworld-example-app", False),
    # Entrada inalterada — o determinístico destas três não mexeu. Só remedir se
    # sobrar cota; senão o número da seção 4 continua válido, e é honesto dizer
    # de que rodada ele veio.
    ("laravel-realworld-example-app", True),
    ("laravel-realworld-example-app", False),
    ("aspnetcore-realworld-example-app", False),
    # Go: preenche a célula que faltava — sem parser dedicado E com a declaração
    # na classe. É o único projeto do corpus sem arquivo de schema de verdade;
    # nos outros o cenário "sem schema" é simulado escondendo arquivos.
    ("golang-gin-realworld-example-app", False),
    ("golang-gin-realworld-example-app", True),
    # BRAÇO DE GENERALIZAÇÃO. Não entra na matriz da seção 4 e nunca é somado a
    # ela: é o único externo fora do domínio Conduit além do petclinic, e existe
    # para responder se o método funciona em código que não foi desenhado em
    # torno dele. Mesma linguagem do laravel de propósito — com a linguagem fixa,
    # a única variável entre os dois é o domínio.
    ("grocy", False),
    ("grocy", True),
]


def _rotulo_de(projeto: str, sem_schema: bool) -> str:
    return projeto + (" (sem schema)" if sem_schema else "")


def _carimbo_da_configuracao(args, repeticoes: int) -> str:
    """A configuração que produziu a tabela, para viajar COLADA nela.

    Existe por causa de um erro real e caro: a ablação da Fase 4.5 rodou com 1
    amostra e foi comparada com a medição final, que rodou com 3. As duas tabelas
    saíram visualmente idênticas — nada nelas dizia qual era qual — e a diferença,
    que tinha duas variáveis dentro, foi reportada como se fosse o efeito de uma.

    O cabeçalho de console não bastava: a tabela em Markdown é recortada e colada
    no documento **sozinha**. Por isso o carimbo vai no corpo do que se cola, e lê
    de `settings`, não do ambiente presumido — quem monta o comando erra a variável
    justamente quando está com pressa.
    """
    from datetime import date

    consenso = import_module("app.pipeline.steps.4_modeling.consenso")
    politica = "união" if _POLITICA_PADRAO_E_UNIAO(consenso) else "maioria"
    return (
        f"*Medido em {date.today():%d/%m/%Y} · `{settings.LLM_MODEL}` · "
        f"AMOSTRAS_MODELAGEM={settings.AMOSTRAS_MODELAGEM} · "
        f"{repeticoes} repetições · "
        f"reconciliação {'DESLIGADA' if args.sem_reconcile else 'ligada'} · "
        f"colunas por {politica}.*"
    )


def _POLITICA_PADRAO_E_UNIAO(consenso) -> bool:
    """Lê o padrão real de `consolidar` em vez de repetir a constante aqui."""
    import inspect

    return inspect.signature(consenso.consolidar).parameters["uniao_de_colunas"].default


def _medicao_oficial(args) -> int:
    """Roda a campanha de medição completa e imprime a tabela pronta em Markdown.

    A tabela sai com o carimbo da configuração que a produziu, para que o número
    não seja lido fora do contexto em que foi medido.
    """
    repeticoes = max(3, args.repeticoes)
    configuracoes = _CONFIGURACOES_OFICIAIS
    if args.somente:
        filtros = [f.strip().lower() for f in args.somente.split(",") if f.strip()]
        configuracoes = [
            (p, s) for p, s in configuracoes
            if any(f in _rotulo_de(p, s).lower() for f in filtros)
        ]
        if not configuracoes:
            print(f"Nenhuma configuração casa com '{args.somente}'. Disponíveis:")
            for p, s in _CONFIGURACOES_OFICIAIS:
                print(f"  {_rotulo_de(p, s)}")
            return 1

    carimbo = _carimbo_da_configuracao(args, repeticoes)
    chamadas = len(configuracoes) * repeticoes * max(1, settings.AMOSTRAS_MODELAGEM)
    if args.sem_reconcile:
        print("ABLAÇÃO: Fase 4.5 (reconciliação) DESLIGADA — comparar com a medição normal")
    print(f"Medição oficial: {len(configuracoes)} configurações × {repeticoes} repetições")
    print(f"= {chamadas} chamadas de LLM ({settings.AMOSTRAS_MODELAGEM} amostra(s) por rodada).")
    print(carimbo.strip("*"))
    print()

    linhas = ["| configuração | tabelas | colunas | FKs | tipos |", "|---|---|---|---|---|"]
    comparacao: list[tuple[str, dict, dict]] = []
    for projeto, sem_schema in configuracoes:
        arquivo = GABARITOS / f"{projeto}.json"
        gabarito = json.loads(arquivo.read_text(encoding="utf-8"))
        pasta = pasta_do_projeto(gabarito)
        esconder = gabarito.get("arquivos_de_schema") if sem_schema else None
        if sem_schema and not esconder:
            print(f"=== {_rotulo_de(projeto, sem_schema)}: sem `arquivos_de_schema` no gabarito, pulando ===")
            continue
        rotulo = _rotulo_de(projeto, sem_schema)
        print(f"=== {rotulo} ===")

        rodadas = []
        rodadas_maioria = []
        for i in range(repeticoes):
            try:
                obtidas = extrair(
                    pasta, com_llm=True, sem_reconcile=args.sem_reconcile, esconder=esconder
                )
                avaliaveis = gabarito.get("fks_avaliaveis", True)
                if isinstance(obtidas, tuple):
                    uniao, maioria = obtidas
                    rodadas.append(avaliar(gabarito["tabelas"], uniao, avaliaveis))
                    rodadas_maioria.append(avaliar(gabarito["tabelas"], maioria, avaliaveis))
                else:
                    rodadas.append(avaliar(gabarito["tabelas"], obtidas, avaliaveis))
            except Exception as exc:  # noqa: BLE001 - uma falha de provedor não pode perder as demais
                print(f"    rodada {i + 1} falhou: {type(exc).__name__}: {exc}")  # o tipo junto: httpx.ReadTimeout tem str() vazio
        if not rodadas:
            linhas.append(f"| {rotulo} | — | — | — | — |")
            continue
        _imprimir_dispersao(rodadas)

        def faixa(chave: str) -> str:
            valores = [r[chave].f1 for r in rodadas]
            media = sum(valores) / len(valores)
            if max(valores) - min(valores) < 0.001:
                return f"{media:.1%}"
            return f"{media:.1%} ({min(valores):.1%}–{max(valores):.1%})"

        tipos = [r["tipos_certos"] / r["tipos_total"] for r in rodadas if r["tipos_total"]]
        media_tipos = f"{sum(tipos) / len(tipos):.1%}" if tipos else "—"
        if rodadas_maioria:
            def media(rs, campo):
                return sum(getattr(r["colunas"], campo) for r in rs) / len(rs)

            comparacao.append((
                rotulo,
                {"f1": media(rodadas, "f1"), "precisao": media(rodadas, "precisao")},
                {"f1": media(rodadas_maioria, "f1"), "precisao": media(rodadas_maioria, "precisao")},
            ))

        coluna_fk = faixa("fks") if rodadas[0].get("fks_avaliaveis", True) else "n/a"
        linhas.append(
            f"| {rotulo} | {faixa('tabelas')} | {faixa('colunas')} | {coluna_fk} | {media_tipos} |"
        )

    if comparacao:
        print()
        print("--- união × maioria na votação de colunas (mesmas amostras, 0 chamadas a mais) ---")
        print()
        print("| configuração | colunas (união) | colunas (maioria) | precisão união | precisão maioria |")
        print("|---|---|---|---|---|")
        for rotulo, u, m in comparacao:
            print(
                f"| {rotulo} | {u['f1']:.1%} | {m['f1']:.1%} | "
                f"{u['precisao']:.1%} | {m['precisao']:.1%} |"
            )

    print()
    print("--- tabela em Markdown ---")
    print()
    for linha in linhas:
        print(linha)
    # O carimbo vai COLADO na tabela, não no cabeçalho: é a tabela que é recortada
    # e levada para o documento, e foi por essa fresta que duas configurações
    # diferentes viraram uma comparação inválida.
    print()
    print(carimbo)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Avalia a extração contra os gabaritos")
    parser.add_argument("--projeto", help="avalia só este projeto")
    parser.add_argument("--com-llm", action="store_true", help="inclui a Fase 4 (gasta cota)")
    parser.add_argument("--detalhes", action="store_true", help="lista o que sobrou e o que faltou")
    parser.add_argument(
        "--oficial",
        action="store_true",
        help="medição oficial: as 6 configurações informativas com --com-llm e 3 repetições",
    )
    parser.add_argument(
        "--somente",
        help="com --oficial, roda só as configurações cujo rótulo casa (lista separada por vírgula)",
    )
    parser.add_argument(
        "--incluir-escala",
        action="store_true",
        help="inclui projetos marcados `escopo: escala` no agregado",
    )
    parser.add_argument(
        "--sem-schema",
        action="store_true",
        help="esconde do scan os `arquivos_de_schema` declarados no gabarito",
    )
    parser.add_argument(
        "--repeticoes",
        type=int,
        default=1,
        help="com --com-llm, repete N vezes e reporta media/minimo/maximo",
    )
    parser.add_argument(
        "--sem-reconcile",
        action="store_true",
        help="com --com-llm, mede a saida crua do LLM sem a Fase 4.5",
    )
    args = parser.parse_args()

    if args.oficial:
        return _medicao_oficial(args)

    arquivos = sorted(GABARITOS.glob("*.json"))
    if not args.projeto and not args.incluir_escala:
        # Projeto marcado `escopo: escala` mede até onde a ferramenta processa,
        # não o quanto ela acerta. No mastodon são 541 tabelas detectadas contra
        # 116 reais — entrar no agregado envenenaria a média de acurácia.
        antes = len(arquivos)
        arquivos = [
            a for a in arquivos
            if json.loads(a.read_text(encoding="utf-8")).get("escopo") != "escala"
        ]
        if antes != len(arquivos):
            print(f"({antes - len(arquivos)} projeto(s) de escala fora do agregado; use --incluir-escala)")
    if args.projeto:
        arquivos = [a for a in arquivos if a.stem == args.projeto]
        if not arquivos:
            print(f"Nenhum gabarito para '{args.projeto}'")
            return 1

    totais = {"tabelas": Contagem(), "colunas": Contagem(), "fks": Contagem()}
    projetos_medidos = 0
    tipos_certos = tipos_total = 0

    for arquivo in arquivos:
        gabarito = json.loads(arquivo.read_text(encoding="utf-8"))
        pasta = pasta_do_projeto(gabarito)
        marca = " [externo]" if gabarito.get("externo") else ""
        print(f"\n=== {gabarito['projeto']}{marca} ({gabarito['confianca']}) ===")
        rodadas = []
        for _ in range(max(1, args.repeticoes)):
            esconder = gabarito.get("arquivos_de_schema") if args.sem_schema else None
            try:
                obtidas = extrair(pasta, args.com_llm, args.sem_reconcile, esconder)
            except Exception as exc:  # noqa: BLE001
                # Mesma resiliência do `--oficial`: uma falha de provedor não pode
                # jogar fora as repetições que já completaram. Eram duas rotas para
                # a mesma medição com robustez diferente.
                print(f"  rodada falhou: {type(exc).__name__}: {exc}")
                continue
            if isinstance(obtidas, tuple):
                obtidas = obtidas[0]
            rodadas.append(
                avaliar(gabarito["tabelas"], obtidas, gabarito.get("fks_avaliaveis", True))
            )
        # A MÉDIA é o número reportado, não a primeira rodada. A variação entre
        # execuções (laravel: 78,7% a 100% em colunas) é maior que qualquer ganho
        # perseguível, então uma amostra só não é resultado — e reportar uma
        # amostra como resultado já produziu conclusão errada duas vezes aqui.
        if not rodadas:
            print("  nenhuma rodada completou")
            continue
        projetos_medidos += 1
        r = _mediana(rodadas)
        if len(rodadas) > 1:
            _imprimir_dispersao(rodadas)

        for chave in totais:
            if chave == "fks" and not r.get("fks_avaliaveis", True):
                print(f"  {'fks':<9} — não avaliável neste projeto (ver o gabarito)")
                continue
            alvo, parcial = totais[chave], r[chave]
            alvo.acertos += parcial.acertos
            alvo.a_mais += parcial.a_mais
            alvo.faltando += parcial.faltando
            print(_linha(chave, parcial))
        tipos_certos += r["tipos_certos"]
        tipos_total += r["tipos_total"]
        if r["tipos_total"]:
            print(f"  {'tipos':<9} {r['tipos_certos'] / r['tipos_total']:5.1%} por família de tipo")
        for esperado, obtido in r["divergencias_de_nome"]:
            print(f"  nome        '{obtido}' deveria ser '{esperado}'")
        # Divergência de nome de coluna não é perdoada em silêncio: ela deixa de
        # contar como erro de extração, mas aparece aqui como o que é.
        for tabela, obtido, esperado in r["divergencias_de_coluna"]:
            print(f"  nome        {tabela}.'{obtido}' deveria ser '{esperado}' (mesma FK)")
        if args.detalhes:
            for chave in ("tabelas", "colunas", "fks"):
                c = r[chave]
                if c.exemplos_faltando:
                    print(f"    faltando ({chave}): {', '.join(c.exemplos_faltando[:12])}")
                if c.exemplos_a_mais:
                    print(f"    a mais   ({chave}): {', '.join(c.exemplos_a_mais[:12])}")

    # `Contagem` devolve 1.0 para o caso vazio, então um agregado que não
    # recebeu nada reporta 100%. O projeto já tinha corrigido isso por projeto
    # ("coluna de tabela não encontrada conta como faltando") e a resiliência
    # acrescentada ao `--projeto` reintroduziu no TOTAL: com todas as rodadas
    # falhando, a saída era `tabelas 100%` e código de saída 0. Silêncio que
    # parece sucesso é pior que erro.
    if not projetos_medidos:
        print("\n=== TOTAL ===")
        print("  nenhum projeto foi medido — não há total a reportar")
        return 1

    print("\n=== TOTAL ===")
    for chave, c in totais.items():
        print(_linha(chave, c))
    if tipos_total:
        print(f"  {'tipos':<9} {tipos_certos / tipos_total:5.1%} por família de tipo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
