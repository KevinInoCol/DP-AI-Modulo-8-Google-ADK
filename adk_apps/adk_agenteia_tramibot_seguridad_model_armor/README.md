# TramiBot con Google ADK · Agente IA MultiTool + Seguridad (Model Armor)

El mismo **TramiBot** (trámites del Municipio de Girardota) de `LangChain-AgenteIA-MultiTool-Seguridad-Model-Armor`, reconstruido con **Google Agent Development Kit (ADK 2.x)** y **Gemini 3.5 Flash**.

Autor: Ing. Kevin Inofuente Colque · DataPath

---

## De LangChain a ADK: qué cambió

| Pieza | LangChain | Google ADK (este proyecto) |
|---|---|---|
| Modelo | GPT-4.1 (`init_chat_model`) | **Gemini 3.5 Flash**, vía API Key **o** Vertex AI (`GEMINI_AUTH_MODE`) |
| Agente | `create_agent(...)` por turno | `LlmAgent` fijo + `App` + `Runner.run_async()` |
| Instrucciones | `system_prompt` + fecha concatenada | *InstructionProvider* (`crear_instruccion`): prompt + fecha en cada petición |
| Tools | `@tool` de LangChain | Funciones Python (async) con docstring → `FunctionTool` |
| Handoff | Tool fabricada con closure (`contact_id`, `conversation_id`) | Tool con `ToolContext`; el webhook pasa los IDs en el estado de la sesión (`state_delta`) |
| Seguridad | Módulo propio que llama a Model Armor | **`ModelArmorPlugin` oficial de ADK** registrado en el `App` |
| Memoria | `PostgresChatMessageHistory` cargado a mano | `DatabaseSessionService` (Postgres); el Runner guarda cada evento |
| Observabilidad | `CallbackHandler` de Langfuse | `GoogleADKInstrumentor` (OpenTelemetry) + `@observe` + `propagate_attributes` |
| LLM-as-a-Judge | GPT-4.1 | Gemini (`google-genai`, respeta el mismo modo de autenticación) |
| RAG | `QdrantVectorStore` | `qdrant-client` + embeddings OpenAI ada-002 (misma colección, sin reingestar) |

Docs oficiales seguidas: [LLM agents](https://adk.dev/agents/llm-agents/) · [App](https://adk.dev/apps/) · [Event loop](https://adk.dev/runtime/event-loop/) · [Function tools](https://adk.dev/tools-custom/function-tools/) · [Sessions](https://adk.dev/sessions/session/) · [Model Armor plugin](https://adk.dev/integrations/model-armor/) · [Langfuse](https://adk.dev/integrations/langfuse/) · [Google Cloud](https://adk.dev/get-started/google-cloud/)

---

## Estructura

ADK trata cada subcarpeta de `adk_apps/` como un agente (nombre en snake_case, con `agent.py`). TramiBot es **autocontenido**: todo su código vive en `adk_apps/adk_agenteia_tramibot_seguridad_model_armor/`, así se despliega solo y pueden convivir otros agentes al lado.

```
Modulo-8-Sesion-1-Google-ADK/
├── LangChain-AgenteIA-MultiTool-Seguridad-Model-Armor/   # versión de referencia
├── Frontend_React/                 # (cuando lo traigas) lo sirve main_frontend_react.py
├── .claude/skills/                 # symlinks a las skills globales
└── adk_apps/
    └── adk_agenteia_tramibot_seguridad_model_armor/                   # ← el agente completo (paquete Python)
        ├── __init__.py             # `from . import agent` (lo exige ADK)
        ├── agent.py                # app / root_agent para `adk web` y `adk run`
        ├── agente_sec_langfuse.py  # Núcleo: LlmAgent + App (Model Armor) + Runner + chat_con_agente() + consola
        ├── main_chatwoot_ia_off.py # Webhook de Chatwoot (ia-off, buffer Redis, handoff) + POST /chat
        ├── main_frontend_react.py  # API para el Frontend React (/api/chat, /api/historial, /api/health)
        ├── model_config/           # model.yaml (Gemini 3.5 Flash) + selector API Key / Vertex
        ├── prompt/                 # system_prompt.yaml (alternativa al de Langfuse)
        ├── tools/                  # buscar_tramites, obtener_fecha_hora, transferir_a_humano, buscar_internet (off)
        ├── guardrails/             # ModelArmorPlugin + filtro de turnos bloqueados
        ├── chat_history/           # DatabaseSessionService sobre Postgres (esquema DB_SCHEMA)
        ├── observability/          # Langfuse + instrumentación OTel de ADK
        ├── evaluation/             # LLM-as-a-Judge con Gemini → scores en Langfuse
        ├── message_buffer/         # Debounce con Redis
        ├── rag/                    # Pipeline de ingesta a Qdrant + documents/
        ├── requirements.txt
        └── .env / .env.example
```

Los imports internos son **relativos** (`from .tools import ...`). Así, si mañana agregas `adk_apps/otro_agente/` con su propia carpeta `tools/`, `adk web` no confunde un `tools` con otro al cargarlos en el mismo proceso. Por lo mismo, los servidores se ejecutan como módulos (`python -m adk_agenteia_tramibot_seguridad_model_armor.…`) desde `adk_apps/`.

---

## Configuración

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r adk_apps/adk_agenteia_tramibot_seguridad_model_armor/requirements.txt
cp adk_apps/adk_agenteia_tramibot_seguridad_model_armor/.env.example adk_apps/adk_agenteia_tramibot_seguridad_model_armor/.env   # si aún no tienes .env
```

### Elegir cómo se conecta Gemini (`GEMINI_AUTH_MODE`)

```bash
# Opción 1 — API Key (Google AI Studio)
GEMINI_AUTH_MODE=api_key
GOOGLE_API_KEY=...            # https://aistudio.google.com/app/apikey

# Opción 2 — Vertex AI
GEMINI_AUTH_MODE=vertex
GOOGLE_CLOUD_PROJECT=tu-proyecto
GOOGLE_CLOUD_LOCATION=global  # los Gemini más nuevos suelen publicarse en "global"
```

En modo `vertex` las credenciales son Application Default Credentials (ADC). **No se usan llaves JSON de cuentas de servicio**: en local se inicia sesión con `gcloud auth application-default login` (y `gcloud auth application-default set-quota-project <PROYECTO>`), y en Cloud Run se usa la cuenta de servicio del servicio. Tu usuario o esa SA necesitan el rol **Vertex AI User** (`roles/aiplatform.user`). Internamente se fijan `GOOGLE_GENAI_USE_ENTERPRISE` / `GOOGLE_GENAI_USE_VERTEXAI`, que son las variables que leen ADK y google-genai.

### Model Armor

Usa la misma plantilla de la versión LangChain (`MODEL_ARMOR_PROJECT`, `MODEL_ARMOR_LOCATION`, `MODEL_ARMOR_TEMPLATE`). Las credenciales también son ADC: tu usuario (local) o la cuenta de servicio de Cloud Run necesitan **Model Armor User** (`roles/modelarmor.user`). Como el plugin es fail-closed, sin ADC bloquearía todos los turnos, así que `crear_plugin_model_armor()` comprueba las credenciales al arrancar. Si `GOOGLE_APPLICATION_CREDENTIALS` sigue en el `.env`, se ignora con un aviso.

### Memoria (Postgres)

ADK crea sus tablas (`sessions`, `events`, `app_states`, `user_states`) en el esquema `DB_SCHEMA` (por defecto `tramibot_adk`), que se crea solo. Con Supabase usa el **Session pooler (puerto 5432)**; el Transaction pooler (6543) no admite las sentencias preparadas de asyncpg.

---

## Ejecutar

Todos los comandos se lanzan desde `adk_apps/` (salvo `adk web`, desde la carpeta del módulo):

```bash
cd adk_apps

# Consola
python -m adk_agenteia_tramibot_seguridad_model_armor.agente_sec_langfuse

# Webhook de Chatwoot (puerto 8000)
python -m adk_agenteia_tramibot_seguridad_model_armor.main_chatwoot_ia_off

# API para el Frontend React (puerto 8001; el front en Modulo-8-Sesion-1-Google-ADK/Frontend_React con npm run dev)
python -m adk_agenteia_tramibot_seguridad_model_armor.main_frontend_react

# Ingesta de documentos a Qdrant
python adk_agenteia_tramibot_seguridad_model_armor/rag/pipeline/run_ingesta.py --dir adk_agenteia_tramibot_seguridad_model_armor/rag/documents

# Interfaz de desarrollo de ADK (desde la carpeta del módulo)
cd .. && adk web adk_apps      # elige "adk_agenteia_tramibot_seguridad_model_armor"
```

| Método | Ruta | Uso |
|---|---|---|
| `POST` | `/webhook` | Eventos de Chatwoot (puerto 8000) |
| `POST` | `/chat` | Pruebas tipo Red Turing / DeepTeam: `{"mensaje"}` → `{"respuesta","session_id","bloqueado"}` |
| `POST` | `/api/chat` | Frontend: `{"mensaje","session_id?"}` → `{"respuesta","session_id","bloqueado"}` (puerto 8001) |
| `GET` | `/api/historial/{session_id}` | Frontend: conversación guardada en la sesión de ADK |

---

## Notas importantes

- **Mensajes de bloqueo.** El plugin oficial tiene **un** mensaje para la entrada y **otro** para la salida (en `guardrails/model_armor_guardrail.py`), no uno por filtro como el guardrail propio de LangChain. Un bloqueo se reconoce por `custom_metadata['model_armor_blocked']` en el evento.
- **Turnos bloqueados fuera del contexto.** El Runner guarda el mensaje del usuario antes de que el plugin lo revise, y el plugin solo revisa el último mensaje. Por eso `quitar_turnos_bloqueados` (un `before_model_callback`) quita del contexto los pares bloqueados: un prompt injection ya rechazado no viaja a Gemini en el siguiente turno.
- **Dos variantes del agente.** `tramibot_chatwoot` tiene `transferir_a_humano`; `tramibot_web` (web, consola, `/chat`, `adk web`) no la tiene y recibe una nota en las instrucciones para no intentar llamarla.
- **Embeddings.** La colección de Qdrant se creó con OpenAI `text-embedding-ada-002`, así que el RAG sigue necesitando `OPENAI_API_KEY`. Pasar a embeddings de Gemini implica volver a ingestar en una colección nueva.
- **Clave del texto en Qdrant.** La tool acepta `text` (lo que escribe `rag/pipeline/`) y `page_content` (colecciones cargadas con LangChain, como la actual).
- **`adk web`** usa su propio SessionService en memoria, no el Postgres del proyecto.
- **Un proceso por servidor.** El pool de Postgres y los clientes async quedan ligados al event loop del proceso; el webhook y la API web corren cada uno en su propio proceso.
