from pathlib import Path

IGNORED_DIRS = {
    "node_modules", ".git", ".venv", "venv", "__pycache__", "dist", "build",
    "vendor",          # dependência do PHP (Composer) e do Go pré-módulos
    "deps", "_build",  # dependência e build do Elixir; o Mix usa sublinhado
    ".next", "target", ".idea", ".vscode", "coverage", ".mypy_cache", ".pytest_cache",
    # O parser de JSON transforma qualquer objeto em tabela, inclusive estes.
    ".devcontainer", ".github", ".husky", ".circleci",
}

# Código de teste não é modelo de domínio em linguagem nenhuma.
DIRETORIOS_DE_TESTE = {"test", "tests", "__tests__", "spec", "specs", "testing"}

# Exceção ao filtro acima: fixture não declara classe, declara registro, com nome
# de coluna e chave estrangeira. É a evidência que sobra em projeto sem schema.
_DADOS_DE_TESTE = (".yml", ".yaml", ".json", ".sql", ".csv")

_SUFIXOS_DE_TESTE = (
    "Test.java", "Tests.java", "IT.java",
    "Test.cs", "Tests.cs",
    "_test.py", "_test.go", "_test.rb",
    ".spec.ts", ".spec.js", ".test.ts", ".test.js", ".spec.tsx", ".test.tsx",
)

# O critério é o nome, não a extensão: `data/categoria.json` continua passando.
ARQUIVOS_DE_CONFIGURACAO = {
    "package.json", "angular.json", "composer.json", "devcontainer.json",
    "nx.json", "firebase.json", "jsconfig.json", "manifest.json",
    "global.json", "dotnet-tools.json", "packages.lock.json", "launchSettings.json",
    "jest.json", "nodemon.json", "nest-cli.json", "lerna.json",
    ".eslintrc.json", ".prettierrc.json", ".babelrc.json",
}

IGNORED_FILES = {
    ".gitignore", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", ".DS_Store", "Thumbs.db",
    "mvnw", "mvnw.cmd", "gradlew", "gradlew.bat",
    "LICENSE", "LICENSE.txt", "LICENSE.md", "NOTICE", "NOTICE.txt", "CHANGELOG.md",
}

# Sem parser dedicado estes iriam inteiros para a evidência bruta, consumindo o
# orçamento do prompt sem descrever dado nenhum.
EXTENSOES_DE_APRESENTACAO = {
    ".css", ".scss", ".sass", ".less", ".styl",
    ".svg", ".eot", ".ttf", ".otf", ".woff", ".woff2",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".avif", ".heic",
    ".mp3", ".mp4", ".ogg", ".webm", ".wav",
    ".pdf", ".zip", ".gz", ".tar", ".jar", ".war", ".class", ".pyc", ".so", ".dll",
    ".po", ".pot", ".mo",  # catálogo de tradução: texto de interface, não dado
}


def _e_teste(rel_path: Path) -> bool:
    nome = rel_path.name
    if any(part.lower() in DIRETORIOS_DE_TESTE for part in rel_path.parts[:-1]):
        return not nome.lower().endswith(_DADOS_DE_TESTE)
    if nome.endswith(_SUFIXOS_DE_TESTE):
        return True
    return nome.startswith("test_") and nome.endswith(".py")


def _e_configuracao(rel_path: Path) -> bool:
    nome = rel_path.name
    if nome in ARQUIVOS_DE_CONFIGURACAO:
        return True
    if nome.startswith("tsconfig") and nome.endswith(".json"):
        return True
    # Coleção do Postman descreve requisição, não dado.
    if nome.lower().endswith((".postman_collection.json", ".postman_environment.json")):
        return True
    # Cobre nestconfig.json, jest.config.json e afins sem uma entrada por ferramenta.
    return nome.endswith(".json") and "config" in nome.lower()


def should_ignore(rel_path: Path) -> bool:
    parts = rel_path.parts
    if any(part in IGNORED_DIRS for part in parts[:-1]):
        return True
    if rel_path.name in IGNORED_FILES:
        return True
    if _e_teste(rel_path) or _e_configuracao(rel_path):
        return True
    if rel_path.suffix.lower() in EXTENSOES_DE_APRESENTACAO:
        return True
    return rel_path.name.endswith((".map", ".min.js"))
