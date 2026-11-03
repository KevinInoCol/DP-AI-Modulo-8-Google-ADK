"""
Módulo de Histórico de Conversación (chat_history).

Expone el SessionService de ADK (Postgres) que usa el Runner. El agente
consume solo esta API pública y no sabe qué backend hay debajo.
"""

from .session_store import (
    DB_SCHEMA,
    obtener_historial,
    preparar_esquema,
    session_service,
)

__all__ = [
    "DB_SCHEMA",
    "obtener_historial",
    "preparar_esquema",
    "session_service",
]
