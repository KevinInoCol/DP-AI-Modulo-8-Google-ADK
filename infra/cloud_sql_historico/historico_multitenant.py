"""
Histórico de conversación MULTITENANT para los agentes de ADK (Cloud SQL · Postgres 18).

Una sola base (`adk_historico`), esquema `public`, las 5 tablas de ADK compartidas
por todos los agentes. Cada fila de historial pertenece a un tenant (= un agente)
y Row Level Security impide que un agente vea o escriba filas de otro.

  Tabla                   ¿RLS?  Por qué
  ──────────────────────  ─────  ────────────────────────────────────────────────
  sessions                sí     una fila por conversación (app_name, user_id, id)
  events                  sí     mensajes, llamadas a tools, respuestas
  app_states              sí     estado app:* de cada App
  user_states             sí     estado user:* por usuario
  adk_internal_metadata   NO     una sola fila global (schema_version); con RLS el
                                 2º agente chocaría con la PK al registrarla

Cómo se identifica el tenant: cada agente se conecta con SU PROPIO usuario de
Postgres, llamado igual que el tenant (`agente_basico`, `tramibot`…). La columna
`tenant_id` toma por defecto `current_user` y la policy exige
`tenant_id = current_user`, así que ADK no necesita saber nada de tenants y el
código del agente no puede hacerse pasar por otro.

Requisitos para que la RLS sirva de algo (todos aplicados aquí):
  - Las tablas son de `adk_owner` (NOLOGIN), no de los usuarios de los agentes.
  - FORCE ROW LEVEL SECURITY: ni siquiera el dueño se salta las policies.
  - Los usuarios de agentes se crean con SQL (NOBYPASSRLS, sin cloudsqlsuperuser).
  - Auditoría: policy auditoria_owner (solo SELECT, solo adk_owner) para que el
    admin pueda contar filas de todos los tenants con SET ROLE adk_owner.

Uso (con el Cloud SQL Auth Proxy abierto en 127.0.0.1:5432):

    python historico_multitenant.py init
    python historico_multitenant.py tenant agente_basico --env-file ../../adk_apps/agente_basico/.env
    python historico_multitenant.py tenant tramibot --env-file ../../adk_apps/adk_agenteia_tramibot_seguridad_model_armor/.env
    python historico_multitenant.py verificar

`tenant` crea el usuario (o rota su contraseña) y escribe DB_USER/DB_PASSWORD/
DB_HOST/DB_PORT/DB_NAME en el .env del agente. Nunca imprime la contraseña.

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

import argparse
import asyncio
import os
import re
import secrets
from pathlib import Path

import asyncpg
from dotenv import load_dotenv
from google.adk.sessions.migration import _schema_check_utils
from google.adk.sessions.schemas.v1 import Base as AdkBaseV1
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

load_dotenv(Path(__file__).parent / ".env")

# ============================================
# CONFIGURACIÓN (admin de la instancia, vía Cloud SQL Auth Proxy)
# ============================================
ADMIN_USER = os.getenv("HISTORICO_ADMIN_USER", "postgres")
ADMIN_PASSWORD = os.getenv("HISTORICO_ADMIN_PASSWORD")
DB_HOST = os.getenv("HISTORICO_DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("HISTORICO_DB_PORT", "5432"))
DB_NAME = os.getenv("HISTORICO_DB_NAME", "adk_historico")

OWNER_ROLE = "adk_owner"
TABLAS_TENANT = ("sessions", "events", "app_states", "user_states")
TABLA_METADATA = "adk_internal_metadata"
TENANT_RE = re.compile(r"[a-z_][a-z0-9_]{0,62}")
ROLES_RESERVADOS = {"postgres", OWNER_ROLE, "public"}


def _validar_identificador(nombre: str) -> str:
    """Los nombres se interpolan en DDL (no admite parámetros): solo snake_case."""
    if not TENANT_RE.fullmatch(nombre) or nombre in ROLES_RESERVADOS or nombre.startswith("cloudsql"):
        raise SystemExit(f"❌ Nombre inválido: {nombre!r} (snake_case, máx. 63, no reservado)")
    return nombre


async def _conectar(database: str) -> asyncpg.Connection:
    if not ADMIN_PASSWORD:
        raise SystemExit("❌ Falta HISTORICO_ADMIN_PASSWORD en infra/cloud_sql_historico/.env")
    return await asyncpg.connect(
        user=ADMIN_USER, password=ADMIN_PASSWORD, host=DB_HOST, port=DB_PORT, database=database
    )


# ============================================
# init — base, rol dueño, tablas de ADK, tenant_id y RLS (idempotente)
# ============================================
async def init() -> None:
    conn = await _conectar("postgres")
    try:
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", DB_NAME):
            await conn.execute(f'CREATE DATABASE "{DB_NAME}"')
            print(f"🆕 Base {DB_NAME} creada")
        if not await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", OWNER_ROLE):
            await conn.execute(f"CREATE ROLE {OWNER_ROLE} NOLOGIN")
            print(f"🆕 Rol {OWNER_ROLE} creado")
        await conn.execute(f'GRANT {OWNER_ROLE} TO "{ADMIN_USER}"')
    finally:
        await conn.close()

    conn = await _conectar(DB_NAME)
    try:
        await conn.execute(f"REVOKE ALL ON DATABASE \"{DB_NAME}\" FROM PUBLIC")
        await conn.execute(f"GRANT USAGE, CREATE ON SCHEMA public TO {OWNER_ROLE}")
    finally:
        await conn.close()

    # Tablas EXACTAS de ADK (mismo modelo que usa DatabaseSessionService), creadas como adk_owner
    url = URL.create("postgresql+asyncpg", username=ADMIN_USER, password=ADMIN_PASSWORD,
                     host=DB_HOST, port=DB_PORT, database=DB_NAME)
    engine = create_async_engine(url)
    async with engine.begin() as sa_conn:
        await sa_conn.exec_driver_sql(f"SET ROLE {OWNER_ROLE}")
        await sa_conn.run_sync(AdkBaseV1.metadata.create_all)
    await engine.dispose()
    print("✅ Tablas de ADK listas: " + ", ".join((TABLA_METADATA,) + TABLAS_TENANT))

    conn = await _conectar(DB_NAME)
    try:
        async with conn.transaction():
            await conn.execute(f"SET LOCAL ROLE {OWNER_ROLE}")
            # Versión del esquema: así ADK solo necesita leer esta tabla
            await conn.execute(
                f"INSERT INTO {TABLA_METADATA} (key, value) VALUES ($1, $2) ON CONFLICT (key) DO NOTHING",
                _schema_check_utils.SCHEMA_VERSION_KEY,
                _schema_check_utils.LATEST_SCHEMA_VERSION,
            )
            await conn.execute(f"REVOKE ALL ON {TABLA_METADATA} FROM PUBLIC")
            for tabla in TABLAS_TENANT:
                await conn.execute(
                    f"ALTER TABLE {tabla} ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(63) "
                    f"NOT NULL DEFAULT (current_user)::varchar"
                )
                await conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{tabla}_tenant ON {tabla} (tenant_id)")
                await conn.execute(f"ALTER TABLE {tabla} ENABLE ROW LEVEL SECURITY")
                await conn.execute(f"ALTER TABLE {tabla} FORCE ROW LEVEL SECURITY")
                await conn.execute(f"DROP POLICY IF EXISTS aislamiento_tenant ON {tabla}")
                await conn.execute(
                    f"CREATE POLICY aislamiento_tenant ON {tabla} "
                    f"USING (tenant_id = current_user) WITH CHECK (tenant_id = current_user)"
                )
                # Auditoría: solo el rol dueño (NOLOGIN, lo usa el admin con SET ROLE) puede LEER todo
                await conn.execute(f"DROP POLICY IF EXISTS auditoria_owner ON {tabla}")
                await conn.execute(
                    f"CREATE POLICY auditoria_owner ON {tabla} FOR SELECT TO {OWNER_ROLE} USING (true)"
                )
                await conn.execute(f"REVOKE ALL ON {tabla} FROM PUBLIC")
        print("🔒 RLS forzada en: " + ", ".join(TABLAS_TENANT) + " (policy aislamiento_tenant)")
    finally:
        await conn.close()


# ============================================
# tenant — usuario de BD del agente + .env
# ============================================
def _escribir_env(env_file: Path, valores: dict[str, str]) -> None:
    """Reemplaza (o añade) las claves en el .env sin tocar el resto de líneas."""
    lineas = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    pendientes = dict(valores)
    salida = []
    for linea in lineas:
        clave = linea.split("=", 1)[0].strip()
        if clave in pendientes:
            salida.append(f"{clave}={pendientes.pop(clave)}")
        else:
            salida.append(linea)
    if pendientes:
        salida.append("")
        salida.append("# Histórico de conversación (Cloud SQL multitenant · infra/cloud_sql_historico)")
        salida.extend(f"{k}={v}" for k, v in pendientes.items())
    env_file.write_text("\n".join(salida) + "\n", encoding="utf-8")


async def tenant(nombre: str, env_file: Path) -> None:
    nombre = _validar_identificador(nombre)
    password = secrets.token_urlsafe(32)
    conn = await _conectar(DB_NAME)
    try:
        existe = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", nombre)
        accion = "ALTER" if existe else "CREATE"
        # La contraseña va como literal escapado por Postgres (DDL no admite parámetros)
        literal = await conn.fetchval("SELECT quote_literal($1)", password)
        await conn.execute(
            f"{accion} ROLE {nombre} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
            f"NOBYPASSRLS PASSWORD {literal}"
        )
        await conn.execute(f'GRANT CONNECT ON DATABASE "{DB_NAME}" TO {nombre}')
        await conn.execute(f"GRANT USAGE ON SCHEMA public TO {nombre}")
        await conn.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(TABLAS_TENANT)} TO {nombre}")
        await conn.execute(f"GRANT SELECT ON {TABLA_METADATA} TO {nombre}")
        bypass = await conn.fetchval("SELECT rolbypassrls OR rolsuper FROM pg_roles WHERE rolname = $1", nombre)
        if bypass:
            raise SystemExit(f"❌ {nombre} puede saltarse la RLS: revisa el rol")
    finally:
        await conn.close()

    _escribir_env(env_file, {
        "DB_USER": nombre,
        "DB_PASSWORD": password,
        "DB_HOST": DB_HOST,
        "DB_PORT": str(DB_PORT),
        "DB_NAME": DB_NAME,
    })
    print(f"{'🔁' if existe else '🆕'} Tenant {nombre}: usuario {'con contraseña rotada' if existe else 'creado'}; "
          f"credenciales escritas en {env_file}")


# ============================================
# verificar — estado de RLS, roles y filas por tenant
# ============================================
async def verificar() -> None:
    conn = await _conectar(DB_NAME)
    try:
        filas = await conn.fetch(
            "SELECT relname, relrowsecurity, relforcerowsecurity, pg_get_userbyid(relowner) AS dueno "
            "FROM pg_class WHERE relname = ANY($1::text[]) AND relkind = 'r' ORDER BY relname",
            list(TABLAS_TENANT) + [TABLA_METADATA],
        )
        print("Tabla                  RLS   FORCE  Dueño")
        for f in filas:
            print(f"{f['relname']:<22} {str(f['relrowsecurity']):<5} {str(f['relforcerowsecurity']):<6} {f['dueno']}")
        roles = await conn.fetch(
            "SELECT r.rolname, r.rolbypassrls, r.rolsuper FROM pg_roles r "
            "WHERE has_table_privilege(r.oid, 'public.sessions', 'INSERT') AND r.rolname <> $1 "
            "AND r.rolcanlogin AND r.rolname NOT LIKE 'cloudsql%' AND r.rolname <> $2 ORDER BY 1",
            OWNER_ROLE, ADMIN_USER,
        )
        print("\nTenants (usuarios con acceso): " + (", ".join(
            f"{r['rolname']}{' ⚠️ BYPASSRLS' if r['rolbypassrls'] or r['rolsuper'] else ''}" for r in roles) or "—"))
        async with conn.transaction():
            await conn.execute(f"SET LOCAL ROLE {OWNER_ROLE}")
            conteo = await conn.fetch(
                "SELECT tenant_id, count(*) AS sesiones FROM sessions GROUP BY 1 ORDER BY 1"
            )
        print("Sesiones por tenant: " + (", ".join(f"{c['tenant_id']}={c['sesiones']}" for c in conteo) or "—"))
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Histórico multitenant de ADK en Cloud SQL")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="Crea base, rol dueño, tablas de ADK y RLS")
    p_t = sub.add_parser("tenant", help="Crea/rota el usuario de un agente y escribe su .env")
    p_t.add_argument("nombre")
    p_t.add_argument("--env-file", required=True, type=Path)
    sub.add_parser("verificar", help="Muestra RLS, tenants y sesiones por tenant")
    args = parser.parse_args()

    if args.cmd == "init":
        asyncio.run(init())
    elif args.cmd == "tenant":
        asyncio.run(tenant(args.nombre, args.env_file))
    else:
        asyncio.run(verificar())


if __name__ == "__main__":
    main()
