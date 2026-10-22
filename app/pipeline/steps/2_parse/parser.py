from pathlib import Path

from app.pipeline.types import FileSummary

from .file_summary import summarize_file


def parse(files: list[FileSummary], root: Path) -> list[FileSummary]:
    summaries: list[FileSummary] = []
    for f in files:
        if f.status != "ok":
            summaries.append(f)
            continue
        path = root / f.relative_path
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            f.status = "excluded"
            f.reason = "Não foi possível ler o arquivo"
            summaries.append(f)
            continue
        imported, exported = summarize_file(text)
        f.imported_symbols = imported
        f.exported_symbols = exported
        summaries.append(f)
    return summaries
