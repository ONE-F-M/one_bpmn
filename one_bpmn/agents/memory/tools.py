"""
Long-term memory tools exposed to AI agents: ``memory_search`` and
``memory_write``.

These are standalone, unit-testable Python functions that read/write the
AI Memory doctype, honouring scope so an agent only sees memories for the
exact scope key it asks about. Each is registered in ``MEMORY_TOOLS`` with an
MCP-compatible definition ({name, description, input_schema}) so a future
multi-turn loop can discover and expose them as LLM tools without adding any
memory code — ``MEMORY_TOOLS`` is the single export the loop reads.

Scope key shapes (the ``scope_key`` argument):
    - "Agent"  -> agent_element (str) or {"agent_element": str}
    - "Process"-> process (str) or {"process": str}
    - "Entity" -> {"reference_doctype": str, "reference_name": str}
"""

from __future__ import annotations

import json
import re

import frappe
from frappe import _

VALID_SCOPES = ("Agent", "Process", "Entity")
_DEFAULT_LIMIT = 5
# Max distinct keyword tokens to OR-match from a query (bounds the WHERE clause).
_MAX_QUERY_TOKENS = 10
# Ignore very short tokens so a whole-sentence query still matches on real words.
_MIN_TOKEN_LEN = 2


def _query_tokens(query: str) -> list[str]:
	"""Split a free-text query into distinct keyword tokens for matching. A
	whole user prompt is a valid query, so we match on its words rather than
	the entire string as one substring."""
	seen, tokens = set(), []
	for tok in re.split(r"\W+", query or ""):
		tok = tok.strip()
		if len(tok) >= _MIN_TOKEN_LEN and tok.lower() not in seen:
			seen.add(tok.lower())
			tokens.append(tok)
		if len(tokens) >= _MAX_QUERY_TOKENS:
			break
	return tokens


def _json_loads(value):
	if not value:
		return None
	try:
		return json.loads(value)
	except (ValueError, TypeError):
		return None


def _resolve_scope(scope: str, scope_key) -> dict:
	"""Translate (scope, scope_key) into the AI Memory field filters that
	pin the query/record to exactly one scope key. Raises a translatable error
	if the scope or its key(s) are missing/invalid."""
	if scope not in VALID_SCOPES:
		frappe.throw(_("Invalid memory scope: {0}").format(scope))

	keys = {"memory_scope": scope}

	if scope == "Agent":
		agent_element = scope_key.get("agent_element") if isinstance(scope_key, dict) else scope_key
		if not agent_element:
			frappe.throw(_("Agent scope requires an agent_element."))
		keys["agent_element"] = agent_element

	elif scope == "Process":
		if isinstance(scope_key, dict):
			process_model = scope_key.get("process") or scope_key.get("process_model")
		else:
			process_model = scope_key
		if not process_model:
			frappe.throw(_("Process scope requires a process."))
		keys["process_model"] = process_model

	else:  # Entity
		if not isinstance(scope_key, dict):
			frappe.throw(_("Entity scope requires reference_doctype and reference_name."))
		reference_doctype = scope_key.get("reference_doctype")
		reference_name = scope_key.get("reference_name")
		if not (reference_doctype and reference_name):
			frappe.throw(_("Entity scope requires reference_doctype and reference_name."))
		keys["reference_doctype"] = reference_doctype
		keys["reference_name"] = reference_name

	return keys


# ── Tools ─────────────────────────────────────────────────────────────────
def memory_search(scope: str, scope_key, query: str, limit: int = 5, *, ignore_permissions: bool = False) -> list[dict]:
	"""Look up memories for exactly one scope key whose content matches ``query``.

	Returns up to ``limit`` results as ``[{name, content, metadata}]`` ordered by
	recency (most recent first). Never returns memories from a different scope
	key. Content matching uses keyword ``like`` filters (the documented v1
	approach for AI Memory; a FULLTEXT index backs it at scale).

	Permissions are enforced by default so an agent only searches memories it is
	allowed to read. ``ignore_permissions=True`` is for trusted server-side
	dispatch ONLY (see ``memory_write``) — never expose it via a whitelisted
	method.
	"""
	filters = _resolve_scope(scope, scope_key)
	# Keyword match: OR each query token against content. `filters` (scope) is
	# AND-ed with `or_filters` (the token match) by DatabaseQuery, so results
	# stay pinned to the exact scope key. Empty/short-only query -> recency list.
	or_filters = None
	if query:
		tokens = _query_tokens(query)
		if tokens:
			or_filters = [["content", "like", f"%{tok}%"] for tok in tokens]

	page_length = limit if isinstance(limit, int) and limit > 0 else _DEFAULT_LIMIT
	rows = frappe.get_list(
		"AI Memory",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "content", "metadata"],
		order_by="modified desc",
		limit_page_length=page_length,
		ignore_permissions=ignore_permissions,
	)
	return [
		{"name": r["name"], "content": r.get("content"), "metadata": _json_loads(r.get("metadata"))}
		for r in rows
	]


def memory_write(
	scope: str,
	scope_key,
	content: str,
	dedup_key: str | None = None,
	metadata: dict | None = None,
	source_run: str | None = None,
	*,
	ignore_permissions: bool = False,
) -> dict:
	"""Save a memory for a scope key.

	With a ``dedup_key`` that already exists for the same scope + key(s), the
	existing record's content/metadata (and source_run) are overwritten in
	place instead of inserting a duplicate; without a ``dedup_key`` a new record
	is inserted. ``source_run`` records provenance (the AI Agent Run that wrote
	the memory).

	Permissions: this writes as the caller's context. ``ignore_permissions=True``
	is the documented escape hatch for TRUSTED server-side dispatch only (the
	agent runs under a system context) — it must NEVER be passed from a
	whitelisted / HTTP-reachable method.

	Returns the resulting record as ``{name, content, metadata}``.
	"""
	keys = _resolve_scope(scope, scope_key)
	metadata_json = json.dumps(metadata) if metadata is not None else None

	existing = None
	if dedup_key:
		lookup = dict(keys, dedup_key=dedup_key)
		found = frappe.get_all("AI Memory", filters=lookup, pluck="name", limit=1)
		existing = found[0] if found else None

	if existing:
		doc = frappe.get_doc("AI Memory", existing)
		doc.content = content
		doc.metadata = metadata_json
		if source_run is not None:
			doc.source_run = source_run
		doc.save(ignore_permissions=ignore_permissions)
	else:
		doc = frappe.get_doc(
			{
				"doctype": "AI Memory",
				**keys,
				"content": content,
				"dedup_key": dedup_key,
				"metadata": metadata_json,
				"source_run": source_run,
			}
		)
		doc.insert(ignore_permissions=ignore_permissions)

	return {"name": doc.name, "content": doc.content, "metadata": _json_loads(doc.metadata)}


# ── MCP-compatible tool registry ────────────────────────────────────────────
# A JSON-Schema object describing a scope key. Which properties apply depends on
# `scope`; the tool validates the combination at runtime.
_SCOPE_ENUM = {"type": "string", "enum": list(VALID_SCOPES), "description": "Memory scope."}
_SCOPE_KEY_SCHEMA = {
	"type": "object",
	"description": (
		"The scope key. Agent: {agent_element}. Process: {process}. "
		"Entity: {reference_doctype, reference_name}."
	),
	"properties": {
		"agent_element": {"type": "string", "description": "BPMN element id (Agent scope)."},
		"process": {"type": "string", "description": "BPMN Process Model (Process scope)."},
		"reference_doctype": {"type": "string", "description": "Reference doctype (Entity scope)."},
		"reference_name": {"type": "string", "description": "Reference document name (Entity scope)."},
	},
	"additionalProperties": False,
}

MEMORY_SEARCH_SCHEMA = {
	"type": "object",
	"properties": {
		"scope": _SCOPE_ENUM,
		"scope_key": _SCOPE_KEY_SCHEMA,
		"query": {"type": "string", "description": "Keywords to match against memory content."},
		"limit": {"type": "integer", "minimum": 1, "default": _DEFAULT_LIMIT, "description": "Max results."},
	},
	"required": ["scope", "scope_key", "query"],
	"additionalProperties": False,
}

MEMORY_WRITE_SCHEMA = {
	"type": "object",
	"properties": {
		"scope": _SCOPE_ENUM,
		"scope_key": _SCOPE_KEY_SCHEMA,
		"content": {"type": "string", "description": "The memory text to store."},
		"dedup_key": {"type": "string", "description": "Optional; overwrites an existing memory with the same scope + key(s)."},
		"metadata": {"type": "object", "description": "Optional arbitrary structured data."},
		"source_run": {"type": "string", "description": "Optional AI Agent Run name for provenance."},
	},
	"required": ["scope", "scope_key", "content"],
	"additionalProperties": False,
}

# Single export the Epic-4 loop reads. Each entry is an MCP-compatible tool
# definition ({name, description, input_schema}) plus the Python `handler` that
# implements it.
MEMORY_TOOLS: dict[str, dict] = {}


def _register_tool(name: str, description: str, input_schema: dict, handler) -> None:
	MEMORY_TOOLS[name] = {
		"name": name,
		"description": description,
		"input_schema": input_schema,
		"handler": handler,
	}


_register_tool(
	"memory_search",
	"Search durable agent memories for a given scope key by keyword; returns matching memories.",
	MEMORY_SEARCH_SCHEMA,
	memory_search,
)
_register_tool(
	"memory_write",
	"Persist a durable agent memory for a given scope key; can overwrite by dedup_key.",
	MEMORY_WRITE_SCHEMA,
	memory_write,
)
