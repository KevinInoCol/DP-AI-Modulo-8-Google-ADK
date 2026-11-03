"""
Módulo de Tools para el agente (Google ADK).
En ADK una tool es una función Python (sync o async) con docstring y tipos;
ADK la envuelve automáticamente en un FunctionTool.
"""

from .Base_de_conocimiento import buscar_tramites
from .Busqueda_internet import buscar_internet
from .Hora_y_fecha import obtener_fecha_hora
from .Transferir_humano import transferir_a_humano

__all__ = [
    "buscar_tramites",
    "buscar_internet",
    "obtener_fecha_hora",
    "transferir_a_humano",
]
