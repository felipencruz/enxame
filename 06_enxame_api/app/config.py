"""Configuração do enxame-api: lê o .env local, que não é versionado."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

# Diretório onde as receitas propostas ficam versionadas (apêndice auditável da monografia).
DIR_RECEITAS = Path(__file__).resolve().parent.parent / "receitas"
