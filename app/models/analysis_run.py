from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.artifact import Artifact
    from app.models.conceptual_model import ConceptualModel
    from app.models.project import Project
    from app.models.run_log import RunLog
    from app.models.scanned_file import ScannedFile
    from app.models.structural_snapshot import StructuralSnapshot
    from app.models.token_usage import TokenUsage



class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", server_default="pending")
    stage: Mapped[str] = mapped_column(String(32), default="pending", server_default="pending")
    progress: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text)
    progress_json: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="runs")
    scanned_files: Mapped[list[ScannedFile]] = relationship(back_populates="run", cascade="all, delete-orphan")
    structural_snapshot: Mapped[StructuralSnapshot] = relationship(back_populates="run", uselist=False, cascade="all, delete-orphan")
    conceptual_model: Mapped[ConceptualModel] = relationship(back_populates="run", uselist=False, cascade="all, delete-orphan")
    artifacts: Mapped[list[Artifact]] = relationship(back_populates="run", cascade="all, delete-orphan")
    token_usages: Mapped[list[TokenUsage]] = relationship(back_populates="run", cascade="all, delete-orphan")
    logs: Mapped[list[RunLog]] = relationship(back_populates="run", cascade="all, delete-orphan")
