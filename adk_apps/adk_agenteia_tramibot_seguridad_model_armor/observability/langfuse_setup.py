"""
Inicialización centralizada de Langfuse para el agente ADK.

Langfuse() es un singleton: basta con invocarlo una vez al arrancar el
proceso; cualquier módulo que haga `get_client()` recibe la misma instancia.

Diferencia con la versión LangChain:
  Allí se pasaba un CallbackHandler en cada invoke(). En ADK las trazas salen
  por OpenTelemetry: GoogleADKInstrumentor (OpenInference) instrumenta el
  Runner, las llamadas a Gemini y las tools, y Langfuse recibe esos spans.
  Doc: https://adk.dev/integrations/langfuse/

Lee LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY y LANGFUSE_BASE_URL del .env.

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

import os

from dotenv import load_dotenv, find_dotenv
from langfuse import Langfuse, get_client
from openinference.instrumentation.google_adk import GoogleADKInstrumentor

load_dotenv(find_dotenv())

# Arranca el singleton (idempotente — llamarlo varias veces no rompe nada).
Langfuse()

# Instancia única que usan el agente, el judge y los scripts.
langfuse_client = get_client()

# Instrumenta ADK una sola vez por proceso (Runner, modelo y tools → spans OTel).
_instrumentor = GoogleADKInstrumentor()
if not _instrumentor.is_instrumented_by_opentelemetry:
    _instrumentor.instrument()

print(
    f"📊 Langfuse conectado: "
    f"{os.getenv('LANGFUSE_BASE_URL', 'https://cloud.langfuse.com')}"
)
