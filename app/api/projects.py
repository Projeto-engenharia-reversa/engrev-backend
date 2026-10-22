import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import UploadError
from app.db.session import get_session
from app.helpers.auth import get_current_user, get_owned_project
from app.helpers.storage import UPLOAD_ROOT, extract_zip
from app.models.analysis_run import AnalysisRun
from app.models.project import Project
from app.models.upload import Upload
from app.models.user import User
from app.schemas.project import (
    FileEligibilityItem,
    ProjectCreate,
    ProjectDetail,
    ProjectListItem,
    ProjectPublic,
    ProjectUpdate,
    UploadResult,
)

router = APIRouter()


@router.post("", response_model=ProjectPublic, status_code=201)
def create_project(data: ProjectCreate, current: User = Depends(get_current_user), session: Session = Depends(get_session)):
    project = Project(owner_id=current.id, name=data.name, language_hint=data.language_hint)
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


@router.get("", response_model=list[ProjectListItem])
def list_projects(current: User = Depends(get_current_user), session: Session = Depends(get_session)):
    """A listagem carrega o resumo das análises junto.

    Duas consultas, não N+1: uma para os projetos e uma para as runs de todos
    eles. As runs vêm ordenadas por data decrescente, então a primeira que
    aparece para cada projeto é a mais recente — agrupar em Python evita uma
    subconsulta correlacionada para buscar o status da última.
    """
    projects = session.query(Project).filter(Project.owner_id == current.id).all()
    if not projects:
        return []

    ultima_run: dict[int, AnalysisRun] = {}
    contagem: dict[int, int] = {}
    runs = (
        session.query(AnalysisRun)
        .filter(AnalysisRun.project_id.in_([p.id for p in projects]))
        .order_by(AnalysisRun.created_at.desc())
        .all()
    )
    for run in runs:
        contagem[run.project_id] = contagem.get(run.project_id, 0) + 1
        ultima_run.setdefault(run.project_id, run)

    itens = []
    for project in projects:
        run = ultima_run.get(project.id)
        atividade = project.updated_at
        if run is not None and run.created_at > atividade:
            atividade = run.created_at
        itens.append(
            ProjectListItem(
                **ProjectPublic.model_validate(project).model_dump(),
                runs_count=contagem.get(project.id, 0),
                last_run_status=run.status if run is not None else None,
                last_activity_at=atividade,
            )
        )
    # Ordenado por atividade, não por criação: numa tela que existe para retomar
    # o trabalho, o que importa é o que foi mexido por último.
    itens.sort(key=lambda i: i.last_activity_at, reverse=True)
    return itens


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(project_id: int, current: User = Depends(get_current_user), session: Session = Depends(get_session)):
    return get_owned_project(session, project_id, current.id)


@router.patch("/{project_id}", response_model=ProjectPublic)
def rename_project(
    project_id: int,
    data: ProjectUpdate,
    current: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    project = get_owned_project(session, project_id, current.id)
    project.name = data.name.strip()
    if not project.name:
        raise HTTPException(status_code=422, detail="O nome do projeto não pode ficar vazio.")
    session.commit()
    session.refresh(project)
    return project


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: int, current: User = Depends(get_current_user), session: Session = Depends(get_session)):
    project = get_owned_project(session, project_id, current.id)
    session.delete(project)
    session.commit()
    project_dir = Path(UPLOAD_ROOT) / str(project_id)
    if project_dir.exists():
        shutil.rmtree(project_dir, ignore_errors=True)


@router.post("/{project_id}/upload", response_model=UploadResult)
async def upload_project_zip(
    project_id: int,
    file: UploadFile = File(...),
    current: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    project = get_owned_project(session, project_id, current.id)
    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise UploadError(f"O arquivo excede o limite de {settings.MAX_UPLOAD_SIZE_MB}MB")
    stored_path, manifest, total, accepted = extract_zip(content, project.id)
    upload = Upload(
        project_id=project.id,
        original_filename=file.filename or "projeto.zip",
        stored_path=str(stored_path),
        size_bytes=len(content),
        total_files=total,
        accepted_files=accepted,
        file_manifest=manifest,
    )
    session.add(upload)
    project.status = "ready"
    session.commit()
    return UploadResult(
        project_id=project.id,
        original_filename=upload.original_filename,
        total_files=total,
        accepted_files=accepted,
        items=[FileEligibilityItem.model_validate(item) for item in manifest],
    )
