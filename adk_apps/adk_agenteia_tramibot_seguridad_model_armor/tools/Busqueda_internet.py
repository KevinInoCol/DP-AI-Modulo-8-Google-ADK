"""
Tool: Búsqueda en Internet (Tavily) — versión Google ADK
Permite buscar información actualizada en internet.

Igual que en la versión LangChain, está DESACTIVADA en el agente municipal
(ver la lista de tools en agente_sec_langfuse.py): el agente responde solo
desde el Manual oficial para evitar alucinaciones de la web abierta.
Para activarla, agrégala a TOOLS_BASE en agente_sec_langfuse.py.

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

import os

from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
MAX_RESULTADOS = 5

_cliente = None


def _get_cliente():
    """Cliente de Tavily perezoso: solo exige la key si la tool se usa."""
    global _cliente
    if _cliente is None:
        if not TAVILY_API_KEY:
            raise ValueError(
                "❌ Falta TAVILY_API_KEY en .env\n"
                "Obtén tu API key gratis en: https://tavily.com"
            )
        from tavily import TavilyClient

        _cliente = TavilyClient(api_key=TAVILY_API_KEY)
    return _cliente


def buscar_internet(consulta: str) -> dict:
    """
    Busca información pública actualizada sobre el Municipio de Girardota en
    internet usando Tavily (p. ej. datos de contacto, direcciones, horarios de
    atención o comunicados oficiales que no estén en la base de conocimiento).
    Usa esta herramienta ÚNICAMENTE para complementar información del municipio.

    NUNCA uses esta herramienta para:
    - Preguntas de cultura general (política, deportes, noticias, ciencia)
    - Temas no relacionados con el Municipio de Girardota o sus trámites

    Args:
        consulta: El aspecto del Municipio de Girardota a buscar.

    Returns:
        dict con "status" y "resultados" (título, contenido y fuente de cada uno).
    """
    # Forzar que la búsqueda siempre esté en el contexto del municipio
    consulta_municipio = f"Municipio de Girardota {consulta}"
    print(f"   🌐 Buscando en internet: '{consulta_municipio}'")

    try:
        respuesta = _get_cliente().search(consulta_municipio, max_results=MAX_RESULTADOS)
    except Exception as e:
        return {"status": "error", "error_message": f"Error al buscar en internet: {e}"}

    resultados = [
        {
            "titulo": r.get("title", "Sin título"),
            "contenido": (r.get("content") or "")[:500],
            "fuente": r.get("url", ""),
        }
        for r in respuesta.get("results", [])
    ]
    if not resultados:
        return {"status": "sin_resultados", "mensaje": "No encontré información relevante en internet."}
    return {"status": "success", "resultados": resultados}
