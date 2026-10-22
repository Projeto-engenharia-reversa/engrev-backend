"""Detecção de linguagem/formato por extensão de arquivo.

Módulo neutro (sem dependência de `app.pipeline`) para que tanto a etapa
`1_scan` quanto a etapa `3_structural` possam reaproveitar a mesma tabela de
extensões sem import circular.
"""

from pathlib import Path

_EXTENSION_LANGUAGE = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "jsx",
    ".sql": "sql",
    ".ddl": "sql",
    ".json": "json",
    ".prisma": "prisma",
    ".proto": "protobuf",
    ".graphql": "graphql",
    ".gql": "graphql",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".xml": "xml",
    ".java": "java",
    ".cs": "csharp",
    ".html": "html",
    ".htm": "html",
    ".md": "markdown",
    ".markdown": "markdown",
}


def detect_language(path: str) -> str | None:
    """Retorna o identificador de linguagem/formato pela extensão do arquivo, ou None se não reconhecida."""
    ext = Path(path).suffix.lower()
    return _EXTENSION_LANGUAGE.get(ext)
