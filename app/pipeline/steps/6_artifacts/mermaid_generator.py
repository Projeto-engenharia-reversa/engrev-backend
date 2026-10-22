from app.pipeline.types import ConceptualModel

from .fk_resolution import missing_junctions, resolve_sides

_MERMAID_TYPES = {
    "integer": "int",
    "string": "string",
    "text": "string",
    "boolean": "bool",
    "decimal": "float",
    "number": "float",
    "datetime": "datetime",
    "date": "date",
    "uuid": "uuid",
    "json": "json",
}

_CARDINALITY = {"one-to-many": "||--o{", "one-to-one": "||--||", "many-to-many": "}o--o{"}


def _mermaid_type(data_type: str) -> str:
    return _MERMAID_TYPES.get(data_type.strip().lower(), data_type)


def generate_er_mermaid(model: ConceptualModel) -> str:
    """Gera o diagrama ER.

    A cardinalidade sai de qual tabela realmente possui a coluna de FK
    (`fk_resolution.resolve_sides`), não da ordem de `table_a`/`table_b` — o LLM
    não emite essa ordem de forma consistente, e confiar nela invertia a
    cardinalidade em boa parte dos diagramas.
    """
    juncoes = missing_junctions(model)

    lines = ["erDiagram"]
    for table in model.tables:
        lines.append(f"    {table.name} {{")
        for column in table.columns:
            marker = "PK" if column.primary_key else "FK" if column.fk_table else ""
            lines.append(f"        {_mermaid_type(column.data_type)} {column.name} {marker}".rstrip())
        lines.append("    }")

    # Sem o bloco próprio, a junção aparece como caixa vazia no diagrama.
    for nome, col_a, _tabela_a, col_b, _tabela_b in juncoes:
        lines.append(f"    {nome} {{")
        lines.append("        int id PK")
        lines.append(f"        int {col_a} FK")
        lines.append(f"        int {col_b} FK")
        lines.append("    }")

    for rel in model.relationships:
        if rel.through:
            # A junção é sempre o lado "many" das duas pontas.
            lines.append(f"    {rel.table_a} ||--o{{ {rel.through} : \"{rel.name}\"")
            lines.append(f"    {rel.through} }}o--|| {rel.table_b} : \"{rel.name}\"")
            continue
        if rel.kind == "one-to-many":
            # Na ausência de metadado, vale a leitura natural da seta do modelo:
            # `table_a -(one-to-many)-> table_b` = table_a tem vários table_b.
            lado_one, lado_many = resolve_sides(model, rel) or (rel.table_a, rel.table_b)
            lines.append(f"    {lado_one} ||--o{{ {lado_many} : \"{rel.name}\"")
            continue
        cardinality = _CARDINALITY.get(rel.kind, "||--o{")
        lines.append(f"    {rel.table_a} {cardinality} {rel.table_b} : \"{rel.name}\"")
    return "\n".join(lines)
