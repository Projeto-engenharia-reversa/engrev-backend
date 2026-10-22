"""Parsers de formatos de definição de schema language-agnostic (Camada 2):
Prisma, Liquibase XML, Protobuf, OpenAPI/JSON Schema e GraphQL SDL. Cada um
consome o texto de um arquivo e devolve um `FileExtraction` (ou `None` se o
conteúdo não corresponder ao formato esperado), no mesmo formato usado pelos
parsers de linguagem em `parsers.py`.
"""
