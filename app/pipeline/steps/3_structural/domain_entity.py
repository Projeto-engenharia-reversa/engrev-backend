"""Critério compartilhado de "isto é entidade de domínio?".

O sinal muda por formato, em linguagens anotadas é a anotação e no Protobuf é o
uso em `rpc`, mas a política é a mesma e mora aqui.
"""

from __future__ import annotations

# Marcam explicitamente uma entidade persistida (JPA, Spring Data, EF Core).
ANOTACOES_DE_ENTIDADE = {"Entity", "Document", "Embeddable", "Table"}

# Classe-base cujas colunas pertencem às subclasses, não a uma tabela própria.
# Limite conhecido: excluí-la não move as colunas dela para as subclasses, o que
# exigiria resolver `extends` entre arquivos.
ANOTACOES_DE_SUPERCLASSE = {"MappedSuperclass"}

# Marcam infraestrutura da aplicação: nunca são entidade de domínio.
ANOTACOES_DE_INFRAESTRUTURA = {
    "Service",
    "Component",
    "Repository",
    "Controller",
    "RestController",
    "ControllerAdvice",
    "Configuration",
    "SpringBootApplication",
    "Aspect",
    "Interceptor",
    "Mapper",
    "Bean",
    "ApiController",
    # Envelope de serialização: existe para transportar, não para persistir.
    "XmlRootElement",
    "XmlType",
    "XmlAccessorType",
    "JsonRootName",
    "JsonNaming",
}


# Sufixos que denunciam infraestrutura pelo nome, único sinal disponível quando a
# linguagem não marca nada. É convenção de nomenclatura, não conhecimento de
# biblioteca. A comparação é por token, então `_view` casa `article_view` mas não
# `interview`, e sufixos ambíguos como `_model` e `_type` ficaram de fora porque
# `CarModel` e `ProductType` são entidades plausíveis.
SUFIXOS_DE_INFRAESTRUTURA = (
    "serializer", "deserializer", "renderer", "view", "view_set", "api_view",
    "controller", "middleware", "migration", "config", "app_config", "settings",
    "exception", "error", "envelope", "dto", "context", "options",
    "factory", "builder", "validator", "interceptor", "resolver", "mapper",
    "handler", "manager", "repository", "service", "helper", "formatter",
    "converter", "listener", "subscriber", "decorator", "wrapper", "proxy",
    "registry", "dispatcher", "router", "mixin", "meta", "test_case", "data",
    # Ficaram fora os que colidem com domínio real: `policy`, `client`, `provider`.
    "authentication", "authorization", "backend", "adapter",
    # Propriedades de componente de interface, convenção de React e TypeScript.
    "props",
    # Envelope de API, inequívoco como sufixo de token inteiro.
    "response", "request",
)


# Superclasse que marca entidade persistida, equivalente a `@Entity` em
# linguagens que não anotam: `class User(Base)` diz a mesma coisa.
BASES_DE_ENTIDADE = {
    "Base", "DeclarativeBase", "Model", "SQLModel", "Document",
    "db.Model", "models.Model",  # Flask-SQLAlchemy e Django
}

# O oposto: a classe existe para transportar ou tipar, nunca para persistir.
# Nenhum sufixo de nome cobriria isto, porque `Admin` e `Token` são nomes de
# entidade plausíveis. A superclasse é o sinal.
BASES_DE_NAO_ENTIDADE = {
    "BaseModel", "TypedDict", "NamedTuple", "Protocol", "ABC", "Enum",
    "IntEnum", "StrEnum", "Exception", "BaseException", "Generic",
}


def _sem_pacote(base: str) -> str:
    """`sqlalchemy.orm.DeclarativeBase` -> `DeclarativeBase`; preserva `db.Model`."""
    if base in BASES_DE_ENTIDADE or base in BASES_DE_NAO_ENTIDADE:
        return base
    return base.rsplit(".", 1)[-1] if "." in base else base


def classificar_por_base(bases: list[str]) -> str | None:
    """`"entidade"`, `"nao"` ou None quando as bases não dizem nada."""
    nomes = {_sem_pacote(b) for b in bases}
    # Não-entidade decide primeiro: uma classe de transporte que por acaso se
    # chame `Base` no projeto não deve virar tabela.
    if nomes & BASES_DE_NAO_ENTIDADE:
        return "nao"
    if nomes & BASES_DE_ENTIDADE:
        return "entidade"
    return None


def _classificar_hierarquia(bases: dict[str, list[str]]) -> dict[str, str | None]:
    """Propaga a classificação pela hierarquia declarada no arquivo.

    A classificação direta não basta quando a hierarquia vem em camadas, porque
    só a primeira casa com a base conhecida:

        class Admin(BaseModel): ...
        class AdminCreate(Admin): ...

    O escopo é o arquivo porque é onde as camadas costumam ser declaradas juntas.
    Itera até estabilizar, com teto, para que hierarquia com ciclo não trave.
    """
    resultado = {nome: classificar_por_base(lista) for nome, lista in bases.items()}
    for _ in range(len(bases) + 1):
        mudou = False
        for nome, lista in bases.items():
            if resultado.get(nome) is not None:
                continue
            for base in lista:
                herdado = resultado.get(_sem_pacote(base)) or resultado.get(base)
                if herdado is not None:
                    resultado[nome] = herdado
                    mudou = True
                    break
        if not mudou:
            break
    return resultado


def parece_infraestrutura_pelo_nome(nome: str) -> bool:
    """`ArticleSerializer` -> True; `Review` e `Interview` -> False.

    Dígito no fim é descartado antes de comparar, senão `Error400` escapa da lista.
    """
    from app.helpers.naming import to_snake

    snake = to_snake(nome).rstrip("0123456789").rstrip("_")
    return any(snake == s or snake.endswith("_" + s) for s in SUFIXOS_DE_INFRAESTRUTURA)


def modulo_e_infraestrutura(caminho: str) -> bool:
    """`exceptions.py` -> True; `models.py` e `article.py` -> False.

    Mesmo princípio dos sufixos de classe um nível acima, e sinal mais forte,
    porque nomear o módulo pelo papel técnico é decisão deliberada do autor.
    Reusa `SUFIXOS_DE_INFRAESTRUTURA` para não manter duas listas iguais.
    """
    from pathlib import Path as _Path

    caule = _Path(caminho).name.split(".")[0]
    if not caule:
        return False
    # Módulo costuma ser plural e a lista é singular; as duas formas bastam.
    formas = {caule, caule.removesuffix("es"), caule.removesuffix("s")}
    return any(parece_infraestrutura_pelo_nome(f) for f in formas if f)


def selecionar_por_anotacao(
    tipos: dict[str, set[str]],
    caminho: str | None = None,
    bases: dict[str, list[str]] | None = None,
) -> set[str]:
    """Quais tipos são de domínio, a partir das anotações de cada um.

    `tipos` mapeia nome do tipo -> conjunto de anotações (sem pacote).

    A política tem dois modos, e o segundo existe para não estreitar demais:

    - **O arquivo marca entidades**: só valem as marcadas, o resto é apoio.
    - **O arquivo não marca nada**: exclui só o que é reconhecidamente
      infraestrutura, para que um objeto de domínio em projeto sem ORM anotado
      continue virando tabela.

    Classe-base é excluída nos dois modos. `caminho` descarta o arquivo inteiro
    pelo nome do módulo, mas só no modo permissivo, porque declaração explícita
    vence convenção de nome.
    """
    # Mesmo sinal das anotações para linguagens que não anotam. Ver `classificar_por_base`.
    por_base = _classificar_hierarquia(bases or {})
    if "entidade" in por_base.values():
        # Entidade declarada por herança segue a mesma política do `@Entity`.
        return {nome for nome, classe in por_base.items() if classe == "entidade"}

    marca_entidades = any(anotacoes & ANOTACOES_DE_ENTIDADE for anotacoes in tipos.values())
    if not marca_entidades and caminho and modulo_e_infraestrutura(caminho):
        return set()
    if marca_entidades:
        candidatos = {nome for nome, anotacoes in tipos.items() if anotacoes & ANOTACOES_DE_ENTIDADE}
    else:
        # Sem nenhuma marcação no arquivo, o nome é o único sinal que sobra.
        candidatos = {
            nome
            for nome, anotacoes in tipos.items()
            if not (anotacoes & ANOTACOES_DE_INFRAESTRUTURA)
            and not parece_infraestrutura_pelo_nome(nome)
            and por_base.get(nome) != "nao"
        }
    return {nome for nome in candidatos if not (tipos[nome] & ANOTACOES_DE_SUPERCLASSE)}
