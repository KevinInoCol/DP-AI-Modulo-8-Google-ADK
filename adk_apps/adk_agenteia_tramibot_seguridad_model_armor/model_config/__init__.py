"""
Módulo de Configuración del Modelo (model_config).

Config PURA del LLM, desacoplada del código. Para cambiar de modelo o
temperatura solo se edita model.yaml (o GEMINI_MODEL en el .env).

También resuelve CÓMO se conecta Gemini, según GEMINI_AUTH_MODE del .env:

  GEMINI_AUTH_MODE=api_key  → Gemini API (Google AI Studio) con GOOGLE_API_KEY
  GEMINI_AUTH_MODE=vertex   → Vertex AI con GOOGLE_CLOUD_PROJECT + GOOGLE_CLOUD_LOCATION
                              y Application Default Credentials (ADC)

Credenciales de Google Cloud: SOLO ADC, nunca una llave JSON de cuenta de servicio.
  - Local:      gcloud auth application-default login
                gcloud auth application-default set-quota-project <PROYECTO>
  - Cloud Run:  la cuenta de servicio del servicio (con sus roles), sin archivo.

ADK y google-genai leen GOOGLE_GENAI_USE_ENTERPRISE (antes GOOGLE_GENAI_USE_VERTEXAI)
para decidir; aquí se fijan ambas a partir de GEMINI_AUTH_MODE para que el
alumno solo toque una variable. Doc: https://adk.dev/get-started/google-cloud/

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

import os

import yaml
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model.yaml")

MODOS_VALIDOS = ("api_key", "vertex")
NIVELES_THINKING = ("minimal", "low", "medium", "high")


def load_model_config(path: str = _CONFIG_PATH) -> dict:
    """Carga model.yaml y aplica los overrides del .env (GEMINI_MODEL, JUDGE_MODEL)."""
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if os.getenv("GEMINI_MODEL"):
        cfg["llm"]["model"] = os.getenv("GEMINI_MODEL").strip()
    if os.getenv("GEMINI_THINKING_LEVEL"):
        cfg["llm"]["thinking_level"] = os.getenv("GEMINI_THINKING_LEVEL").strip()
    nivel = str(cfg["llm"].get("thinking_level", "")).lower()
    if nivel and nivel not in NIVELES_THINKING:
        raise ValueError(
            f"❌ thinking_level={nivel!r} no es válido. Usa: {' | '.join(NIVELES_THINKING)}"
        )
    if os.getenv("JUDGE_MODEL"):
        cfg["judge"]["model"] = os.getenv("JUDGE_MODEL").strip()
    return cfg


def verificar_adc() -> None:
    """
    Comprueba que hay Application Default Credentials (las necesitan Vertex AI y
    Model Armor). Falla con un mensaje claro en vez de un error críptico al primer turno.
    """
    import google.auth
    from google.auth.exceptions import DefaultCredentialsError

    try:
        google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    except DefaultCredentialsError as e:
        raise RuntimeError(
            "❌ No hay credenciales de Google Cloud (ADC).\n"
            "   En local:  gcloud auth application-default login\n"
            "              gcloud auth application-default set-quota-project <PROYECTO>\n"
            "   En Cloud Run se usa la cuenta de servicio del servicio."
        ) from e


def configurar_autenticacion_gemini() -> str:
    """
    Fija las variables que leen ADK y google-genai según GEMINI_AUTH_MODE.

    Debe llamarse antes de la primera llamada al modelo (el cliente de Gemini
    se crea de forma perezosa, así que basta con llamarla al importar el agente).

    Returns:
        El modo activo: "api_key" o "vertex".
    """
    modo = os.getenv("GEMINI_AUTH_MODE", "api_key").strip().lower()
    if modo not in MODOS_VALIDOS:
        raise ValueError(
            f"❌ GEMINI_AUTH_MODE={modo!r} no es válido. Usa: {' | '.join(MODOS_VALIDOS)}"
        )

    usar_vertex = "TRUE" if modo == "vertex" else "FALSE"
    os.environ["GOOGLE_GENAI_USE_ENTERPRISE"] = usar_vertex
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = usar_vertex  # nombre anterior, mismo efecto

    if modo == "api_key":
        if not os.getenv("GOOGLE_API_KEY"):
            raise ValueError(
                "❌ GEMINI_AUTH_MODE=api_key pero falta GOOGLE_API_KEY en el .env\n"
                "   Obtén una en https://aistudio.google.com/app/apikey"
            )
        print("🔑 Gemini vía API Key (Google AI Studio)")
    else:
        faltan = [v for v in ("GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION") if not os.getenv(v)]
        if faltan:
            raise ValueError(
                f"❌ GEMINI_AUTH_MODE=vertex pero faltan en el .env: {', '.join(faltan)}"
            )
        verificar_adc()
        print(
            f"☁️  Gemini vía Vertex AI: proyecto {os.getenv('GOOGLE_CLOUD_PROJECT')} "
            f"· región {os.getenv('GOOGLE_CLOUD_LOCATION')}"
        )
    return modo


__all__ = ["load_model_config", "configurar_autenticacion_gemini", "verificar_adc", "MODOS_VALIDOS", "NIVELES_THINKING"]
