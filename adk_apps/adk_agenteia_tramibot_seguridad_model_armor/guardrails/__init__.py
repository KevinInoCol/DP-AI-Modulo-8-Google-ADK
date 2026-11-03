"""Guardrails del agente: Model Armor mediante el plugin oficial de ADK."""

from .model_armor_guardrail import (
    crear_plugin_model_armor,
    evento_bloqueado,
    quitar_turnos_bloqueados,
    MENSAJE_ENTRADA_BLOQUEADA,
    MENSAJE_SALIDA_BLOQUEADA,
)

__all__ = [
    "crear_plugin_model_armor",
    "evento_bloqueado",
    "quitar_turnos_bloqueados",
    "MENSAJE_ENTRADA_BLOQUEADA",
    "MENSAJE_SALIDA_BLOQUEADA",
]
