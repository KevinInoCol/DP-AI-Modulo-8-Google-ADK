"""
Agente básico con Google ADK: prompt + model_config + histórico de conversación.

- Modelo:      Gemini (API Key o Vertex AI, según GEMINI_AUTH_MODE)   → model_config/
- Prompt:      prompt/system_prompt.yaml (+ fecha/hora en cada turno)  → prompt/
- Histórico:   sesiones de ADK en Cloud SQL multitenant (RLS)           → chat_history/

Sin tools, guardrails ni observabilidad: es la base mínima para empezar.

    cd Modulo-8-Sesion-1-Google-ADK
    adk web adk_apps                      # elige "agente_basico" (sesiones en memoria de adk web)
    cd adk_apps && python -m agente_basico.agent   # consola con historial en Postgres

Docs: https://adk.dev/agents/llm-agents/ · https://adk.dev/apps/
https://adk.dev/sessions/session/

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

import asyncio
import os
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

# Va primero: fija las variables que leen ADK y google-genai antes de crear nada.
from .model_config import load_model_config, configurar_autenticacion_gemini

MODO_GEMINI = configurar_autenticacion_gemini()

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.apps import App
from google.adk.runners import Runner
from google.genai import types

from .chat_history import obtener_historial, session_service
from .prompt import load_system_prompt

# ============================================
# 1. CONFIGURACIÓN
# ============================================
APP_NAME = "agente_basico"  # debe coincidir con el nombre de la carpeta
_model_cfg = load_model_config()
MODELO = _model_cfg["llm"]["model"]
AGENT_TIMEZONE = os.getenv("AGENT_TIMEZONE", "America/Lima")
SYSTEM_PROMPT = load_system_prompt()


def _thinking_config() -> types.ThinkingConfig | None:
    """ThinkingConfig de Gemini 3+ a partir de model.yaml (None = valor por defecto del modelo)."""
    nivel = _model_cfg["llm"].get("thinking_level")
    return types.ThinkingConfig(thinking_level=nivel.upper()) if nivel else None


# ============================================
# 2. INSTRUCCIÓN (InstructionProvider)
# ============================================
def instruccion(ctx: ReadonlyContext) -> str:
    """
    ADK la llama en cada petición al modelo: añade la fecha/hora del turno.
    Al ser una función, ADK no aplica el templating {variable} sobre el prompt.
    """
    try:
        tz = ZoneInfo(AGENT_TIMEZONE)
    except Exception:
        tz = ZoneInfo("America/Lima")
    ahora = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    return f"{SYSTEM_PROMPT}\n\n---\nFECHA Y HORA ACTUAL: {ahora} (zona {AGENT_TIMEZONE})"


# ============================================
# 3. AGENTE + APP + RUNNER
# ============================================
root_agent = LlmAgent(
    name="agente_basico",
    model=MODELO,
    description="Asistente conversacional básico con memoria de la conversación.",
    instruction=instruccion,
    generate_content_config=types.GenerateContentConfig(
        temperature=_model_cfg["llm"]["temperature"],
        # Nivel de razonamiento (model_config/model.yaml → thinking_level)
        thinking_config=_thinking_config(),
    ),
)

app = App(name=APP_NAME, root_agent=root_agent)

# El Runner lee el historial de la sesión antes de llamar a Gemini y guarda
# cada evento nuevo en Postgres. auto_create_session crea la sesión la primera vez.
runner = Runner(app=app, session_service=session_service, auto_create_session=True)


def _texto(content) -> str:
    """Une las partes de texto visibles (sin 'thoughts') de un Content."""
    if not content or not content.parts:
        return ""
    return "".join(
        p.text for p in content.parts if getattr(p, "text", None) and not getattr(p, "thought", False)
    ).strip()


async def chat_con_agente(mensaje_usuario: str, session_id: str, user_id: str = "consola") -> str:
    """Ejecuta un turno del agente y devuelve el texto de la respuesta final."""
    nuevo = types.Content(role="user", parts=[types.Part(text=mensaje_usuario)])

    respuesta = ""
    async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=nuevo):
        if event.is_final_response():
            respuesta = _texto(event.content) or respuesta
        elif event.error_message:
            print(f"   ⚠️  Evento con error: {event.error_code} {event.error_message}")

    return respuesta or "Disculpa, no pude generar una respuesta. ¿Puedes reformular?"


# ============================================
# 4. CONSOLA
# ============================================
async def main():
    print("=" * 60)
    print("🤖 Agente básico (Google ADK)")
    print("=" * 60)
    print(f"🧠 Modelo: {MODELO} ({MODO_GEMINI})")
    print("💾 Historial: Cloud SQL multitenant (tenant agente_basico)")
    print("\n  1. Nueva conversación\n  2. Continuar sesión existente (pegar UUID)")

    opcion = (await asyncio.to_thread(input, "\nElige (1/2): ")).strip()
    session_id = str(uuid.uuid4())
    if opcion == "2":
        pegado = (await asyncio.to_thread(input, "Pega el UUID de la sesión: ")).strip()
        try:
            session_id = str(uuid.UUID(pegado))
            historial = await obtener_historial(APP_NAME, "consola", session_id)
            print(f"\n📜 Historial ({len(historial)} mensajes):")
            for m in historial:
                print(f"   {'Tú' if m['rol'] == 'user' else '🤖'}: {m['texto']}")
        except ValueError:
            print("⚠️ UUID inválido. Creando nueva sesión...")

    print(f"\n📝 Session ID: {session_id}\nEscribe 'salir' para terminar.\n")

    while True:
        usuario = (await asyncio.to_thread(input, "Tú: ")).strip()
        if usuario.lower() in ("salir", "exit", "quit"):
            print(f"\n💾 Sesión guardada. UUID: {session_id}\n👋 ¡Hasta luego!")
            break
        if not usuario:
            continue
        try:
            print(f"\n🤖: {await chat_con_agente(usuario, session_id)}\n")
        except Exception as e:
            print(f"\n❌ Error: {e}\n")


if __name__ == "__main__":
    asyncio.run(main())
