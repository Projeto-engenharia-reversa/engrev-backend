from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.analysis_run import AnalysisRun



class ConceptualModel(Base):
    __tablename__ = "conceptual_models"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)
    entities_json: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    relationships_json: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    queries_json: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    quality_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    generated_by: Mapped[str] = mapped_column(String(64), default="llm", server_default="llm")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped[AnalysisRun] = relationship(back_populates="conceptual_model")
