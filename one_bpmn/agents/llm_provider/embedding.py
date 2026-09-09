"""
Embedding adapter for AI Memory semantic retrieval.

One function, ``embed``. It runs a small ONNX sentence-embedding model on the
worker CPU through ``fastembed`` (no PyTorch), so a memory write or a recall
query never leaves the box and costs nothing per call. The model files are
fetched once per bench into ``sites/.fastembed`` and loaded once per process.

Failure of any kind (package missing, model not downloadable, runtime error)
returns ``None``. Callers treat ``None`` as "no semantic signal" and fall back
to keyword search. Embeddings improve retrieval; they are never a dependency
for it.

Swapping to a hosted embedding API is a change to ``_vectors`` only; the
column size in ``ai_memory.EMBEDDING_DIMENSIONS`` must follow the model.
"""

from __future__ import annotations

import os

import frappe

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

_model = None
_model_name = None


def model_name() -> str:
	"""Configured model, or the default. Reads Processa Settings; never raises."""
	try:
		return frappe.db.get_single_value("Processa Settings", "memory_embedding_model") or DEFAULT_MODEL
	except Exception:
		return DEFAULT_MODEL


def _cache_dir() -> str:
	# One download per bench, shared by every worker and every site on it.
	return os.path.join(frappe.utils.get_bench_path(), "sites", ".fastembed")


def _get_model(name: str):
	global _model, _model_name
	if _model is None or _model_name != name:
		from fastembed import TextEmbedding

		_model = TextEmbedding(name, cache_dir=_cache_dir())
		_model_name = name
	return _model


def _vectors(texts: list[str]) -> list[list[float]]:
	model = _get_model(model_name())
	return [[float(x) for x in vector] for vector in model.embed([text or "" for text in texts])]


def embed(texts: list[str]) -> list[list[float]] | None:
	"""Embed ``texts`` in order. Returns one vector per text, or ``None`` when
	embeddings are unavailable for any reason (logged once per failure)."""
	if not texts:
		return []
	try:
		return _vectors(texts)
	except Exception:
		frappe.logger("one_bpmn").warning(
			f"AI Memory: embedding unavailable, keyword search only. {frappe.get_traceback()}"
		)
		return None
