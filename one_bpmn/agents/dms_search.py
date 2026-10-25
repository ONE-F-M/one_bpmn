"""Search over the Active Document Register entries, for the General Chat DMS tool."""

import json
import math
import os

import frappe
from frappe import _
from frappe.utils.synchronization import filelock

from one_bpmn.agents.llm_provider.embedding import embed
from one_bpmn.agents.memory.tools import _SEMANTIC_MIN_SIMILARITY, _query_tokens

DOCTYPE = "Document Register"
DOCUMENT_TYPES = ("Policy", "SOP", "Manual", "Guideline", "Knowledge Base")
METADATA_FIELDS = ["name", "title", "document_code", "document_type", "current_version"]
INDEX_LOCK = "dms_search_index"
CHUNK_WORDS = 600
CHUNK_OVERLAP = 80
KEYWORD_MIN_SHARE = 0.34
MAX_RESULTS = 4


def enqueue_reindex(doc, method=None):
	"""Document hook: refresh this document's chunks in the background."""
	frappe.enqueue(
		"one_bpmn.agents.dms_search.reindex_document",
		document=doc.name,
		queue="long",
		job_id=f"dms_reindex_{doc.name}",
		deduplicate=True,
		enqueue_after_commit=True,
	)


def reindex_document(document: str):
	"""Replace a document's chunks with its current content; Inactive or deleted documents keep none."""
	row = frappe.db.get_value(
		DOCTYPE, document, [*METADATA_FIELDS, "lifecycle_state", "content"], as_dict=True
	)
	active = bool(row and row.lifecycle_state == "Active" and row.content)
	chunks = _chunk_words(row.content) if active else []
	vectors = embed(chunks) if chunks else None

	with filelock(INDEX_LOCK):
		entries = [entry for entry in _load_index() if entry["name"] != document]
		for position, text in enumerate(chunks):
			entries.append(
				{
					**{field: row[field] for field in METADATA_FIELDS},
					"text": text,
					"vector": _unit(vectors[position]) if vectors else None,
				}
			)
		_save_index(entries)


def search_dms_documents(query: str, document_type: str | None = None) -> dict:
	"""Top matching excerpts from Active documents the current user can read."""
	if document_type and document_type not in DOCUMENT_TYPES:
		return {"error": _("document_type must be one of: {0}").format(", ".join(DOCUMENT_TYPES))}

	entries = [e for e in _load_index() if not document_type or e["document_type"] == document_type]
	query_vectors = embed([query]) if entries else None
	query_vector = _unit(query_vectors[0]) if query_vectors else None
	tokens = [token.lower() for token in _query_tokens(query)]

	hits = []
	for entry in entries:
		score = _score(entry, query_vector, tokens)
		if score is not None:
			hits.append((score, entry))
	hits.sort(key=lambda hit: hit[0], reverse=True)

	readable, results = {}, []
	for _hit_score, entry in hits:
		name = entry["name"]
		if name not in readable:
			readable[name] = frappe.db.get_value(
				DOCTYPE, name, "lifecycle_state"
			) == "Active" and frappe.has_permission(DOCTYPE, "read", doc=name)
		if readable[name]:
			results.append(
				{
					"title": entry["title"],
					"document_code": entry["document_code"],
					"document_type": entry["document_type"],
					"version": entry["current_version"],
					"excerpt": entry["text"],
					"url": frappe.db.get_value(DOCTYPE, name, "drive_file_link"),
				}
			)
		if len(results) == MAX_RESULTS:
			break

	return {"results": results}


def _score(entry: dict, query_vector: list | None, tokens: list) -> float | None:
	"""Cosine similarity, or the share of query keywords found when either side has no vector; None below the floor."""
	if query_vector and entry["vector"]:
		score = sum(a * b for a, b in zip(query_vector, entry["vector"]))
		return score if score >= _SEMANTIC_MIN_SIMILARITY else None
	if not tokens:
		return None
	text = entry["text"].lower()
	share = sum(token in text for token in tokens) / len(tokens)
	return share if share >= KEYWORD_MIN_SHARE else None


def _chunk_words(text: str) -> list[str]:
	words = text.split()
	if not words:
		return []
	step = CHUNK_WORDS - CHUNK_OVERLAP
	return [
		" ".join(words[start : start + CHUNK_WORDS])
		for start in range(0, max(len(words) - CHUNK_OVERLAP, 1), step)
	]


def _unit(vector: list) -> list[float]:
	norm = math.sqrt(sum(v * v for v in vector)) or 1.0
	return [float(v) / norm for v in vector]


def _index_path() -> str:
	return frappe.get_site_path("private", "dms_search_index.json")


# ponytail: whole index is read per query, move to a vector column if it outgrows a few thousand chunks
def _load_index() -> list[dict]:
	path = _index_path()
	if not os.path.exists(path):
		return []
	with open(path) as index_file:
		return json.load(index_file)


def _save_index(entries: list[dict]):
	path = _index_path()
	with open(f"{path}.tmp", "w") as index_file:
		json.dump(entries, index_file)
	os.replace(f"{path}.tmp", path)
