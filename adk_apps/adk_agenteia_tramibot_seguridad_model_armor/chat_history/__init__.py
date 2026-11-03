"""
Módulo de Histórico de Conversación (chat_history).

Expone el SessionService de ADK (Cloud SQL multitenant) que usa el Runner. El
agente consume solo esta API pública y no sabe qué backend hay debajo.
"""

from .session_store import DB_USER, session_service

__all__ = ["DB_USER", "session_service"]
