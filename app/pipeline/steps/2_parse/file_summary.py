import re

IMPORT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.MULTILINE),
    re.compile(r"^\s*import\s+.*?from\s+['\"]([^'\"]+)['\"]", re.MULTILINE),
    re.compile(r"require\(['\"]([^'\"]+)['\"]\)"),
    re.compile(r"^\s*import\s+([\w.]+);", re.MULTILINE),
    re.compile(r"^\s*\"([\w./-]+)\"", re.MULTILINE),
    re.compile(r"^\s*(?:use\s+([\w\\\\]+);|require(?:_once)?\(['\"]([^'\"]+)['\"]\))", re.MULTILINE),
    re.compile(r"^\s*require(?:_relative)?\s+['\"]([^'\"]+)['\"]", re.MULTILINE),
    re.compile(r"^\s*#\s*include\s*[<\"]([\w./]+)[>\"]", re.MULTILINE),
    re.compile(r"^\s*(?:import|using)\s+([\w.]+)\s*;", re.MULTILINE),
]

EXPORT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^(?:class|def)\s+([A-Za-z_]\w*)", re.MULTILINE),
    re.compile(r"^\s*export\s+(?:default\s+)?(?:class|interface|type|function|const)\s+([A-Za-z_]\w*)", re.MULTILINE),
    re.compile(r"^\s*(?:export\s+)?(?:class|function)\s+([A-Za-z_]\w*)", re.MULTILINE),
    re.compile(r"^\s*(?:(?:public|private|protected)\s+)?(?:class|interface|enum)\s+([A-Za-z_]\w*)", re.MULTILINE),
    re.compile(r"^\s*func\s+([A-Za-z_]\w*)", re.MULTILINE),
    re.compile(r"^\s*type\s+([A-Za-z_]\w*)", re.MULTILINE),
    re.compile(r"^\s*(?:final\s+|abstract\s+)?class\s+([A-Za-z_]\w*)", re.MULTILINE),
    re.compile(r"^\s*(?:class|module)\s+([A-Za-z_]\w*)", re.MULTILINE),
    re.compile(r"^\s*(?:struct|enum|union)\s+([A-Za-z_]\w*)", re.MULTILINE),
    re.compile(r"^\s*(?:class|struct|enum|namespace)\s+([A-Za-z_]\w*)", re.MULTILINE),
    re.compile(r"^\s*(?:public|internal|private|protected)\s*(?:abstract\s+|sealed\s+|static\s+)?class\s+([A-Za-z_]\w*)", re.MULTILINE),
    re.compile(r"^\s*(?:pub\s+)?(?:struct|enum|fn|trait|impl)\s+([A-Za-z_]\w*)", re.MULTILINE),
    re.compile(r"^\s*(?:public|private|protected)\s+interface\s+([A-Za-z_]\w*)", re.MULTILINE),
]


def _unique_groups(pattern: re.Pattern[str], text: str) -> list[str]:
    found = []
    for match in pattern.finditer(text):
        for group in match.groups():
            if group:
                found.append(group)
    return found


def summarize_file(text: str) -> tuple[list[str], list[str]]:
    imported = []
    for pattern in IMPORT_PATTERNS:
        imported.extend(_unique_groups(pattern, text))
    exported = []
    for pattern in EXPORT_PATTERNS:
        exported.extend(_unique_groups(pattern, text))
    return list(dict.fromkeys(imported))[:50], list(dict.fromkeys(exported))[:50]
