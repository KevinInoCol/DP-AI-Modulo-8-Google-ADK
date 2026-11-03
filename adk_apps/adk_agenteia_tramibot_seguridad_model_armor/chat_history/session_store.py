"""
Backend de persistencia de conversación (Histórico) — PostgreSQL con ADK.

En la versión LangChain el historial vivía en una tabla `chat_history`
(PostgresChatMessageHistory) y el agente lo cargaba a mano en cada turno.
En ADK la memoria del hilo es la SESIÓN: el Runner la lee y la guarda solo,
a través de un SessionService. Aquí se usa DatabaseSessionService sobre el
mismo Postgres (Supabase). Doc: https://adk.dev/sessions/session/

ADK crea sus propias tablas (sessions, events, app_states, user_states…).
Para que no se mezclen con otras tablas del proyecto viven en un ESQUEMA
propio (DB_SCHEMA, por defecto `tramibot_adk`), que se crea si no existe.

Requisitos: driver asíncrono asyncpg (pip install 'google-adk[db]' asyncpg).
Con Supabase usa el Session pooler (puerto 5432): el Transaction pooler (6543)
no admite las sentencias preparadas de asyncpg.

Esta carpeta es el ÚNICO lugar que conoce el backend de memoria.

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

import os
import re

from dotenv import load_dotenv, find_dotenv
from google.adk.sessions import DatabaseSessionService
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

load_dotenv(find_dotenv())

# ============================================
# 1. CONFIGURACIÓN DE BASE DE DATOS
# ============================================
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "postgres")
DB_SCHEMA = os.getenv("DB_SCHEMA", "tramibot_adk")

if not all([DB_USER, DB_PASSWORD, DB_HOST]):
    raise ValueError(
        "❌ Faltan variables de base de datos en .env\n"
        "Requeridas: DB_USER, DB_PASSWORD, DB_HOST"
    )
if not re.fullmatch(r"[a-z_][a-z0-9_]*", DB_SCHEMA):
    raise ValueError(f"❌ DB_SCHEMA={DB_SCHEMA!r} debe ser snake_case (a-z, 0-9, _)")

# URL.create escapa la contraseña (no hace falta quote_plus)
DATABASE_URL = URL.create(
    "postgresql+asyncpg",
    username=DB_USER,
    password=DB_PASSWORD,
    host=DB_HOST,
    port=DB_PORT,
    database=DB_NAME,
)

print(f"🔌 Sesiones ADK en Postgres: {DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME} (esquema {DB_SCHEMA})")

# Motor propio para fijar el search_path al esquema del agente en cada conexión
_engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"server_settings": {"search_path": DB_SCHEMA}},
)

session_service = DatabaseSessionService(db_engine=_engine)

_esquema_listo = False


# ============================================
# 2. CREAR ESQUEMA (idempotente)
# ============================================
async def preparar_esquema() -> None:
    """Crea el esquema del agente si no existe. Las tablas las crea ADK."""
    global _esquema_listo
    if _esquema_listo:
        return
    async with _engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{DB_SCHEMA}"'))
    _esquema_listo = True
