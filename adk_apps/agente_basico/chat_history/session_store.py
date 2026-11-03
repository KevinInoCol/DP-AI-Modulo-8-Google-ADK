"""
Histórico de conversación — sesiones de ADK en PostgreSQL.

En ADK la memoria del hilo es la SESIÓN: el Runner la lee y la guarda solo a
través de un SessionService. Aquí se usa DatabaseSessionService sobre Postgres
(Supabase, Session pooler :5432). Doc: https://adk.dev/sessions/session/

ADK crea sus tablas (sessions, events, app_states, user_states) dentro de un
ESQUEMA propio del agente (AGENTE_BASICO_DB_SCHEMA, por defecto
`agente_basico_adk`) para no mezclarse con otras tablas ni con TramiBot.

Se usa una variable con prefijo (y no DB_SCHEMA) porque `adk web adk_apps`
carga todos los agentes en un mismo proceso: load_dotenv no sobrescribe, así
que el DB_SCHEMA del primer agente cargado taparía el de este.

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
DB_SCHEMA = os.getenv("AGENTE_BASICO_DB_SCHEMA", "agente_basico_adk")

if not all([DB_USER, DB_PASSWORD, DB_HOST]):
    raise ValueError(
        "❌ Faltan variables de base de datos en .env\n"
        "Requeridas: DB_USER, DB_PASSWORD, DB_HOST"
    )
if not re.fullmatch(r"[a-z_][a-z0-9_]*", DB_SCHEMA):
    raise ValueError(f"❌ AGENTE_BASICO_DB_SCHEMA={DB_SCHEMA!r} debe ser snake_case (a-z, 0-9, _)")

# URL.create escapa la contraseña (no hace falta quote_plus)
DATABASE_URL = URL.create(
    "postgresql+asyncpg",
    username=DB_USER,
    password=DB_PASSWORD,
    host=DB_HOST,
    port=DB_PORT,
    database=DB_NAME,
)

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


# ============================================
# 3. LEER EL HISTORIAL DE UNA SESIÓN
# ============================================
async def obtener_historial(app_name: str, user_id: str, session_id: str) -> list[dict]:
    """
    Devuelve los mensajes de la sesión como [{"rol": "user"|"agente", "texto": str}].
    Omite las llamadas y respuestas de tools y las partes de razonamiento.
    """
    await preparar_esquema()
    sesion = await session_service.get_session(
        app_name=app_name, user_id=user_id, session_id=session_id
    )
    if not sesion:
        return []

    mensajes = []
    for event in sesion.events:
        if not event.content or not event.content.parts:
            continue
        texto = "".join(
            p.text for p in event.content.parts
            if getattr(p, "text", None) and not getattr(p, "thought", False)
        ).strip()
        if not texto:
            continue
        if event.author == "user":
            mensajes.append({"rol": "user", "texto": texto})
        elif event.is_final_response():
            mensajes.append({"rol": "agente", "texto": texto})
    return mensajes
