import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.exceptions import UploadError
from app.db.session import get_session
from app.helpers.auth import get_current_user, get_owned_project, get_owned_run
from app.models.analysis_run import AnalysisRun
from app.models.token_usage import TokenUsage as TokenUsageModel
from app.models.upload import Upload
from app.models.user import User
from app.pipeline.orchestrator import bus, run_pipeline
from app.pipeline.types import AnalysisContext
from app.schemas.run import (
    ArtifactPublic,
    RunDetail,
    RunMetricsResponse,
    RunPublic,
    RunStatusResponse,
    TokenUsagePublic,
)

router = APIRouter()

# `asyncio.create_task` só guarda uma referência fraca à task. Sem manter uma
# referência forte aqui, o GC pode coletar a pipeline no meio da execução e a run
# fica parada num estágio intermediário para sempre, sem nunca virar "failed".
_tasks: set[asyncio.Task] = set()


@router.post("/{project_id}/analyze", response_model=RunPublic, status_code=202)
async def analyze_project(
    project_id: int,
    current: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    project = get_owned_project(session, project_id, current.id)
    upload = (
        session.query(Upload)
        .filter(Upload.project_id == project.id)
        .order_by(Upload.created_at.desc())
        .first()
    )
    if upload is None:
        raise UploadError("Envie um ZIP do projeto antes de analisar")
    run = AnalysisRun(project_id=project.id, user_id=current.id, status="pending", stage="pending", progress=0.0, progress_json={})
    session.add(run)
    session.commit()
    session.refresh(run)
    ctx = AnalysisContext(run_id=run.id, project_id=project.id, project_name=project.name, root_path=Path(upload.stored_path))
    task = asyncio.create_task(run_pipeline(ctx))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return run


@router.get("", response_model=list[RunPublic])
def list_runs(current: User = Depends(get_current_user), session: Session = Depends(get_session)):
    return (
        session.query(AnalysisRun)
        .filter(AnalysisRun.user_id == current.id)
        .order_by(AnalysisRun.created_at.desc())
        .all()
    )


@router.get("/{run_id}", response_model=RunDetail)
def get_run(run_id: int, current: User = Depends(get_current_user), session: Session = Depends(get_session)):
    run = get_owned_run(session, run_id, current.id)
    # `RunDetail.scanned_files` é uma contagem, mas o ORM expõe `scanned_files`
    # como relação (lista de ScannedFile): validar o objeto inteiro contra
    # RunDetail estoura na validação, antes de dar tempo de sobrescrever o campo.
    # Valida-se então contra RunPublic, que não tem esse nome, e as contagens
    # entram explicitamente.
    detail = RunDetail(
        **RunPublic.model_validate(run).model_dump(),
        scanned_files=len(run.scanned_files),
        artifacts=[ArtifactPublic.model_validate(a) for a in run.artifacts],
    )
    if run.conceptual_model:
        detail.entities = len(run.conceptual_model.entities_json)
        detail.relationships = len(run.conceptual_model.relationships_json)
    return detail


@router.get("/{run_id}/status", response_model=RunStatusResponse)
def run_status(run_id: int, current: User = Depends(get_current_user), session: Session = Depends(get_session)):
    return get_owned_run(session, run_id, current.id)


@router.get("/{run_id}/metrics", response_model=RunMetricsResponse)
def run_metrics(run_id: int, current: User = Depends(get_current_user), session: Session = Depends(get_session)):
    run = get_owned_run(session, run_id, current.id)
    usages = (
        session.query(TokenUsageModel)
        .filter(TokenUsageModel.run_id == run.id)
        .order_by(TokenUsageModel.created_at)
        .all()
    )
    return RunMetricsResponse(
        total_tokens=run.total_tokens,
        total_cost_usd=run.total_cost_usd,
        steps=[TokenUsagePublic.model_validate(u) for u in usages],
    )


# Silêncio de 15s vira um comentário SSE. Folgado o bastante para não desperdiçar
# tráfego e curto o bastante para caber sob o timeout de qualquer proxy comum.
HEARTBEAT_SECONDS = 15

TERMINAL_STATUSES = ("done", "failed")


@router.get("/{run_id}/stream")
async def stream_run(run_id: int, current: User = Depends(get_current_user), session: Session = Depends(get_session)):
    run = get_owned_run(session, run_id, current.id)
    # Subscrever ANTES de ler o snapshot. Na ordem inversa existe uma janela em
    # que a pipeline emite "finished" depois da leitura e antes da inscrição: o
    # evento se perde e o cliente fica esperando um término que nunca chega.
    queue = bus.subscribe(run.id)
    snapshot = {
        "type": "snapshot",
        "run_id": run.id,
        "status": run.status,
        "stage": run.stage,
        "progress": run.progress,
        # Sem isto, um F5 numa run que falhou reabre a tela de progresso sem o
        # motivo do erro -- spinner girando sobre uma análise morta.
        "message": run.error_message,
    }
    terminal = run.status in TERMINAL_STATUSES

    async def generator():
        try:
            yield f"data: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
            # Run já concluída: o snapshot é a resposta inteira. Entrar no laço
            # aqui seria bater heartbeat para sempre num stream sem emissor.
            if terminal:
                return
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except TimeoutError:
                    # A etapa `modeling` passa mais de um minuto sem emitir nada
                    # (é ~99% do tempo da pipeline). Fechar o stream aqui era o
                    # que travava a barra em 72%. O ping é um comentário SSE: o
                    # cliente ignora toda linha que não comece com "data:", então
                    # ele segura a conexão sem virar evento.
                    yield ": ping\n\n"
                    continue
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("type") in ("finished", "failed"):
                    break
        finally:
            bus.unsubscribe(run.id, queue)


    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
