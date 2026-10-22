from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel
from app.schemas.run import RunSummary


class ProjectCreate(BaseModel):
    name: str
    language_hint: str | None = None


class ProjectUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class ProjectPublic(ORMModel):
    id: int
    name: str
    language_hint: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime


class ProjectListItem(ProjectPublic):
    """O projeto como ele aparece na listagem, com o resumo das análises junto.

    `Project.status` sozinho não responde a pergunta que a tela faz — ele vale
    "created" ou "ready" e fala sobre o *upload*, não sobre a análise. Quem
    responde é a última run.

    `last_activity_at` é `max(updated_at, created_at da última run)`: o
    `onupdate` da coluna só dispara quando a linha do projeto é escrita, e
    rodar uma análise não escreve nela — sem o máximo, um projeto analisado hoje
    apareceria com a data do upload.
    """

    runs_count: int = 0
    last_run_status: str | None = None
    last_activity_at: datetime


class ProjectDetail(ProjectPublic):
    runs: list[RunSummary] = Field(default_factory=list)


class FileEligibilityItem(BaseModel):
    path: str
    size_bytes: int
    status: str
    reason: str | None = None


class UploadResult(BaseModel):
    project_id: int
    original_filename: str
    total_files: int
    accepted_files: int
    items: list[FileEligibilityItem]
