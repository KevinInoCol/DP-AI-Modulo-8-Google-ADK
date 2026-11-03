"""
Agente IA Completo con Google ADK: Base de Conocimiento + Histórico + Langfuse + Model Armor
- Modelo:          Gemini 3.5 Flash (API Key o Vertex AI, según GEMINI_AUTH_MODE)
- Tool 1:          Base de Conocimiento (RAG con Qdrant)
- Tool 2:          Fecha y hora actual
- Tool 3:          Transferir a humano (solo en el canal Chatwoot)
- Histórico:       Sesiones de ADK en PostgreSQL (DatabaseSessionService)
- Observabilidad:  Langfuse vía OpenTelemetry (trazas, tokens, latencia) + LLM-as-a-Judge
- Seguridad:       ModelArmorPlugin (plugin oficial de ADK) revisa la entrada y la salida

Es el mismo TramiBot de la versión LangChain, reescrito con las piezas de ADK:

  LangChain                              Google ADK
  ─────────────────────────────────────  ──────────────────────────────────────────
  create_agent(model, tools, prompt)  →  LlmAgent(model, tools, instruction)
  agente.invoke() por turno           →  Runner.run_async() (eventos)
  guardrail propio antes/después      →  ModelArmorPlugin registrado en el App
  PostgresChatMessageHistory a mano   →  DatabaseSessionService (el Runner guarda solo)
  CallbackHandler de Langfuse         →  GoogleADKInstrumentor (OpenTelemetry)
  tool con closure (handoff)          →  tool con ToolContext + estado de la sesión

Docs seguidas: https://adk.dev/agents/llm-agents/ · https://adk.dev/apps/
https://adk.dev/runtime/event-loop/ · https://adk.dev/integrations/model-armor/
https://adk.dev/integrations/langfuse/ · https://adk.dev/sessions/session/

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

import os
import uuid
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())


# Config del modelo (desacoplada del código) + selección API Key / Vertex AI.
# Va primero: fija las variables que leen ADK y google-genai antes de crear nada.
from .model_config import load_model_config, configurar_autenticacion_gemini

MODO_GEMINI = configurar_autenticacion_gemini()

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.apps import App
from google.adk.runners import Runner
from google.genai import types

# LANGFUSE ▶ decorador @observe y propagación de atributos (trace name, tags…)
from langfuse import observe, propagate_attributes

# LANGFUSE ▶ Cliente singleton + instrumentación OpenTelemetry de ADK
from .observability.langfuse_setup import langfuse_client

# Tools (funciones Python; ADK las envuelve en FunctionTool)
from .tools.Base_de_conocimiento import buscar_tramites
from .tools.Hora_y_fecha import obtener_fecha_hora
from .tools.Transferir_humano import transferir_a_humano
# buscar_internet desactivada para el agente municipal (ver TOOLS_BASE más abajo).
# from tools.Busqueda_internet import buscar_internet

# Model Armor: plugin oficial de ADK (entrada + salida)
from .guardrails import (
    crear_plugin_model_armor,
    evento_bloqueado,
    quitar_turnos_bloqueados,
    MENSAJE_ENTRADA_BLOQUEADA,
)

# Evaluador LLM-as-a-Judge (módulo evaluation/)
from .evaluation.llm_judge import evaluar_con_llm_judge

# Histórico: SessionService de ADK sobre PostgreSQL (chat_history/)
from .chat_history import preparar_esquema, session_service

# System prompt desde YAML (prompt/)
from .prompt import load_system_prompt

# ============================================
# 1. CONFIGURACIÓN
# ============================================
_model_cfg = load_model_config()
MODELO = _model_cfg["llm"]["model"]
AGENT_TIMEZONE = os.getenv("AGENT_TIMEZONE", "America/Lima")
PROMPT_SOURCE = os.getenv("PROMPT_SOURCE", "langfuse").strip().lower()
LANGFUSE_PROMPT_NAME = os.getenv("LANGFUSE_PROMPT_NAME", "Prompt-del-Agente-Tramites-Girardota")

# ============================================
# 2. LISTA DE TOOLS DISPONIBLES
# ============================================
TOOLS_BASE = [
    buscar_tramites,      # Base de conocimiento de trámites del Municipio de Girardota
    obtener_fecha_hora,   # Fecha y hora actual por zona horaria (plazos/días hábiles)
    # buscar_internet,    # Desactivada: el agente municipal responde solo desde el
                          # Manual oficial (evita alucinaciones de la web abierta).
]

# ============================================
# 3. SYSTEM PROMPT
# ============================================
# Opción A (por defecto, igual que la versión LangChain): Prompt Management de Langfuse.
#   Ventaja: cambias el prompt desde la UI sin tocar código.
# Opción B: PROMPT_SOURCE=yaml → prompt/system_prompt.yaml.
# Si Langfuse falla, se usa el YAML para que el agente no se quede sin instrucciones.
def _cargar_system_prompt() -> str:
    if PROMPT_SOURCE == "langfuse":
        try:
            lf_prompt = langfuse_client.get_prompt(LANGFUSE_PROMPT_NAME)
            print(f"📝 Prompt cargado desde Langfuse: {LANGFUSE_PROMPT_NAME} v{lf_prompt.version}")
            return lf_prompt.compile()
        except Exception as e:
            print(f"⚠️  No se pudo leer el prompt de Langfuse ({e}); uso prompt/system_prompt.yaml")
    prompt = load_system_prompt()
    print("📝 Prompt cargado desde YAML: prompt/system_prompt.yaml")
    return prompt


SYSTEM_PROMPT = _cargar_system_prompt()


def _contexto_fecha_hora() -> str:
    """Fecha y hora actual para inyectar en el system prompt (cada turno)."""
    try:
        tz = ZoneInfo(AGENT_TIMEZONE)
    except Exception:
        tz = ZoneInfo("America/Lima")
    now = datetime.now(tz)
    return now.strftime("%Y-%m-%d %H:%M:%S") + f" (zona {AGENT_TIMEZONE})"


# En la web y la consola no existe transferir_a_humano, pero el prompt la menciona:
# sin esta nota Gemini intenta llamarla y ADK responde "Tool not found".
NOTA_SIN_HANDOFF = (
    "\n\n---\nCANAL WEB: en este canal la herramienta transferir_a_humano NO está "
    "disponible. Si el ciudadano pide hablar con un funcionario o su caso excede lo "
    "informativo, indícale que puede comunicarse con la Alcaldía de Girardota por sus "
    "canales oficiales de atención o acudir presencialmente."
)


def crear_instruccion(con_handoff: bool):
    """
    Devuelve el InstructionProvider del agente: ADK lo llama en cada petición al modelo.

    Sirve para tres cosas:
      1. Inyectar la fecha/hora actual en cada turno (como en la versión LangChain).
      2. Añadir la nota del canal web cuando no hay transferir_a_humano.
      3. Al ser una función, ADK NO aplica el templating {variable} sobre el texto,
         así que el prompt puede contener llaves sin romperse.
    """

    def instruccion_tramibot(ctx: ReadonlyContext) -> str:
        return (
            SYSTEM_PROMPT
            + ("" if con_handoff else NOTA_SIN_HANDOFF)
            + "\n\n---\nFECHA Y HORA ACTUAL (referencia para este turno): "
            + _contexto_fecha_hora()
        )

    return instruccion_tramibot


# ============================================
# 4. AGENTE + APP (con Model Armor) + RUNNER
# ============================================
def crear_agente(con_handoff: bool) -> LlmAgent:
    """
    Crea TramiBot. Hay dos variantes porque transferir_a_humano solo tiene
    sentido en Chatwoot (etiqueta la conversación con "ia-off"); la web y la
    consola no la ofrecen, igual que en la versión LangChain.
    """
    tools = TOOLS_BASE + ([transferir_a_humano] if con_handoff else [])
    return LlmAgent(
        name="tramibot",
        model=MODELO,
        description="Asistente virtual de trámites del Municipio de Girardota (Colombia).",
        instruction=crear_instruccion(con_handoff),
        tools=tools,
        generate_content_config=types.GenerateContentConfig(
            temperature=_model_cfg["llm"]["temperature"],
        ),
        # No reenviar a Gemini turnos que Model Armor ya bloqueó (ver guardrails/)
        before_model_callback=quitar_turnos_bloqueados,
    )


def crear_app(nombre: str, con_handoff: bool) -> App:
    """App = agente raíz + plugins. Model Armor se aplica a todo lo que corra el App."""
    return App(
        name=nombre,
        root_agent=crear_agente(con_handoff),
        plugins=[crear_plugin_model_armor()],
    )


app_chatwoot = crear_app("tramibot_chatwoot", con_handoff=True)
app_web = crear_app("tramibot_web", con_handoff=False)

# El Runner guarda cada evento (mensaje, llamada a tool, respuesta) en Postgres.
# auto_create_session: la primera vez que llega un session_id, crea la sesión.
_runners = {
    "chatwoot": Runner(app=app_chatwoot, session_service=session_service, auto_create_session=True),
    "web": Runner(app=app_web, session_service=session_service, auto_create_session=True),
}


def runner_para(canal: str) -> Runner:
    """Chatwoot usa el agente con handoff; web, consola y pruebas, el que no lo tiene."""
    return _runners["chatwoot"] if canal == "chatwoot" else _runners["web"]


def _texto(content) -> str:
    """Une las partes de texto visibles (sin 'thoughts') de un Content."""
    if not content or not content.parts:
        return ""
    return "".join(
        p.text for p in content.parts if getattr(p, "text", None) and not getattr(p, "thought", False)
    ).strip()


# ============================================
# 5. FUNCIÓN DE CHAT CON AGENTE + TOOLS + LANGFUSE
# ============================================
# LANGFUSE ▶ @observe() crea el trace raíz del turno; los spans que emite ADK
#             (agente, llamadas a Gemini, tools) quedan anidados debajo.
@observe()
async def chat_con_agente(
    mensaje_usuario: str,
    session_id: str,
    canal: str = "chatwoot",
    user_id: str | None = None,
    estado: dict | None = None,
) -> dict:
    """
    Ejecuta un turno del agente.

    Args:
        mensaje_usuario: Mensaje del usuario.
        session_id:      UUID de la sesión/conversación (para el historial).
        canal:           "chatwoot", "web", "consola"… Elige el agente y es tag en Langfuse.
        user_id:         Usuario de la sesión en ADK (por defecto, el canal).
        estado:          Claves que se escriben en el estado de la sesión antes del
                         turno (p. ej. los IDs de Chatwoot que lee transferir_a_humano).

    Returns:
        {"respuesta": str, "bloqueado": bool, "motivo": "" | "entrada" | "salida"}
    """
    await preparar_esquema()
    runner = runner_para(canal)
    user_id = user_id or canal
    nuevo = types.Content(role="user", parts=[types.Part(text=mensaje_usuario)])

    respuesta, bloqueado = "", False

    # LANGFUSE v4 ▶ propagate_attributes() fija trace name, sesión, usuario y tags
    #               en todas las observaciones del turno (incluidos los spans de ADK).
    with propagate_attributes(
        trace_name="tramibot-turno",
        session_id=session_id,
        user_id=user_id,
        tags=["produccion", canal, "tramibot", "adk", "model-armor"],
        metadata={"modelo": MODELO, "auth": MODO_GEMINI},
    ):
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=nuevo,
            state_delta=estado,
        ):
            if event.is_final_response():
                respuesta = _texto(event.content) or respuesta
                bloqueado = bloqueado or evento_bloqueado(event)
            elif event.error_message:
                print(f"   ⚠️  Evento con error: {event.error_code} {event.error_message}")

    if not respuesta:
        respuesta = "Disculpa, no pude generar una respuesta. ¿Puedes reformular tu consulta?"

    motivo = ""
    if bloqueado:
        motivo = "entrada" if respuesta == MENSAJE_ENTRADA_BLOQUEADA else "salida"
        print(f"🚨 [MODEL ARMOR] Turno bloqueado en la {motivo}")
        with propagate_attributes(tags=["guardrail", "bloqueado", f"bloqueo-{motivo}"]):
            pass

    # LANGFUSE v4 ▶ input/output del turno completo en el trace raíz
    langfuse_client.set_current_trace_io(
        input={"mensaje_usuario": mensaje_usuario},
        output={"respuesta": respuesta, "bloqueado": bloqueado, "motivo": motivo},
    )

    # JUDGE ▶ Evaluar el turno (no se evalúa un mensaje bloqueado en la entrada:
    #          el agente ni siquiera llegó a responder).
    trace_id_actual = langfuse_client.get_current_trace_id()
    if trace_id_actual and motivo != "entrada":
        await evaluar_con_llm_judge(mensaje_usuario, respuesta, trace_id_actual)

    return {"respuesta": respuesta, "bloqueado": bloqueado, "motivo": motivo}


# ============================================
# 6. LOOP DE CONVERSACIÓN (CONSOLA)
# ============================================
async def main():
    print("=" * 60)
    print("🤖 TramiBot (Google ADK) - Agente de Trámites del Municipio de Girardota")
    print("=" * 60)
    print(f"🧠 Modelo: {MODELO} ({MODO_GEMINI})")
    print("🔧 Tools disponibles:")
    for t in TOOLS_BASE:
        print(f"   - {t.__name__}")
    print("💾 Historial: sesiones de ADK en PostgreSQL")

    print("\nOpciones de sesión:")
    print("  1. Nueva conversación")
    print("  2. Continuar sesión existente (pegar UUID)")

    opcion = (await asyncio.to_thread(input, "\nElige (1/2): ")).strip()

    session_id = str(uuid.uuid4())
    if opcion == "2":
        pegado = (await asyncio.to_thread(input, "Pega el UUID de la sesión: ")).strip()
        try:
            session_id = str(uuid.UUID(pegado))
        except ValueError:
            print("⚠️ UUID inválido. Creando nueva sesión...")

    print(f"\n📝 Session ID: {session_id}")
    print("   (Guarda este ID para continuar después)")
    print("Escribe 'salir' para terminar.\n")

    while True:
        usuario = (await asyncio.to_thread(input, "Tú: ")).strip()

        if usuario.lower() in ["salir", "exit", "quit"]:
            print(f"\n💾 Tu sesión está guardada.\n   UUID: {session_id}")
            # LANGFUSE ▶ flush() envía los eventos pendientes antes de cerrar el proceso
            langfuse_client.flush()
            print("👋 ¡Hasta luego!")
            break

        if not usuario:
            continue

        try:
            resultado = await chat_con_agente(usuario, session_id, canal="consola", user_id="web")
            etiqueta = " [bloqueado por Model Armor]" if resultado["bloqueado"] else ""
            print(f"\n🤖 TramiBot{etiqueta}: {resultado['respuesta']}\n")
        except Exception as e:
            print(f"\n❌ Error: {e}\n")


if __name__ == "__main__":
    asyncio.run(main())
