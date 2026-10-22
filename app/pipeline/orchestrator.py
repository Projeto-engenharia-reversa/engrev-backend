import asyncio
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete

from app.core.config import settings
from app.db.session import session_scope
from app.helpers.llm.tokens import estimate_cost_usd
from app.models.analysis_run import AnalysisRun
from app.models.artifact import Artifact
from app.models.conceptual_model import ConceptualModel
from app.models.run_log import RunLog
from app.models.scanned_file import ScannedFile
from app.models.structural_snapshot import StructuralSnapshot
from app.models.token_usage import TokenUsage
from app.pipeline.steps import (
    build_structural,
    generate_artifacts,
    model,
    parse,
    review,
    scan,
    validate,
)
from app.pipeline.types import AnalysisContext

PROGRESS = {
    "scan": 0.15,
    "parse": 0.35,
    "structural": 0.5,
    "modeling": 0.72,
    "validation": 0.86,
    "artifacts": 0.95,
    "done": 1.0,
}


class ProgressBus:
    def __init__(self):
        self._subscribers: dict[int, dict[asyncio.Queue, asyncio.AbstractEventLoop]] = {}

    def subscribe(self, run_id: int) -> asyncio.Queue:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.setdefault(run_id, {})[queue] = loop
        return queue

    def unsubscribe(self, run_id: int, queue: asyncio.Queue) -> None:
        subscribers = self._subscribers.get(run_id)
        if subscribers:
            subscribers.pop(queue, None)
            if not subscribers:
                self._subscribers.pop(run_id, None)

    def publish(self, run_id: int, event: dict) -> None:
        subscribers = self._subscribers.get(run_id)
        if not subscribers:
            return
        for queue, loop in list(subscribers.items()):
            loop.call_soon_threadsafe(queue.put_nowait, event)


bus = ProgressBus()


def _now() -> datetime:
    return datetime.now(UTC)


async def _simulate_step() -> None:
    if settings.SIMULATE_PROGRESS:
        await asyncio.sleep(settings.PROGRESS_STAGE_DELAY_SECONDS)


def _update_run(run_id: int, **fields) -> None:
    with session_scope() as session:
        run = session.get(AnalysisRun, run_id)
        if run is None:
            return
        for key, value in fields.items():
            setattr(run, key, value)


def _emit(run_id: int, event_type: str, **data) -> None:
    bus.publish(run_id, {"type": event_type, "run_id": run_id, **data})


def _save_scanned_files(run_id: int, summaries) -> None:
    with session_scope() as session:
        session.execute(delete(ScannedFile).where(ScannedFile.run_id == run_id))
        for summary in summaries:
            session.add(
                ScannedFile(
                    run_id=run_id,
                    path=summary.relative_path,
                    language=summary.language,
                    size_bytes=summary.size_bytes,
                    status=summary.status,
                    reason=summary.reason,
                    summary_json=summary.model_dump(),
                )
            )


def _save_structural_snapshot(ctx: AnalysisContext) -> None:
    """Fase 4.3: persiste o StructuralModel logo após a etapa `structural`, pra
    não perder o trabalho se o pipeline cair antes de terminar `modeling`. Não
    implementa retomada automática — é só sobrevivência dos dados a um crash."""
    with session_scope() as session:
        session.add(
            StructuralSnapshot(run_id=ctx.run_id, structural_json=ctx.structural.model_dump(mode="json"))
        )


def _quality_score(ctx: AnalysisContext) -> int:
    errors = sum(1 for i in ctx.conceptual.issues if i.severity == "error")
    warnings = sum(1 for i in ctx.conceptual.issues if i.severity == "warning")
    return max(0, min(100, 100 - errors * 15 - warnings * 5))


def _save_conceptual_model(ctx: AnalysisContext) -> None:
    with session_scope() as session:
        session.add(
            ConceptualModel(
                run_id=ctx.run_id,
                entities_json=[t.model_dump() for t in ctx.conceptual.tables],
                relationships_json=[r.model_dump() for r in ctx.conceptual.relationships],
                queries_json=[q.model_dump() for q in ctx.conceptual.queries],
                quality_score=_quality_score(ctx),
            )
        )


def _save_artifacts(ctx: AnalysisContext) -> None:
    with session_scope() as session:
        for filename, content in ctx.artifacts.items():
            kind = Path(filename).suffix.lstrip(".").lower()
            session.add(
                Artifact(run_id=ctx.run_id, kind=kind, filename=filename, content=content, size_bytes=len(content.encode("utf-8")))
            )


def _save_token_usage(ctx: AnalysisContext) -> None:
    """Uma linha por chamada de LLM, com a etapa e o modelo que de fato rodaram.

    Antes gravava uma linha só, com `step="modeling"` e `settings.LLM_MODEL`
    fixos, somando tudo que estivesse no contexto. Como o agente de validação
    roda no modelo leve e nem chegava a somar, o consumo dele era invisível e o
    custo do que sobrava era calculado com o preço do modelo errado.
    """
    total = 0.0
    with session_scope() as session:
        for uso in ctx.usages:
            custo = estimate_cost_usd(uso.input_tokens, uso.output_tokens, uso.model)
            total += custo
            session.add(
                TokenUsage(
                    run_id=ctx.run_id,
                    step=uso.step,
                    model=uso.model,
                    input_tokens=uso.input_tokens,
                    output_tokens=uso.output_tokens,
                    cost_usd=custo,
                )
            )
        run = session.get(AnalysisRun, ctx.run_id)
        run.total_tokens = ctx.prompt_tokens + ctx.completion_tokens
        run.total_cost_usd = total
        run.metrics_json = {
            "prompt_tokens": ctx.prompt_tokens,
            "completion_tokens": ctx.completion_tokens,
            "cost_usd": total,
            "por_etapa": [
                {
                    "step": u.step,
                    "model": u.model,
                    "input_tokens": u.input_tokens,
                    "output_tokens": u.output_tokens,
                }
                for u in ctx.usages
            ],
        }


async def run_pipeline(ctx: AnalysisContext) -> None:
    try:
        await _simulate_step()
        _update_run(ctx.run_id, status="scan", stage="scan", progress=PROGRESS["scan"], started_at=_now())
        _emit(ctx.run_id, "stage", stage="scan", progress=PROGRESS["scan"], message="Escaneando arquivos...")
        ctx.summaries = await asyncio.to_thread(scan, ctx.root_path)
        _save_scanned_files(ctx.run_id, ctx.summaries)
        _emit(ctx.run_id, "stage", stage="scan", progress=0.25, message=f"{len(ctx.summaries)} arquivos escaneados")

        await _simulate_step()
        _update_run(ctx.run_id, status="parse", stage="parse", progress=PROGRESS["parse"])
        _emit(ctx.run_id, "stage", stage="parse", progress=PROGRESS["parse"], message="Extraindo resumos...")
        ctx.summaries = await asyncio.to_thread(parse, ctx.summaries, ctx.root_path)
        _save_scanned_files(ctx.run_id, ctx.summaries)
        _emit(ctx.run_id, "stage", stage="parse", progress=0.45, message="Resumos extraídos")

        await _simulate_step()
        _update_run(ctx.run_id, status="structural", stage="structural", progress=PROGRESS["structural"])
        _emit(ctx.run_id, "stage", stage="structural", progress=PROGRESS["structural"], message="Construindo modelo estrutural...")
        ctx.structural = await asyncio.to_thread(build_structural, ctx.summaries, ctx.root_path)
        _save_structural_snapshot(ctx)
        _emit(ctx.run_id, "stage", stage="structural", progress=0.6, message=f"{len(ctx.structural.tables)} entidades candidatas")

        await _simulate_step()
        _update_run(ctx.run_id, status="modeling", stage="modeling", progress=PROGRESS["modeling"])
        _emit(ctx.run_id, "stage", stage="modeling", progress=PROGRESS["modeling"], message="Modelando com IA...")
        ctx = await model(ctx)
        _save_conceptual_model(ctx)
        _emit(ctx.run_id, "stage", stage="modeling", progress=0.8, message="Modelo conceitual gerado")

        await _simulate_step()
        _update_run(ctx.run_id, status="validation", stage="validation", progress=PROGRESS["validation"])
        _emit(ctx.run_id, "stage", stage="validation", progress=PROGRESS["validation"], message="Validando modelo...")
        issues = await asyncio.to_thread(validate, ctx.conceptual)
        if settings.LLM_PROVIDER != "mock":
            issues = await review(ctx, issues)
        ctx.conceptual.issues = issues
        _emit(ctx.run_id, "stage", stage="validation", progress=0.9, message=f"{len(issues)} pontos avaliados")

        await _simulate_step()
        _update_run(ctx.run_id, status="artifacts", stage="artifacts", progress=PROGRESS["artifacts"])
        _emit(ctx.run_id, "stage", stage="artifacts", progress=PROGRESS["artifacts"], message="Gerando artefatos...")
        ctx = await asyncio.to_thread(generate_artifacts, ctx)
        _save_artifacts(ctx)
        _save_token_usage(ctx)
        _update_run(ctx.run_id, status="done", stage="done", progress=PROGRESS["done"], finished_at=_now())
        _emit(ctx.run_id, "finished", stage="done", progress=PROGRESS["done"], message="Análise concluída")
    except Exception as exc:  # noqa: BLE001 - borda do pipeline: qualquer erro marca a run como failed
        with session_scope() as session:
            run = session.get(AnalysisRun, ctx.run_id)
            run.status = "failed"
            run.stage = "failed"
            run.error_message = str(exc)
            run.finished_at = _now()
            session.add(RunLog(run_id=ctx.run_id, level="error", message=str(exc)))
        _emit(ctx.run_id, "failed", stage="failed", message=str(exc))
