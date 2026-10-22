from pathlib import Path

from app.helpers.language_detect import detect_language
from app.helpers.storage import looks_binary
from app.pipeline.types import FileSummary

from .ignore import should_ignore

BINARY_SAMPLE_SIZE = 8 * 1024


def scan(folder: Path, max_file_size: int = 5 * 1024 * 1024) -> list[FileSummary]:
    files: list[FileSummary] = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        # `as_posix()` e nao `str()`: no Windows o separador sai como `\`, e o
        # resto do pipeline trata o caminho como texto com `/` (nome de tabela
        # a partir do arquivo, resolucao de import, chave de evidencia). Sem
        # normalizar aqui, `data/categoria.json` virava a tabela
        # `data_categorias` no Windows e `categorias` no container Linux.
        rel = path.relative_to(folder).as_posix()
        if should_ignore(Path(rel)):
            continue
        size = path.stat().st_size
        if size > max_file_size:
            files.append(FileSummary(relative_path=rel, size_bytes=size, status="excluded", reason="Arquivo excede o limite de 5MB"))
            continue
        try:
            with path.open("rb") as fh:
                sample = fh.read(BINARY_SAMPLE_SIZE)
        except OSError:
            files.append(FileSummary(relative_path=rel, size_bytes=size, status="excluded", reason="Não foi possível ler o arquivo"))
            continue
        if looks_binary(sample):
            files.append(FileSummary(relative_path=rel, size_bytes=size, status="excluded", reason="Arquivo binário ou ilegível"))
            continue
        files.append(
            FileSummary(
                relative_path=rel,
                language=detect_language(rel) or "unknown",
                size_bytes=size,
                status="ok",
            )
        )
    return files
