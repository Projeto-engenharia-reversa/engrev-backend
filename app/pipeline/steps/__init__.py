from importlib import import_module


def _step(module: str, name: str):
    return getattr(import_module(f"app.pipeline.steps.{module}"), name)


scan = _step("1_scan.scanner", "scan")
parse = _step("2_parse.parser", "parse")
build_structural = _step("3_structural.builder", "build_structural")
build_context = _step("3_structural.context_builder", "build_context")
select_evidence = _step("3_structural.context_builder", "select_evidence")
model = _step("4_modeling.agent", "model")
validate = _step("5_validation.rules", "validate")
review = _step("5_validation.agent", "review")
generate_artifacts = _step("6_artifacts.service", "generate_artifacts")

__all__ = ["build_context", "build_structural", "generate_artifacts", "model", "parse", "review", "scan", "select_evidence", "validate"]
