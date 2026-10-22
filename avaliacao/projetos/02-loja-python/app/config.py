"""Configuracao lida do ambiente."""

import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://loja:loja@localhost:5432/loja")
SECRET_KEY = os.getenv("SECRET_KEY", "trocar-em-producao")
DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"

FRETE_GRATIS_ACIMA_DE = 250.00
PARCELAS_MAXIMAS = 12
