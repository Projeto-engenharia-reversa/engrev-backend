from app.helpers.naming import to_snake
from app.pipeline.types import ConceptualModel, ValidationIssue


def validate(model: ConceptualModel) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    table_names = {t.name for t in model.tables}
    for table in model.tables:
        if to_snake(table.name) != table.name:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    message=f"Nome da tabela '{table.name}' deve ser snake_case.",
                    source=table.name,
                    suggestion=to_snake(table.name),
                )
            )
        seen: set[str] = set()
        pk = [c for c in table.columns if c.primary_key]
        if not pk:
            issues.append(
                ValidationIssue(
                    severity="error",
                    message=f"Tabela '{table.name}' sem chave primária.",
                    source=table.name,
                    suggestion="Adicione uma coluna 'id' como PRIMARY KEY.",
                )
            )
        for column in table.columns:
            if column.name in seen:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        message=f"Coluna duplicada '{column.name}' em '{table.name}'.",
                        source=table.name,
                        suggestion="Renomeie a coluna duplicada.",
                    )
                )
            seen.add(column.name)
            if column.fk_table and column.fk_table not in table_names:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        message=f"FK de '{table.name}.{column.name}' referencia tabela inexistente '{column.fk_table}'.",
                        source=table.name,
                        suggestion=f"Crie a tabela '{column.fk_table}' ou remova a FK.",
                    )
                )
    for rel in model.relationships:
        for name in (rel.table_a, rel.table_b, rel.through):
            if name and name not in table_names:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        message=f"Relacionamento '{rel.name}' referencia tabela inexistente '{name}'.",
                        source=rel.name,
                    )
                )
    return issues
