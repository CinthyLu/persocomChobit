"""Configuración leída del archivo .env (ver .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent
load_dotenv(RAIZ.parent / ".env")


@dataclass(frozen=True)
class Config:
    telegram_token: str
    owner_id: int | None
    llm_model: str
    zona: ZoneInfo
    database_url: str


def cargar() -> Config:
    owner = os.getenv("TELEGRAM_OWNER_ID", "").strip()
    return Config(
        telegram_token=os.getenv("TELEGRAM_TOKEN", "").strip(),
        owner_id=int(owner) if owner else None,
        llm_model=os.getenv("LLM_MODEL", "").strip() or "claude-opus-5-5",
        zona=ZoneInfo(os.getenv("ZONA_HORARIA", "").strip() or "America/Guayaquil"),
        database_url=os.getenv("DATABASE_URL", "").strip() or "sqlite:///asistente.db",
    )
