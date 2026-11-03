"""
Guardrail con Model Armor (Google Cloud) para TramiBot — plugin OFICIAL de ADK.

En la versión LangChain había un módulo propio que llamaba a la API de Model
Armor antes y después del agente. En ADK se usa `ModelArmorPlugin`, que viene
con el framework y se registra en el `App`. Doc: https://adk.dev/integrations/model-armor/

  - Entrada: before_model_callback → sanitize_user_prompt   (antes de llamar a Gemini)
  - Salida:  after_model_callback  → sanitize_model_response (antes de entregar la respuesta)

Los filtros, niveles de confianza y el registro siguen viviendo en la plantilla
de la consola (projects/<proyecto>/locations/<región>/templates/<id>), no en el código.

Diferencias con el guardrail propio de la versión LangChain:
  - El plugin devuelve UN mensaje de bloqueo para la entrada y OTRO para la salida
    (no uno distinto por filtro activado: prompt injection, PII, URL maliciosa…).
  - Un turno bloqueado lleva custom_metadata['model_armor_blocked'] en su evento;
    así la web distingue un bloqueo de una respuesta normal (campo "bloqueado").
  - Si Model Armor no responde, bloquea (fail-closed), igual que antes.

Autenticación: Application Default Credentials. Con GOOGLE_APPLICATION_CREDENTIALS
en el .env se usa esa cuenta de servicio (necesita el rol Model Armor User,
roles/modelarmor.user). En Cloud Run se usa la cuenta de servicio del servicio.

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

import os

from dotenv import load_dotenv, find_dotenv
from google.adk.agents.callback_context import CallbackContext
from google.adk.integrations.model_armor import ModelArmorConfig, ModelArmorPlugin
from google.adk.models.llm_request import LlmRequest

load_dotenv(find_dotenv())

# ============================================================
# CONFIGURACIÓN (.env)
# ============================================================
MODEL_ARMOR_PROJECT = os.getenv("MODEL_ARMOR_PROJECT", "")
MODEL_ARMOR_LOCATION = os.getenv("MODEL_ARMOR_LOCATION", "us-central1")
MODEL_ARMOR_TEMPLATE = os.getenv("MODEL_ARMOR_TEMPLATE", "datapath-guardrail")
# Opcional: otra plantilla para la salida. Si no se define, se usa la misma.
MODEL_ARMOR_RESPONSE_TEMPLATE = os.getenv("MODEL_ARMOR_RESPONSE_TEMPLATE", "") or MODEL_ARMOR_TEMPLATE

# Clave que el plugin pone en el evento cuando bloquea
CLAVE_BLOQUEO = "model_armor_blocked"

MENSAJE_ENTRADA_BLOQUEADA = (
    "Lo siento, no puedo procesar ese mensaje. "
    "Por favor, reformula tu consulta sin datos sensibles ni instrucciones especiales. "
    "Estoy aquí para ayudarte con los trámites y servicios del Municipio de Girardota."
)
MENSAJE_SALIDA_BLOQUEADA = (
    "Lo siento, no puedo darte esa respuesta. "
    "Por favor, reformula tu consulta sobre los trámites del Municipio de Girardota."
)


def _plantilla(template_id: str) -> str:
    """Nombre completo de la plantilla (el plugin exige la ruta completa)."""
    return f"projects/{MODEL_ARMOR_PROJECT}/locations/{MODEL_ARMOR_LOCATION}/templates/{template_id}"


def crear_plugin_model_armor() -> ModelArmorPlugin:
    """Construye el plugin oficial con la(s) plantilla(s) del .env."""
    if not MODEL_ARMOR_PROJECT:
        raise ValueError(
            "❌ Falta MODEL_ARMOR_PROJECT en el .env (proyecto de GCP con la plantilla de Model Armor)"
        )
    return ModelArmorPlugin(
        config=ModelArmorConfig(
            prompt_template_name=_plantilla(MODEL_ARMOR_TEMPLATE),
            response_template_name=_plantilla(MODEL_ARMOR_RESPONSE_TEMPLATE),
            input_blocked_message=MENSAJE_ENTRADA_BLOQUEADA,
            output_blocked_message=MENSAJE_SALIDA_BLOQUEADA,
            block_on_screening_failure=True,  # fail-closed
        )
    )


def evento_bloqueado(event) -> bool:
    """True si el evento es la respuesta de reemplazo de un bloqueo de Model Armor."""
    return bool((getattr(event, "custom_metadata", None) or {}).get(CLAVE_BLOQUEO))


def _texto_content(content) -> str:
    if not content or not content.parts:
        return ""
    return "".join(p.text for p in content.parts if p.text and not p.thought).strip()


def quitar_turnos_bloqueados(callback_context: CallbackContext, llm_request: LlmRequest) -> None:
    """
    before_model_callback del agente: saca del contexto los turnos bloqueados en la entrada.

    Por qué hace falta: el Runner guarda el mensaje del usuario en la sesión ANTES
    de que el plugin lo revise, y en los turnos siguientes el plugin solo revisa el
    mensaje más reciente. Sin este filtro, un prompt injection ya bloqueado viajaría
    a Gemini dentro del historial en el siguiente turno. Se elimina cada par
    (mensaje del usuario + respuesta de bloqueo); el turno actual no se toca.
    Doc de callbacks: https://adk.dev/callbacks/types-of-callbacks/
    """
    contenidos = llm_request.contents or []
    limpios = []
    for c in contenidos:
        if c.role == "model" and _texto_content(c) == MENSAJE_ENTRADA_BLOQUEADA:
            # Quitar también el/los mensaje(s) de usuario que provocaron el bloqueo
            while limpios and limpios[-1].role == "user":
                limpios.pop()
            continue
        limpios.append(c)
    if len(limpios) != len(contenidos):
        llm_request.contents = limpios
    return None


__all__ = [
    "crear_plugin_model_armor",
    "evento_bloqueado",
    "quitar_turnos_bloqueados",
    "MENSAJE_ENTRADA_BLOQUEADA",
    "MENSAJE_SALIDA_BLOQUEADA",
]
