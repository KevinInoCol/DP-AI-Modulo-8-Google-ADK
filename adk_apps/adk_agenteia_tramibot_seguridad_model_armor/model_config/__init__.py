"""
Módulo de Configuración del Modelo (model_config).

Config PURA del LLM, desacoplada del código. Para cambiar de modelo o
temperatura solo se edita model.yaml (o GEMINI_MODEL en el .env).

También resuelve CÓMO se conecta Gemini, según GEMINI_AUTH_MODE del .env:

  GEMINI_AUTH_MODE=api_key  → Gemini API (Google AI Studio) con GOOGLE_API_KEY
  GEMINI_AUTH_MODE=vertex   → Vertex AI con GOOGLE_CLOUD_PROJECT + GOOGLE_CLOUD_LOCATION
                              y Application Default Credentials
                              (gcloud auth application-default login, o la
                              cuenta de servicio de GOOGLE_APPLICATION_CREDENTIALS)

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


def load_model_config(path: str = _CONFIG_PATH) -> dict:
    """Carga model.yaml y aplica los overrides del .env (GEMINI_MODEL, JUDGE_MODEL)."""
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if os.getenv("GEMINI_MODEL"):
        cfg["llm"]["model"] = os.getenv("GEMINI_MODEL").strip()
    if os.getenv("JUDGE_MODEL"):
        cfg["judge"]["model"] = os.getenv("JUDGE_MODEL").strip()
    return cfg


def _resolver_ruta_credenciales() -> None:
    """
    Convierte GOOGLE_APPLICATION_CREDENTIALS en ruta absoluta respecto a la raíz
    del proyecto. Así credenciales/xxx.json funciona aunque el script se lance
    desde otra carpeta (por ejemplo `adk web adk_apps`).
    """
    ruta = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if ruta and not os.path.isabs(ruta):
        raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.join(raiz, ruta)


def configurar_autenticacion_gemini() -> str:
    """
    Fija las variables que leen ADK y google-genai según GEMINI_AUTH_MODE.

    Debe llamarse antes de la primera llamada al modelo (el cliente de Gemini
    se crea de forma perezosa, así que basta con llamarla al importar el agente).

    Returns:
        El modo activo: "api_key" o "vertex".
    """
    _resolver_ruta_credenciales()

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
        print(
            f"☁️  Gemini vía Vertex AI: proyecto {os.getenv('GOOGLE_CLOUD_PROJECT')} "
            f"· región {os.getenv('GOOGLE_CLOUD_LOCATION')}"
        )
    return modo


__all__ = ["load_model_config", "configurar_autenticacion_gemini", "MODOS_VALIDOS"]
