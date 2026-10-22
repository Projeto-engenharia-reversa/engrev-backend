"""Utilitários pequenos compartilhados por todos os parsers de tabela/entidade
(SQL, formatos de schema da Camada 2, extração AST da Camada 3)."""

from __future__ import annotations

from .parsed_types import ParsedColumn


def ensure_primary_key(columns: list[ParsedColumn]) -> None:
    """Garante que a lista de colunas tenha uma PK: promove uma coluna `id`
    existente, ou insere uma sintética no início. Esse idioma se repetia em cada
    parser de tabela/entidade -- centralizado aqui pra não duplicar por formato."""
    if any(c.primary_key for c in columns):
        return
    existing = next((c for c in columns if c.name == "id"), None)
    if existing is not None:
        existing.primary_key = True
        existing.nullable = False
    else:
        columns.insert(0, ParsedColumn(name="id", data_type="integer", nullable=False, primary_key=True))
