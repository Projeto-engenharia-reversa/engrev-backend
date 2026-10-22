from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.analysis_run import AnalysisRun


class StructuralSnapshot(Base):
    """Snapshot do `StructuralModel` logo após a etapa `structural` (Fase 4.3) —
    puramente aditivo: garante que os dados sobrevivem a um crash antes da
    etapa `modeling`. Não implementa retomada automática de execução (fora de
    escopo desta fase); é só persistência de auditoria/recuperação manual."""

    __tablename__ = "structural_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)
    structural_json: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped[AnalysisRun] = relationship(back_populates="structural_snapshot")
