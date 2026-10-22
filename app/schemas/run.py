from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ArtifactPublic(ORMModel):
    id: int
    run_id: int
    kind: str
    filename: str
    size_bytes: int
    created_at: datetime


class RunPublic(ORMModel):
    id: int
    project_id: int
    status: str
    stage: str
    progress: float
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    total_tokens: int = 0


class RunSummary(ORMModel):
    id: int
    status: str
    stage: str
    progress: float
    created_at: datetime


class RunDetail(RunPublic):
    scanned_files: int = 0
    entities: int = 0
    relationships: int = 0
    artifacts: list[ArtifactPublic] = Field(default_factory=list)


class RunStatusResponse(BaseModel):
    id: int
    status: str
    stage: str
    progress: float
    error_message: str | None = None


class TokenUsagePublic(ORMModel):
    step: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


class RunMetricsResponse(BaseModel):
    total_tokens: int
    total_cost_usd: float
    steps: list[TokenUsagePublic]
