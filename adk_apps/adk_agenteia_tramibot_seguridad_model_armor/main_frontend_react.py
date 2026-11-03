"""
Integración del Agente IA (Google ADK) con un Frontend web (React + Vite)
API REST para que la interfaz web (carpeta Frontend_React/, al lado de la carpeta
del proyecto) converse con TramiBot.

Mismo contrato que la versión LangChain, así el frontend no cambia:

  POST /api/chat                   {"mensaje": "...", "session_id": "uuid opcional"}
                                   → {"respuesta", "session_id", "bloqueado"}
  GET  /api/historial/{session_id} → {"session_id", "mensajes": [{rol, texto}]}
  GET  /api/health

Usa el mismo chat_con_agente que el webhook de Chatwoot (Model Armor en entrada y
salida + RAG + memoria + Langfuse), con el agente SIN transferir_a_humano.

"bloqueado" ya no se deduce comparando textos: el plugin de Model Armor marca el
evento con custom_metadata['model_armor_blocked'] y chat_con_agente lo devuelve.

El historial se lee de la sesión de ADK (Postgres): solo los textos del
ciudadano y las respuestas finales del agente (sin llamadas a tools).

En desarrollo el frontend corre en Vite (puerto 5173) y llega a /api por proxy.
En producción (npm run build) este mismo servidor sirve ../Frontend_React/dist/
(o la ruta de FRONTEND_DIST_DIR).

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

import os
import uuid
import logging

from dotenv import load_dotenv, find_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

# Mostrar logs INFO (Model Armor, buffer…) en consola
logging.basicConfig(level=logging.INFO, format="%(message)s")

load_dotenv(find_dotenv())


from .agente_sec_langfuse import chat_con_agente, runner_para, MODELO, _texto
from .chat_history import preparar_esquema, session_service

# ============================================
# CONFIGURACIÓN
# ============================================
FRONTEND_PORT = int(os.getenv("FRONTEND_API_PORT", "8001"))
# Orígenes permitidos por CORS (solo hace falta si el front no usa el proxy de Vite)
FRONTEND_ORIGINS = [
    o.strip()
    for o in os.getenv("FRONTEND_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if o.strip()
]

CANAL = "web"
USER_ID = "web"  # la web no tiene login: cada pestaña se distingue por su session_id
APP_NAME = runner_para(CANAL).app_name
# El frontend vive al lado de adk_apps/ (en la carpeta del módulo):
#   <módulo>/Frontend_React/dist   (este archivo está en <módulo>/adk_apps/<agente>/)
_MODULO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
DIST_DIR = os.getenv("FRONTEND_DIST_DIR", os.path.join(_MODULO, "Frontend_React", "dist"))

# ============================================
# APP
# ============================================
app = FastAPI(title="TramiBot (Google ADK) - API para Frontend React")

app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class ChatRequest(BaseModel):
    mensaje: str
    session_id: str | None = None


def _session_id_valido(session_id: str | None) -> str:
    """Devuelve el UUID recibido si es válido; si no, abre una sesión nueva."""
    try:
        return str(uuid.UUID(str(session_id or "").strip()))
    except ValueError:
        return str(uuid.uuid4())


@app.post("/api/chat")
async def chat(req: ChatRequest):
    mensaje = req.mensaje.strip()
    if not mensaje:
        raise HTTPException(status_code=400, detail="El mensaje está vacío.")

    session_id = _session_id_valido(req.session_id)
    print(f"💬 [WEB] {session_id[:8]} → {mensaje[:80]}")

    try:
        resultado = await chat_con_agente(mensaje, session_id, canal=CANAL, user_id=USER_ID)
    except Exception as e:
        print(f"   ❌ Error al procesar: {e}")
        raise HTTPException(
            status_code=500,
            detail="Tuve un problema al procesar tu consulta. Intenta de nuevo en un momento.",
        )

    return {
        "respuesta": resultado["respuesta"],
        "session_id": session_id,
        "bloqueado": resultado["bloqueado"],
    }


@app.get("/api/historial/{session_id}")
async def historial(session_id: str):
    """Mensajes guardados en la sesión de ADK para que la web recupere la conversación."""
    try:
        uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="session_id no es un UUID válido.")

    await preparar_esquema()
    session = await session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session_id
    )

    mensajes = []
    for event in (session.events if session else []):
        texto = _texto(event.content)
        if not texto:
            continue  # llamadas y respuestas de tools
        if event.author == "user":
            mensajes.append({"rol": "usuario", "texto": texto})
        elif event.is_final_response():
            mensajes.append({"rol": "agente", "texto": texto})
    return {"session_id": session_id, "mensajes": mensajes}


@app.get("/api/health")
def health_check():
    return {"status": "healthy", "agent": "TramiBot", "framework": "google-adk", "canal": CANAL}


# En producción, el build de React se sirve desde la raíz (después de las rutas /api)
if os.path.isdir(DIST_DIR):
    app.mount("/", StaticFiles(directory=DIST_DIR, html=True), name="frontend")


# ============================================
# MAIN
# ============================================
if __name__ == "__main__":
    print()
    print("=" * 60)
    print("🚀 INICIANDO TRAMIBOT (GOOGLE ADK) PARA EL FRONTEND REACT")
    print("=" * 60)
    print("🤖 Agente: TramiBot - Trámites del Municipio de Girardota (RAG + Memoria)")
    print(f"🧠 Modelo: {MODELO}")
    print("🔧 Tools: buscar_tramites, obtener_fecha_hora")
    print("💾 Historial: sesiones de ADK en PostgreSQL")
    print(f"🌐 API: http://127.0.0.1:{FRONTEND_PORT}/api")
    print(f"🖥️  Build servido: {DIST_DIR if os.path.isdir(DIST_DIR) else 'no — usa npm run dev en ../Frontend_React'}")
    print("=" * 60)
    print()

    uvicorn.run(app, host="0.0.0.0", port=FRONTEND_PORT)
