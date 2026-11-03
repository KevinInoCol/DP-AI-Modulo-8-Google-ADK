"""
Pipeline de ingesta RAG · EMBEDDINGS (adaptado a OpenAI, sin LangChain)
Ruta: rag/pipeline/embeddings.py

Módulo glue que provee la interfaz que consume el orquestador (g_orchestrator):
  - DEFAULT_DIMENSION           dimensión del vector.
  - embed_documents(provider, texts) -> np.ndarray  (n_texts, dim)

Adaptación del pipeline original (que usaba Gemini) a **OpenAI
text-embedding-ada-002**, para que write (ingesta) y read (el agente en
tools/Base_de_conocimiento.py) usen EL MISMO modelo — si no, el agente no podría
consultar lo ingestado (vectores en espacios distintos).

Se conserva la firma `embed_documents(provider, texts)` por compatibilidad con el
orquestador; el único proveedor implementado es OpenAI.

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

from __future__ import annotations

import os

import numpy as np
from dotenv import find_dotenv, load_dotenv
from openai import OpenAI

load_dotenv(find_dotenv())

# Mismo modelo/dimensión que lee el agente (text-embedding-ada-002 → 1536, coseno).
DEFAULT_MODEL = os.getenv("RAG_EMBEDDING_MODEL", "text-embedding-ada-002")
DEFAULT_DIMENSION = int(os.getenv("RAG_EMBEDDING_DIM", "1536"))

_SUPPORTED = {"openai", "openai-ada", "ada", "default", ""}

_client: OpenAI | None = None
_BATCH = 512  # textos por petición a la API de embeddings


def _get_client() -> OpenAI:
    """Cliente OpenAI perezoso (singleton por proceso). Lee OPENAI_API_KEY."""
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


def _embed(texts: list[str]) -> list[list[float]]:
    """Embeddings con el SDK de OpenAI, en lotes y en el mismo orden de entrada."""
    vectores: list[list[float]] = []
    for i in range(0, len(texts), _BATCH):
        resp = _get_client().embeddings.create(model=DEFAULT_MODEL, input=texts[i : i + _BATCH])
        vectores.extend(d.embedding for d in sorted(resp.data, key=lambda d: d.index))
    return vectores


def embed_documents(provider: str, texts: list[str]) -> np.ndarray:
    """
    Genera embeddings de una lista de textos (para indexar en Qdrant).

    Args:
        provider: por compatibilidad con el orquestador. Solo se soporta OpenAI.
        texts:    textos de los chunks.

    Returns:
        np.ndarray de forma (len(texts), DEFAULT_DIMENSION), dtype float32.
    """
    if provider and provider.lower() not in _SUPPORTED:
        raise ValueError(
            f"Proveedor de embeddings no soportado: {provider!r}. "
            "Este RAG está adaptado a OpenAI (text-embedding-ada-002)."
        )
    if not texts:
        return np.zeros((0, DEFAULT_DIMENSION), dtype=np.float32)
    vectors = _embed(list(texts))
    return np.asarray(vectors, dtype=np.float32)


def embed_query(text: str) -> np.ndarray:
    """Embedding de una consulta (mismo modelo que embed_documents)."""
    return np.asarray(_embed([text])[0], dtype=np.float32)
