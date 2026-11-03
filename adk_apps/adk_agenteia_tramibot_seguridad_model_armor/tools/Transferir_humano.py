"""
Tool: Transferir a Humano (Handoff IA → Asesor) — versión Google ADK
Coloca el tag "ia-off" en el CONTACTO y en la CONVERSACIÓN de Chatwoot
para desactivar el bot de forma inmediata y permanente.

APIs usadas:
  - Contacto:     POST /api/v1/accounts/{account_id}/contacts/{id}/labels
    https://developers.chatwoot.com/api-reference/contact-labels/add-labels
  - Conversación: POST /api/v1/accounts/{account_id}/conversations/{id}/labels
    (para que el webhook detecte "ia-off" en el payload de inmediato)

Diferencia con la versión LangChain:
  Allí la tool se fabricaba en cada turno con una closure que capturaba
  contact_id y conversation_id. En ADK el agente es fijo, así que el webhook
  pasa esos IDs en el ESTADO de la sesión (Runner.run_async(state_delta=...))
  y la tool los lee con ToolContext. ADK inyecta tool_context automáticamente
  y NO lo expone al modelo. Doc: https://adk.dev/tools-custom/function-tools/

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

import asyncio
import os

import requests
from dotenv import load_dotenv, find_dotenv
from google.adk.tools import ToolContext

load_dotenv(find_dotenv())

CHATWOOT_BASE_URL = os.getenv("CHATWOOT_BASE_URL", "").rstrip("/")
CHATWOOT_ACCOUNT_ID = os.getenv("CHATWOOT_ACCOUNT_ID")
CHATWOOT_API_TOKEN = os.getenv("CHATWOOT_API_ACCESS_TOKEN")

TAG_IA_OFF = "ia-off"

# Claves de estado que escribe el webhook (main_chatwoot-ia_off.py)
STATE_CONTACT_ID = "chatwoot_contact_id"
STATE_CONVERSATION_ID = "chatwoot_conversation_id"

MENSAJE_TRASPASO = (
    "Perfecto, he notificado a nuestro equipo. Un asesor humano tomará "
    "tu conversación en breve — por favor aguarda unos minutos. "
    "¡Gracias por tu paciencia!"
)


def _headers() -> dict:
    return {
        "api_access_token": CHATWOOT_API_TOKEN,
        "Content-Type": "application/json",
    }


# ============================================================
# FUNCIONES INTERNAS (síncronas; se ejecutan en un hilo aparte)
# ============================================================
def _agregar_label(recurso: str, recurso_id: int) -> list[str]:
    """
    Agrega "ia-off" a un contacto o conversación sin perder sus otras etiquetas.

    La API de Chatwoot sobreescribe todos los labels, así que primero hace GET
    para obtener los existentes y luego los fusiona antes del POST.

    Args:
        recurso:    "contacts" o "conversations".
        recurso_id: ID del contacto o de la conversación.
    """
    base = f"{CHATWOOT_BASE_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/{recurso}/{recurso_id}"

    try:
        get_resp = requests.get(f"{base}/labels", headers=_headers(), timeout=10)
        get_resp.raise_for_status()
        labels_actuales: list[str] = get_resp.json().get("payload", [])
    except Exception:
        labels_actuales = []

    if TAG_IA_OFF not in labels_actuales:
        labels_actuales.append(TAG_IA_OFF)

    post_resp = requests.post(
        f"{base}/labels",
        json={"labels": labels_actuales},
        headers=_headers(),
        timeout=10,
    )
    post_resp.raise_for_status()
    return post_resp.json().get("payload", labels_actuales)


# ============================================================
# TOOL EXPORTABLE
# ============================================================
async def transferir_a_humano(tool_context: ToolContext) -> dict:
    """
    Transfiere la conversación a un asesor humano y desactiva la IA.

    Usa esta herramienta ÚNICAMENTE cuando el usuario exprese claramente
    que quiere comunicarse con una persona real, por ejemplo:
    - "quiero hablar con un humano / una persona / un asesor"
    - "necesito soporte personalizado"
    - "comunícame con alguien"
    - "prefiero atención humana"
    - "pásame con un representante"

    Tras ejecutar esta herramienta el agente IA dejará de responder
    tanto en esta conversación como en futuras del mismo contacto.

    Returns:
        dict con "status" y el "mensaje" que debes transmitir al ciudadano.
    """
    contact_id = tool_context.state.get(STATE_CONTACT_ID)
    conversation_id = tool_context.state.get(STATE_CONVERSATION_ID)

    print(
        f"   🤝 [HANDOFF] Aplicando '{TAG_IA_OFF}' → "
        f"contacto {contact_id} | conversación {conversation_id}..."
    )

    if not all([CHATWOOT_BASE_URL, CHATWOOT_ACCOUNT_ID, CHATWOOT_API_TOKEN]):
        print("   ⚠️  [HANDOFF] Configuración de Chatwoot incompleta.")
        return {"status": "notificado", "mensaje": MENSAJE_TRASPASO}

    errores = []

    # 1. Etiquetar el contacto (desactivación permanente)
    if contact_id:
        try:
            labels = await asyncio.to_thread(_agregar_label, "contacts", contact_id)
            print(f"   ✅ [HANDOFF] Contacto {contact_id} etiquetado: {labels}")
        except requests.exceptions.RequestException as e:
            print(f"   ❌ [HANDOFF] Error al etiquetar contacto: {e}")
            errores.append("contacto")

    # 2. Etiquetar la conversación (desactivación inmediata en webhook)
    if conversation_id:
        try:
            labels = await asyncio.to_thread(_agregar_label, "conversations", conversation_id)
            print(f"   ✅ [HANDOFF] Conversación {conversation_id} etiquetada: {labels}")
        except requests.exceptions.RequestException as e:
            print(f"   ❌ [HANDOFF] Error al etiquetar conversación: {e}")
            errores.append("conversación")

    if errores:
        print(f"   ⚠️  [HANDOFF] Falló el etiquetado en: {errores}")

    return {"status": "transferido", "mensaje": MENSAJE_TRASPASO}
