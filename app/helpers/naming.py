import re
from functools import lru_cache


@lru_cache
def to_snake(value: str) -> str:
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
    s2 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1)
    s = re.sub(r"[^A-Za-z0-9]+", "_", s2).lower()
    return s.strip("_")


def _plural_en(snake: str) -> str:
    if snake.endswith("y") and not snake.endswith(("ay", "ey", "oy", "uy")):
        return snake[:-1] + "ies"
    if snake.endswith(("s", "x", "z", "ch", "sh")):
        return snake + "es"
    return snake + "s"


def _plural_pt(snake: str) -> str:
    """Plural português sobre identificador já normalizado (sem acento).

    Os identificadores chegam em ASCII (`Recomendacao`, não `Recomendação`),
    porque é assim que se escreve nome de classe em Java/C#/Prisma.
    """
    if snake.endswith("ao"):  # recomendacao -> recomendacoes
        return snake[:-2] + "oes"
    if snake.endswith("m"):  # album -> albuns
        return snake[:-1] + "ns"
    if snake.endswith("il"):  # funil -> funis
        return snake[:-2] + "is"
    if snake.endswith("l"):  # editorial -> editoriais
        return snake[:-1] + "is"
    if snake.endswith(("r", "s", "z")):  # autor -> autores
        return snake + "es"
    return snake + "s"


# TENTADO E REVERTIDO: flexionar as duas partes do composto
# (`campanha_editorial` -> `campanhas_editoriais`) parece a regra da língua, mas
# medido no projeto 4 sob `pt` **piorou** — consertou `campanhas_editoriais` e
# quebrou `item_playlists` -> `itens_playlists` e `perfil_gostos` ->
# `perfis_gostos`. Composto português concorda quando o segundo termo é adjetivo
# e não concorda quando é substantivo qualificador, e distinguir os dois exige
# saber a classe gramatical da palavra. Uma divergência virou duas.
#
# Fica só o núcleo no plural, e a divergência de nome composto é limite declarado
# — o avaliador já a reporta como métrica separada da extração.
_REGRAS_DE_PLURAL = {"en": _plural_en, "pt": _plural_pt, "none": lambda snake: snake}


def to_plural(snake: str) -> str:
    """Pluraliza conforme `settings.NAMING_PLURAL`.

    Não se tenta detectar o idioma: as terminações ambíguas são as mesmas
    palavras nos dois (`album`, `editorial`, `item`, `total`), com plurais
    diferentes, e projeto brasileiro real mistura domínio em português com
    framework em inglês. Diante de ambiguidade que não se resolve por análise,
    a escolha fica com quem conhece o código.
    """
    from app.core.config import settings  # tardio: evita ciclo e permite trocar em teste

    regra = _REGRAS_DE_PLURAL.get(settings.NAMING_PLURAL, _plural_en)
    return regra(snake)


def table_name_for(entity_name: str) -> str:
    return to_plural(to_snake(entity_name))


def column_name_for(field_name: str) -> str:
    return to_snake(field_name)


def fk_name_for(entity_name: str) -> str:
    return f"{to_snake(entity_name)}_id"


def constraint_name(prefix: str, *parts: str) -> str:
    joined = "_".join(p for p in parts if p)
    return f"{prefix}_{joined}"[:63]
