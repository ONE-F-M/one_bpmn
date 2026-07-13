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
# Ignore short tokens: InnoDB FULLTEXT ignores anything below ft_min_token_size
# (default 3), so a whole-sentence query still matches on its real words.
_MIN_TOKEN_LEN = 3
# Very common words carry no signal; dropping them stops a whole-prompt query
# from matching essentially every memory in scope (the old recency-noise bug).
_STOPWORDS = frozenset(
	{
		"the", "and", "for", "with", "that", "this", "you", "your", "are", "was",
		"were", "have", "has", "had", "will", "would", "should", "could", "can",
		"not", "but", "from", "into", "out", "about", "what", "when", "where",
		"which", "who", "how", "please", "need", "want", "use", "using", "all",
		"any", "its", "our", "their", "them", "then", "there", "here", "been",
	}
)


def _query_tokens(query: str) -> list[str]:
	"""Split a free-text query into distinct, meaningful keyword tokens. A whole
	user prompt is a valid query, so we match on its content words — dropping
	stopwords and sub-index-length tokens — rather than the entire string."""
	seen, tokens = set(), []
	for tok in re.split(r"\W+", query or ""):
		tok = tok.strip()
		low = tok.lower()
		if len(tok) >= _MIN_TOKEN_LEN and low not in _STOPWORDS and low not in seen:
			seen.add(low)
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
def _row_dict(r) -> dict:
	return {"name": r["name"], "content": r.get("content"), "metadata": _json_loads(r.get("metadata"))}


def _fulltext_search(filters: dict, query: str, limit: int):
	"""Relevance-ranked search via a MariaDB FULLTEXT ``MATCH`` (the
	``content_fulltext`` index created in ``ai_memory.on_doctype_update``).

	Returns row dicts ordered by match score then recency, or ``None`` when
	FULLTEXT is unavailable (missing index / unsupported engine) so the caller
	falls back to ``like``. An empty list is also treated by the caller as
	"fall back" — it covers the InnoDB case where rows written in the current
	uncommitted transaction are not yet visible to the FULLTEXT cache.
	"""
	conds = " AND ".join(f"`{col}` = %({col})s" for col in filters)
	params = dict(filters, _q=query, _lim=int(limit))
	sql = f"""
		SELECT name, content, metadata,
		       MATCH(content) AGAINST (%(_q)s IN NATURAL LANGUAGE MODE) AS _score
		FROM `tabAI Memory`
		WHERE {conds}
		  AND MATCH(content) AGAINST (%(_q)s IN NATURAL LANGUAGE MODE)
		ORDER BY _score DESC, modified DESC
		LIMIT %(_lim)s
	"""
	try:
		return frappe.db.sql(sql, params, as_dict=True)
	except Exception:
		return None


def memory_search(scope: str, scope_key, query: str, limit: int = 5, *, ignore_permissions: bool = False) -> list[dict]:
	"""Look up memories for exactly one scope key whose content matches ``query``.

	Returns up to ``limit`` results as ``[{name, content, metadata}]``, never from
	a different scope key. Ranking depends on the path taken:

	- Trusted dispatch (``ignore_permissions=True``) with indexable query tokens
	  uses a FULLTEXT ``MATCH`` and returns results ordered by **relevance** then
	  recency — so the most on-topic memories surface, not merely the most recent.
	- Otherwise (permission-enforced callers, no indexable tokens, or FULLTEXT
	  unavailable) it uses keyword ``like`` filters ordered by recency. The
	  FULLTEXT path is gated on ``ignore_permissions`` because raw SQL cannot
	  apply Frappe row-level permissions.

	Permissions are enforced by default so an agent only searches memories it is
	allowed to read. ``ignore_permissions=True`` is for trusted server-side
	dispatch ONLY (see ``memory_write``) — never expose it via a whitelisted
	method.
	"""
	filters = _resolve_scope(scope, scope_key)
	page_length = limit if isinstance(limit, int) and limit > 0 else _DEFAULT_LIMIT
	tokens = _query_tokens(query) if query else []

	# Relevance-ranked FULLTEXT path (trusted dispatch only). A non-empty result
	# wins; empty/unavailable falls through to the keyword path below.
	if ignore_permissions and tokens:
		rows = _fulltext_search(filters, " ".join(tokens), page_length)
		if rows:
			return [_row_dict(r) for r in rows]

	# Keyword match: OR each query token against content. `filters` (scope) is
	# AND-ed with `or_filters` (the token match) by DatabaseQuery, so results
	# stay pinned to the exact scope key. Empty/short-only query -> recency list.
	or_filters = [["content", "like", f"%{tok}%"] for tok in tokens] or None
	rows = frappe.get_list(
		"AI Memory",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "content", "metadata"],
		order_by="modified desc",
		limit_page_length=page_length,
		ignore_permissions=ignore_permissions,
	)
	return [_row_dict(r) for r in rows]


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
