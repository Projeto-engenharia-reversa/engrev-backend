"""Extração de seções de Markdown por heading, via `tree-sitter-markdown` (sem
regex). Alimenta o canal de documentação em linguagem natural (Fase 4.2):
`builder.py` chama `extract_sections` + `filter_relevant_sections` diretamente para
arquivos `.md`/`.markdown` (fora do fluxo normal de `parse_file`, já que Markdown
nunca produz `TableDef` -- só `DocEvidence`, evidência corroborativa)."""

from __future__ import annotations

from dataclasses import dataclass

import tree_sitter_markdown
from tree_sitter import Language, Node, Parser

_MARKDOWN_LANGUAGE = Language(tree_sitter_markdown.language())

# Headings cujo texto sugere que a seção fala do modelo de dados/domínio —
# comparação de substring simples (lowercase), não regex. Deliberadamente
# conservador: melhor perder uma seção relevante com título atípico do que
# inundar o prompt com todo o conteúdo de todo .md do projeto.
_RELEVANT_HEADING_KEYWORDS = (
    "modelo de dados",
    "data model",
    "database",
    "domain model",
    "schema",
    "entidades",
    "entities",
    "banco de dados",
    "estrutura de dados",
    "domínio",
)


@dataclass
class MarkdownSection:
    heading: str
    level: int
    text: str
    line_start: int
    line_end: int


def extract_sections(text: str) -> list[MarkdownSection]:
    """Retorna uma seção por heading de nível 1-6, com o texto completo daquele
    heading até o próximo heading de nível igual ou maior (a própria estrutura
    `section` do tree-sitter-markdown já faz esse agrupamento por aninhamento)."""
    parser = Parser(_MARKDOWN_LANGUAGE)
    tree = parser.parse(text.encode("utf-8"))
    sections: list[MarkdownSection] = []
    _collect_sections(tree.root_node, sections)
    return sections


def filter_relevant_sections(sections: list[MarkdownSection]) -> list[MarkdownSection]:
    """Mantém só seções cujo heading parece falar do modelo de dados/domínio."""
    return [s for s in sections if _is_relevant_heading(s.heading)]


def _is_relevant_heading(heading: str) -> bool:
    lowered = heading.lower()
    return any(keyword in lowered for keyword in _RELEVANT_HEADING_KEYWORDS)


def _collect_sections(node: Node, sections: list[MarkdownSection]) -> None:
    for child in node.children:
        if child.type == "section":
            # Texto e pontos lidos antes de descer nos filhos: nesta versão do
            # py-tree-sitter percorrer `child.children` invalida `child`, e ler
            # depois é acesso a memória liberada.
            texto = child.text.decode(errors="replace")
            linha_inicial = child.start_point.row + 1
            linha_final = child.end_point.row + 1
            heading_node = next((c for c in child.children if c.type.startswith("atx_heading") or c.type == "setext_heading"), None)
            if heading_node is not None:
                heading_text, level = _heading_text_and_level(heading_node)
                sections.append(
                    MarkdownSection(
                        heading=heading_text,
                        level=level,
                        text=texto,
                        line_start=linha_inicial,
                        line_end=linha_final,
                    )
                )
            _collect_sections(child, sections)  # seções aninhadas (headings de nível maior)
        else:
            _collect_sections(child, sections)


def _heading_text_and_level(heading_node: Node) -> tuple[str, int]:
    level = 1
    for marker_type, marker_level in (
        ("atx_h1_marker", 1),
        ("atx_h2_marker", 2),
        ("atx_h3_marker", 3),
        ("atx_h4_marker", 4),
        ("atx_h5_marker", 5),
        ("atx_h6_marker", 6),
    ):
        if any(c.type == marker_type for c in heading_node.children):
            level = marker_level
            break
    inline = next((c for c in heading_node.children if c.type == "inline"), None)
    heading_text = inline.text.decode(errors="replace").strip() if inline is not None else ""
    return heading_text, level
