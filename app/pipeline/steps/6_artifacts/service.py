from app.pipeline.types import AnalysisContext

from .mermaid_generator import generate_er_mermaid
from .report_generator import generate_report
from .sql_generator import generate_sql


def generate_artifacts(ctx: AnalysisContext) -> AnalysisContext:
    ctx.artifacts["schema.sql"] = generate_sql(ctx.conceptual)
    ctx.artifacts["schema.mmd"] = generate_er_mermaid(ctx.conceptual)
    ctx.artifacts["model.json"] = ctx.conceptual.model_dump_json(indent=2)
    ctx.artifacts["report.md"] = generate_report(ctx)
    return ctx
