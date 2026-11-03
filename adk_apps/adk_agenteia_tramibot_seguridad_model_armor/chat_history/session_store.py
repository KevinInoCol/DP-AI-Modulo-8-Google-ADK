"""
Histórico de conversación — sesiones de ADK en Cloud SQL (Postgres 18), MULTITENANT.

En ADK la memoria del hilo es la SESIÓN: el Runner la lee y la guarda solo a
través de un SessionService. Aquí se usa DatabaseSessionService sobre la base
compartida `adk_historico` (esquema public), la misma para todos los agentes.
Doc: https://adk.dev/sessions/session/

Multitenant con RLS (ver infra/cloud_sql_historico/historico_multitenant.py):
  - Este agente se conecta con SU usuario de Postgres, DB_USER = "tramibot".
  - Cada fila de sessions/events/app_states/user_states lleva tenant_id, que
    Postgres rellena con current_user; la policy solo deja ver y escribir las
    filas de ese tenant. El código no tiene que filtrar nada.
  - Las tablas ya existen (las crea `historico_multitenant.py init`): este
    usuario no puede crear tablas, y ADK solo comprueba que estén.

Conexión:
  - Local:      Cloud SQL Auth Proxy → DB_HOST=127.0.0.1, DB_PORT=5432
  - Cloud Run:  --add-cloudsql-instances → DB_HOST=/cloudsql/<proyecto>:<región>:adk-historico

Las variables DB_* se leen del .env de ESTE paquete antes que del entorno:
`adk web adk_apps` carga todos los agentes en un mismo proceso y load_dotenv no
sobrescribe, así que con os.getenv el DB_USER del primer agente cargado se
usaría para todos (y escribiría en el tenant equivocado). En Cloud Run no hay
.env y se usa el entorno del servicio.

Esta carpeta es el ÚNICO lugar que conoce el backend de memoria.

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

import os
from pathlib import Path

from dotenv import dotenv_values
from google.adk.sessions import DatabaseSessionService
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

# ============================================
# 1. CONFIGURACIÓN DE BASE DE DATOS
# ============================================
_ENV_PAQUETE = Path(__file__).resolve().parent.parent / ".env"
_cfg = {**os.environ, **{k: v for k, v in dotenv_values(_ENV_PAQUETE).items() if v is not None}}

DB_USER = _cfg.get("DB_USER")          # = tenant_id de este agente
DB_PASSWORD = _cfg.get("DB_PASSWORD")
DB_HOST = _cfg.get("DB_HOST", "127.0.0.1")
DB_PORT = int(_cfg.get("DB_PORT", "5432"))
DB_NAME = _cfg.get("DB_NAME", "adk_historico")

if not all([DB_USER, DB_PASSWORD, DB_HOST]):
    raise ValueError(
        "❌ Faltan variables de base de datos en el .env del agente\n"
        "Requeridas: DB_USER, DB_PASSWORD, DB_HOST\n"
        "Créalas con: python infra/cloud_sql_historico/historico_multitenant.py tenant tramibot --env-file <.env>"
    )
if DB_USER != "tramibot":
    print(f"⚠️  DB_USER={DB_USER!r}: este agente debería usar el tenant 'tramibot'")

# URL.create escapa la contraseña; si DB_HOST es una carpeta (/cloudsql/...) asyncpg usa el socket
DATABASE_URL = URL.create(
    "postgresql+asyncpg",
    username=DB_USER,
    password=DB_PASSWORD,
    host=DB_HOST,
    port=DB_PORT,
    database=DB_NAME,
)

_engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)

session_service = DatabaseSessionService(db_engine=_engine)
