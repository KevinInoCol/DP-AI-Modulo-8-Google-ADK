# Histórico de conversación multitenant (Cloud SQL · Postgres 18)

Una sola base para el histórico de **todos** los agentes de `adk_apps/`, aislada por tenant con Row Level Security.

| | |
|---|---|
| Instancia | `datapath-kevin-inofuente:us-central1:adk-historico` |
| Configuración | Postgres 18 · `db-f1-micro` · Enterprise · zonal · HDD 10 GB sin autoincremento · sin backups |
| Base | `adk_historico` (esquema `public`) |
| Tenants | `agente_basico`, `tramibot` |

## Modelo

ADK (`DatabaseSessionService`) usa 5 tablas:

| Tabla | RLS | Contenido |
|---|---|---|
| `sessions` | sí | una fila por conversación (`app_name`, `user_id`, `id`) |
| `events` | sí | mensajes, llamadas a tools y respuestas |
| `app_states` | sí | estado `app:*` de cada App |
| `user_states` | sí | estado `user:*` por usuario |
| `adk_internal_metadata` | no | una fila global con la versión del esquema |

- Cada agente se conecta con **su propio usuario de Postgres, llamado igual que el tenant**.
- La columna `tenant_id` toma por defecto `current_user`, y la policy `aislamiento_tenant` exige `tenant_id = current_user` para leer y escribir. ADK no sabe nada de tenants y el código del agente no puede hacerse pasar por otro.
- Las tablas son de `adk_owner` (sin login), con `FORCE ROW LEVEL SECURITY`. Los usuarios de los agentes no son dueños, no pueden saltarse la RLS (`NOBYPASSRLS`) y no pueden crear tablas.
- Dentro de un tenant, cada conversación se identifica por `app_name` + `user_id` + `id` de sesión. TramiBot usa dos apps (`tramibot_chatwoot` y `tramibot_web`) y el agente básico usa `agente_basico`.

## Uso

```bash
# 1. Proxy local (se autentica con tu login de gcloud / ADC)
cloud-sql-proxy datapath-kevin-inofuente:us-central1:adk-historico --port 5432

# 2. Una vez: base, rol dueño, tablas de ADK y RLS (idempotente)
python historico_multitenant.py init

# 3. Por cada agente: crea su usuario (o rota la contraseña) y escribe DB_* en su .env
python historico_multitenant.py tenant agente_basico --env-file ../../adk_apps/agente_basico/.env
python historico_multitenant.py tenant tramibot --env-file ../../adk_apps/adk_agenteia_tramibot_seguridad_model_armor/.env

# 4. Estado: RLS, tenants y sesiones por tenant
python historico_multitenant.py verificar
```

La contraseña del admin (`postgres`) vive en `.env` (está en el `.gitignore`; la plantilla es `.env.example`). Los agentes nunca la usan.

**Agente nuevo:** ejecuta el paso 3 con su tenant y su `.env`. Su `chat_history/session_store.py` es el mismo que el de `agente_basico`, cambiando el nombre del tenant.

## Despliegue en Cloud Run

- `--add-cloudsql-instances datapath-kevin-inofuente:us-central1:adk-historico`
- `DB_HOST=/cloudsql/datapath-kevin-inofuente:us-central1:adk-historico`, y `DB_USER` / `DB_PASSWORD` del tenant (mejor desde Secret Manager).
- La cuenta de servicio del servicio necesita `roles/cloudsql.client`.

## Costos

`db-f1-micro` es un núcleo compartido sin SLA. Si no lo usas, puedes apagar la instancia: `gcloud sql instances patch adk-historico --activation-policy=NEVER` (y `ALWAYS` para encenderla). Mientras está apagada solo pagas el disco y la IP.
