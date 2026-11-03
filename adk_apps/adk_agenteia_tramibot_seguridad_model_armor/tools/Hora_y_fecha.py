"""
Tool: Hora y Fecha actual (por región) — versión Google ADK
Devuelve la fecha y hora actual en una zona horaria. Sin APIs externas, apto para producción.

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

# Zona horaria por defecto (ej. America/Lima, America/Bogota, Europe/Madrid)
DEFAULT_TIMEZONE = os.getenv("AGENT_TIMEZONE", "America/Lima")

# Nombres de días y meses en español
DIAS = [
    "lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"
]
MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
]


def _fecha_hora_actual(zona: str) -> dict:
    """Obtiene fecha y hora en la zona indicada. Usa solo stdlib (zoneinfo)."""
    try:
        tz = ZoneInfo(zona)
    except Exception:
        tz = ZoneInfo(DEFAULT_TIMEZONE)
        zona = DEFAULT_TIMEZONE
    now = datetime.now(tz)
    return {
        "status": "success",
        "zona_horaria": zona,
        "fecha": f"{DIAS[now.weekday()]}, {now.day} de {MESES[now.month - 1]} de {now.year}",
        "hora": now.strftime("%H:%M:%S"),
        "iso": now.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


def obtener_fecha_hora(zona_horaria: str = "") -> dict:
    """
    Obtiene la fecha y hora actual en una zona horaria.
    Usa esta herramienta cuando el usuario pregunte:
    - Qué hora es, qué día es, fecha actual
    - Horario, momento actual, "ahora"
    - Hora en otra ciudad/región (pasa la zona, ej. Europe/Madrid, America/Mexico_City)

    Args:
        zona_horaria: Zona IANA opcional (ej. America/Lima, Europe/Madrid).
                      Si está vacío, se usa la zona por defecto del agente (AGENT_TIMEZONE).

    Returns:
        dict con "status", "zona_horaria", "fecha" legible en español, "hora" e "iso".
    """
    zona = (zona_horaria or "").strip() or DEFAULT_TIMEZONE
    print(f"   🕐 Obteniendo fecha/hora: {zona}")
    return _fecha_hora_actual(zona)
