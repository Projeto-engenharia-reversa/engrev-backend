import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.pipeline.steps import build_context, build_structural, parse, scan


def analyze(folder: Path) -> None:
    files = scan(folder)
    print(f"{len(files)} arquivos encontrados")
    summaries = parse(files, folder)
    model = build_structural(summaries, folder)
    context, omitted = build_context(folder.name, model, settings.MAP_BUDGET)
    print(context)
    if omitted:
        print(f"\n[aviso] seções cortadas por orçamento: {omitted}")


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    analyze(target)
