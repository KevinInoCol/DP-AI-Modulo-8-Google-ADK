"""
Tool: Base de Conocimiento (RAG con Qdrant) — versión Google ADK
Permite buscar información en la base de conocimiento de trámites del
Municipio de Girardota (Manual de Trámites).

Consume la MISMA colección de Qdrant que la versión LangChain (QDRANT_URL +
QDRANT_API_KEY + QDRANT_COLLECTION_NAME). Esa colección se creó con embeddings
de OpenAI text-embedding-ada-002 (1536 dimensiones, coseno), así que la
consulta se vectoriza con ese mismo modelo: si se usara otro (p. ej. un
embedding de Gemini) los vectores no serían comparables. Cambiar de modelo de
embeddings implica volver a ingestar (rag/pipeline/run_ingesta.py).

En ADK una tool es una función Python normal: su docstring es la descripción
que ve el modelo y sus parámetros tipados forman el esquema. Se devuelve un
dict con "status" (recomendación de la doc de ADK: https://adk.dev/tools-custom/function-tools/).
Es async para no bloquear el event loop mientras espera a OpenAI y Qdrant
(ADK ejecuta las tools síncronas dentro del loop).

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

import os
from urllib.parse import urlparse

from dotenv import load_dotenv, find_dotenv
from openai import AsyncOpenAI
from qdrant_client import AsyncQdrantClient

load_dotenv(find_dotenv())

# ============================================
# CONFIGURACIÓN DE QDRANT + EMBEDDINGS
# ============================================
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME")
EMBEDDING_MODEL = os.getenv("RAG_EMBEDDING_MODEL", "text-embedding-ada-002")
# Clave del payload donde está el texto del chunk. El pipeline de este proyecto
# (rag/pipeline/f_metadata.py) escribe "text"; una colección cargada con
# LangChain (QdrantVectorStore) usa "page_content". Se aceptan ambas.
CONTENT_PAYLOAD_KEYS = ("text", "page_content")
TOP_K = 8

if not QDRANT_URL:
    raise ValueError(
        "❌ Falta variable QDRANT_URL en .env "
        "(ej. https://tu-servidor-qdrant o http://IP:6333)"
    )
if not COLLECTION_NAME:
    raise ValueError("❌ Falta QDRANT_COLLECTION_NAME en .env")

# Normalizar URL y puerto. qdrant-client, si la URL no trae puerto, asume 6333,
# pero detrás de un proxy HTTPS (EasyPanel/Nginx/Caddy) el puerto es 443.
_qdrant_url = QDRANT_URL.rstrip("/")
_parsed = urlparse(_qdrant_url)
_qdrant_port = _parsed.port or (443 if _parsed.scheme == "https" else 6333)

_qdrant = AsyncQdrantClient(
    url=_qdrant_url,
    api_key=QDRANT_API_KEY,
    port=_qdrant_port,
    prefer_grpc=False,  # REST; usa True solo si expones gRPC (6334)
)
_openai = AsyncOpenAI()  # lee OPENAI_API_KEY del entorno


# ============================================
# FUNCIÓN INTERNA DE BÚSQUEDA
# ============================================
async def buscar_en_base_conocimiento_interno(query: str, top_k: int = TOP_K) -> list[str]:
    """Vectoriza la consulta y devuelve el texto de los chunks más parecidos."""
    respuesta = await _openai.embeddings.create(model=EMBEDDING_MODEL, input=query)
    vector = respuesta.data[0].embedding
    resultado = await _qdrant.query_points(
        collection_name=COLLECTION_NAME,
        query=vector,
        limit=top_k,
        with_payload=True,
    )
    puntos = resultado.points
    fragmentos = []
    for p in puntos:
        payload = p.payload or {}
        texto = next((payload[k] for k in CONTENT_PAYLOAD_KEYS if payload.get(k)), "")
        if texto:
            fragmentos.append(texto)
    return fragmentos


# ============================================
# TOOL EXPORTABLE
# ============================================
async def buscar_tramites(consulta: str) -> dict:
    """
    Busca información sobre los trámites y servicios del Municipio de Girardota
    en la base de conocimiento oficial (Manual de Trámites).
    Usa esta herramienta cuando el ciudadano pregunte sobre:
    - Requisitos y documentos de un trámite
    - Propósito o en qué consiste un trámite
    - Tiempo de obtención / plazos
    - Costos del trámite
    - Secretaría o dependencia responsable
    - Cualquier información sobre trámites del municipio

    Args:
        consulta: La pregunta o trámite a buscar.

    Returns:
        dict con "status" ("success", "sin_resultados" o "error") y, si hubo
        resultados, "fragmentos": los textos del Manual de Trámites encontrados.
    """
    print(f"   🔍 Buscando: '{consulta}'")
    try:
        fragmentos = await buscar_en_base_conocimiento_interno(consulta)
    except Exception as e:
        return {"status": "error", "error_message": f"Error al buscar: {e}"}

    if not fragmentos:
        return {
            "status": "sin_resultados",
            "mensaje": "No encontré información relevante en la base de conocimientos.",
        }
    return {"status": "success", "fragmentos": fragmentos}
