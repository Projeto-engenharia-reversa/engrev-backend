from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.session import get_session
from app.helpers.auth import get_current_user, get_owned_run
from app.models.artifact import Artifact
from app.models.user import User
from app.schemas.run import ArtifactPublic

router = APIRouter()

_MEDIA = {
    "sql": "application/sql",
    "mmd": "text/plain",
    "md": "text/markdown",
    "json": "application/json",
}


@router.get("/{run_id}", response_model=list[ArtifactPublic])
def list_artifacts(run_id: int, current: User = Depends(get_current_user), session: Session = Depends(get_session)):
    get_owned_run(session, run_id, current.id)
    return session.query(Artifact).filter(Artifact.run_id == run_id).order_by(Artifact.created_at).all()


@router.get("/{artifact_id}/download")
def download_artifact(artifact_id: int, current: User = Depends(get_current_user), session: Session = Depends(get_session)):
    artifact = session.get(Artifact, artifact_id)
    if artifact is None:
        raise NotFoundError("Artefato não encontrado")
    get_owned_run(session, artifact.run_id, current.id)
    media_type = _MEDIA.get(artifact.kind, "application/octet-stream")
    return Response(
        content=artifact.content or "",
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{artifact.filename}"'},
    )
