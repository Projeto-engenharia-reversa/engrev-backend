"""Mapeamento de tipos SQL para os tipos genéricos do modelo conceitual.

Módulo pequeno e neutro pra ser reaproveitado tanto pelo parser SQL (`parsers.py`)
quanto por parsers de formato de schema que carregam tipos em sintaxe SQL-like
(ex.: Liquibase XML, onde `<column type="varchar(20)">` usa os mesmos nomes de tipo).
"""


def sql_type_to_generic(raw_type: str) -> str:
    t = raw_type.upper()
    if "SERIAL" in t or "INT" in t:
        return "integer"
    if any(k in t for k in ("VARCHAR", "TEXT", "CHAR")):
        return "string"
    if "BOOL" in t:
        return "boolean"
    if any(k in t for k in ("NUMERIC", "DECIMAL", "FLOAT", "REAL", "DOUBLE")):
        return "decimal"
    if any(k in t for k in ("TIMESTAMP", "DATETIME")):
        return "datetime"
    if "DATE" in t:
        return "date"
    if "UUID" in t:
        return "uuid"
    if "JSON" in t:
        return "json"
    return "string"
