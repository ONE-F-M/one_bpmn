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
import time

import frappe

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
# Chosen in the Embedding Model setting to turn semantic search off and leave
# keyword search, which is what a machine that cannot reach the model should do.
SEMANTIC_DISABLED = "Disabled"

_model = None
_model_name = None


def model_name() -> str:
	"""Configured model, or the default. Reads Processa Settings; never raises."""
	try:
		return frappe.db.get_single_value("Processa Settings", "memory_embedding_model") or DEFAULT_MODEL
	except Exception:
		return DEFAULT_MODEL


def probe_model(name: str) -> int:
	"""Load ``name`` and return how many numbers it produces per text.

	Raises if the model cannot be loaded. Used by the Processa Settings save
	check, which is the one place a slow first download is acceptable. Builds
	its own instance instead of going through ``_get_model`` so probing a model
	that is about to be rejected does not evict the working one from the cache.
	"""
	from fastembed import TextEmbedding

	model = TextEmbedding(name, cache_dir=_cache_dir())
	return len(next(iter(model.embed(["probe"]))))


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


# One Error Log an hour per kind of failure. A backfill that meets the same
# broken model on two hundred rows should leave one record, not two hundred,
# and a site that is still broken tomorrow should say so again tomorrow.
_REPORT_WINDOW_SECONDS = 3600
_reported: dict[str, float] = {}


def _recently_reported(title: str) -> bool:
	"""True when this failure is already on record inside the window.

	Two guards, because they cover different things. The in-process clock holds
	a backfill walking two hundred rows, and it holds even where Redis is
	unreachable (the cache swallows a connection error and answers None, which
	would make a cache-only guard quietly useless). The cache key holds across
	the other workers.
	"""
	now = time.monotonic()
	last = _reported.get(title)
	if last is not None and now - last < _REPORT_WINDOW_SECONDS:
		return True
	_reported[title] = now

	key = f"one_bpmn:memory_degraded:{title}"
	if frappe.cache.get_value(key):
		return True
	frappe.cache.set_value(key, 1, expires_in_sec=_REPORT_WINDOW_SECONDS)
	return False


def report_degraded(title: str, detail: str) -> None:
	"""Record a fallback to keyword search where somebody will see it.

	``frappe.logger`` sits at ERROR on every bench that does not set
	DEV_SERVER, so the warnings these paths used to emit were thrown away on
	staging and production. A site could store months of memories with no
	embeddings and nothing anywhere said so. Rate limited by title, and it
	never raises: reporting the degradation must not become the thing that
	breaks the write.
	"""
	frappe.logger("one_bpmn").warning(f"{title} {detail}")
	try:
		if _recently_reported(title):
			return
		frappe.log_error(title=title, message=detail)
	except Exception:
		pass


def embed(texts: list[str]) -> list[list[float]] | None:
	"""Embed ``texts`` in order. Returns one vector per text, or ``None`` when
	embeddings are unavailable for any reason (logged once per failure).

	``None`` is also what an administrator asked for by choosing Disabled: the
	caller falls back to keyword search either way, so switching semantic search
	off needs no separate branch anywhere else.
	"""
	if not texts:
		return []
	if model_name() == SEMANTIC_DISABLED:
		return None
	try:
		return _vectors(texts)
	except Exception:
		report_degraded("AI Memory: embedding unavailable, keyword search only", frappe.get_traceback())
		return None
