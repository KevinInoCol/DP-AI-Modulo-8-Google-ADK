"""
Punto de entrada de ADK para TramiBot (`adk web` / `adk run`).

Este paquete (adk_apps/adk_agenteia_tramibot_seguridad_model_armor/) ES el agente completo: tools, guardrails,
memoria, observabilidad y también los servidores (Chatwoot y Frontend React).
ADK trata cada subcarpeta de adk_apps/ como un agente; el nombre de la carpeta
debe ser un identificador de Python (snake_case) y coincidir con el del App.

    cd Modulo-8-Sesion-1-Google-ADK
    adk web adk_apps          # elige "adk_agenteia_tramibot_seguridad_model_armor" en http://127.0.0.1:8000
    adk run adk_apps/adk_agenteia_tramibot_seguridad_model_armor

Aquí se expone la variante SIN transferir_a_humano (no hay Chatwoot en la UI de
desarrollo), con el plugin de Model Armor. `adk web` usa su propio SessionService
(en memoria), no el Postgres del proyecto. Doc: https://adk.dev/apps/

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

from google.adk.apps import App

from .agente_sec_langfuse import crear_agente
from .guardrails import crear_plugin_model_armor

root_agent = crear_agente(con_handoff=False)

app = App(
    name="adk_agenteia_tramibot_seguridad_model_armor",
    root_agent=root_agent,
    plugins=[crear_plugin_model_armor()],
)
