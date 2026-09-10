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
from frappe.utils import get_datetime, now, now_datetime

VALID_SCOPES = ("Agent", "Process", "Entity")
_DEFAULT_LIMIT = 5
# Extra rows fetched on the keyword (`like`) path before dropping expired/
# superseded ones in Python, so the post-filter still fills `limit` in the common
# case. The FULLTEXT path filters expiry in SQL and needs no headroom.
_EXPIRY_HEADROOM = 50
# How many similar currently-valid memories to hand the reconciler as conflict
# candidates. Bounds both the retrieval and the reconciler prompt size.
_RECONCILE_K = 8
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

# ── Semantic retrieval (MariaDB 11.7+ VECTOR column) ─────────────────────────
# Ranking is EXACT cosine over the scope-filtered, currently-valid candidate set.
# No VECTOR INDEX: that is HNSW, an approximate search, and after scope
# pre-filtering the candidate set is small enough that an exact scan costs
# nothing measurable (0.6 ms at 10,000 candidates on this hardware).
#
# Revisit when either bound below is crossed. The volume alert reads them. The
# next step at that point is still MariaDB (a VECTOR INDEX inside the same
# query), not an external vector store: keeping the filter and the ranking in
# one statement is the property that makes this design work.
REVISIT_SCOPE_ROWS = 10_000
REVISIT_TOTAL_ROWS = 500_000
# Candidates pulled per query before ranking in Python. Today a scope holds far
# fewer valid rows than this, so it is the whole candidate set.
_SEMANTIC_CANDIDATES = 200
# Share of the relevance score that comes from meaning when Processa Settings has
# no value. The rest comes from the FULLTEXT relevance score.
_DEFAULT_SEMANTIC_WEIGHT = 0.6
# Shares of the final score given to recency and to importance when Processa
# Settings has no value; relevance takes whatever is left.
_DEFAULT_RECENCY_WEIGHT = 0.2
_DEFAULT_IMPORTANCE_WEIGHT = 0.2
# Recency halves every this many days. A three-month-old memory keeps an eighth.
# ponytail: fixed half-life, make it a setting if one agent needs a different clock
_RECENCY_HALF_LIFE_DAYS = 30.0
_DEFAULT_IMPORTANCE = 3

# ── Provenance and trust ─────────────────────────────────────────────────────
SOURCE_TYPES = ("User Statement", "Agent Inference", "Tool Output")
_DEFAULT_SOURCE_TYPE = "Agent Inference"
# Starting confidence by source. Tool output is discouraged by default: a fact
# read off what a tool returned is one step further from anything a person
# said, so it starts low and loses ties against the other two.
# ponytail: fixed table, promote to settings if a site wants tool facts trusted more
_INITIAL_CONFIDENCE = {"User Statement": 0.9, "Agent Inference": 0.6, "Tool Output": 0.4}
# Added to confidence each time a later fact restates an existing one.
_CORROBORATION_BOOST = 0.1
# Effective confidence halves every this many days since the fact was last
# written or corroborated, so an old uncorroborated fact loses a tie to a new one.
_CONFIDENCE_HALF_LIFE_DAYS = 90.0
# A row that shares no keyword with the query must be at least this similar in
# meaning to be returned at all, or the semantic path would pad results with
# unrelated facts. all-MiniLM-L6-v2: related pairs score above 0.35, unrelated
# below 0.25.
# ponytail: fixed floor, make it a setting if a second model needs another value
_SEMANTIC_MIN_SIMILARITY = 0.3


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
	params = dict(filters, _q=query, _lim=int(limit), _now=now())
	# Only currently-valid memories: exclude superseded (expires_on set to now on
	# reconcile) and naturally-expired rows, so the most-recent fact wins.
	sql = f"""
		SELECT name, content, metadata,
		       MATCH(content) AGAINST (%(_q)s IN NATURAL LANGUAGE MODE) AS _score
		FROM `tabAI Memory`
		WHERE {conds}
		  AND MATCH(content) AGAINST (%(_q)s IN NATURAL LANGUAGE MODE)
		  AND (expires_on IS NULL OR expires_on > %(_now)s)
		ORDER BY _score DESC, modified DESC
		LIMIT %(_lim)s
	"""
	try:
		return frappe.db.sql(sql, params, as_dict=True)
	except Exception:
		return None


def _vector_supported() -> bool:
	"""True when the ``embedding`` VECTOR column exists (MariaDB 11.7+, added by
	``ai_memory.add_embedding_column``). One information_schema lookup."""
	try:
		return bool(frappe.db.has_column("AI Memory", "embedding"))
	except Exception:
		return False


def _setting_weight(fieldname: str, default: float) -> float:
	try:
		value = frappe.db.get_single_value("Processa Settings", fieldname)
	except Exception:
		value = None
	value = default if value is None else float(value)
	return min(max(value, 0.0), 1.0)


def _score_weights() -> dict:
	"""``{semantic, recency, importance}`` from Processa Settings, code defaults
	when blank. ``semantic`` splits the relevance score between meaning and
	keywords; ``recency`` and ``importance`` are shares of the final score, and
	relevance takes what is left of 1.0."""
	recency = _setting_weight("memory_recency_weight", _DEFAULT_RECENCY_WEIGHT)
	importance = _setting_weight("memory_importance_weight", _DEFAULT_IMPORTANCE_WEIGHT)
	if recency + importance > 1.0:
		total = recency + importance
		recency, importance = recency / total, importance / total
	return {
		"semantic": _setting_weight("memory_semantic_weight", _DEFAULT_SEMANTIC_WEIGHT),
		"recency": recency,
		"importance": importance,
	}


def _recency(modified, now) -> float:
	"""1.0 for a memory touched just now, halving every ``_RECENCY_HALF_LIFE_DAYS``."""
	if not modified:
		return 0.0
	age_days = max(0.0, (now - get_datetime(modified)).total_seconds() / 86400.0)
	return 0.5 ** (age_days / _RECENCY_HALF_LIFE_DAYS)


def _blend(rows: list[dict], weights: dict, now=None) -> list[dict]:
	"""Rank candidate rows by relevance, recency and importance.

	relevance  = ``semantic * meaning + (1 - semantic) * keyword``, where meaning
	             is ``1 - _dist`` (0 for a row with no embedding yet, so it keeps
	             its keyword score and stays findable) and keyword is ``_ft``
	             normalised by the best FULLTEXT score in the set.
	recency    = exponential decay of ``modified`` with a 30-day half-life.
	importance = ``(importance - 1) / 4``, so 1 scores 0 and 5 scores 1.
	score      = ``(1 - recency_w - importance_w) * relevance + recency_w * recency
	             + importance_w * importance``.

	A row with no keyword hit and a meaning similarity under
	``_SEMANTIC_MIN_SIMILARITY`` is dropped before scoring: recency and
	importance lift a relevant memory, they never make an unrelated one
	relevant. Pure function; the unit tests drive it directly."""
	now = now or now_datetime()
	semantic_w = weights.get("semantic", _DEFAULT_SEMANTIC_WEIGHT)
	recency_w = weights.get("recency", _DEFAULT_RECENCY_WEIGHT)
	importance_w = weights.get("importance", _DEFAULT_IMPORTANCE_WEIGHT)
	relevance_w = max(0.0, 1.0 - recency_w - importance_w)
	ft_max = max((float(r.get("_ft") or 0) for r in rows), default=0.0) or 1.0
	ranked = []
	for r in rows:
		meaning = 0.0 if r.get("_dist") is None else 1.0 - float(r["_dist"])
		keyword = float(r.get("_ft") or 0) / ft_max
		if keyword <= 0 and meaning < _SEMANTIC_MIN_SIMILARITY:
			continue
		relevance = semantic_w * meaning + (1.0 - semantic_w) * keyword
		importance = (min(5, max(1, int(r.get("importance") or _DEFAULT_IMPORTANCE))) - 1) / 4.0
		score = relevance_w * relevance + recency_w * _recency(r.get("modified"), now) + importance_w * importance
		ranked.append((score, r))
	ranked.sort(key=lambda pair: pair[0], reverse=True)
	return [r for _, r in ranked]


def _semantic_search(filters: dict, query: str, limit: int):
	"""Hybrid meaning-plus-keyword search inside one SQL statement.

	Scope and validity are filtered FIRST in SQL on the existing indexes; only
	the survivors are scored. A candidate is any valid in-scope row that has an
	embedding or matches the FULLTEXT query, so rows written before embeddings
	existed remain reachable by keyword. Returns ranked row dicts, or ``None``
	whenever the semantic path cannot run (no VECTOR column, embedding
	unavailable, SQL error) so the caller falls back to keyword ranking. Never
	raises.
	"""
	try:
		if not _vector_supported():
			return None
		from one_bpmn.agents.llm_provider.embedding import embed

		vectors = embed([query])
		if not vectors:
			return None
		conds = " AND ".join(f"`{col}` = %({col})s" for col in filters)
		params = dict(filters, _vec=json.dumps(vectors[0]), _q=query, _lim=_SEMANTIC_CANDIDATES, _now=now())
		sql = f"""
			SELECT name, content, metadata, modified, importance,
			       VEC_DISTANCE_COSINE(embedding, VEC_FromText(%(_vec)s)) AS _dist,
			       MATCH(content) AGAINST (%(_q)s IN NATURAL LANGUAGE MODE) AS _ft
			FROM `tabAI Memory`
			WHERE {conds}
			  AND (expires_on IS NULL OR expires_on > %(_now)s)
			  AND (embedding IS NOT NULL OR MATCH(content) AGAINST (%(_q)s IN NATURAL LANGUAGE MODE))
			ORDER BY _dist ASC, modified DESC
			LIMIT %(_lim)s
		"""
		rows = frappe.db.sql(sql, params, as_dict=True)
		return _blend(rows, _score_weights())[:limit]
	except Exception:
		frappe.logger("one_bpmn").warning(
			f"AI Memory: semantic search unavailable, using keyword ranking. {frappe.get_traceback()}"
		)
		return None


def store_embedding(name: str, content: str) -> bool:
	"""Embed ``content`` and store it on the row. Silent no-op (returns False)
	when the VECTOR column or the embedding model is unavailable; a row with no
	embedding is still found by the keyword paths. Shared with the backfill job."""
	if not _vector_supported():
		return False
	from one_bpmn.agents.llm_provider.embedding import embed

	vectors = embed([content])
	if not vectors:
		return False
	try:
		frappe.db.sql(
			"UPDATE `tabAI Memory` SET embedding = VEC_FromText(%s) WHERE name = %s",
			(json.dumps(vectors[0]), name),
		)
		return True
	except Exception:
		frappe.logger("one_bpmn").warning(f"AI Memory: could not store embedding for {name}. {frappe.get_traceback()}")
		return False


def memory_search(scope: str, scope_key, query: str, limit: int = 5, *, ignore_permissions: bool = False) -> list[dict]:
	"""Look up memories for exactly one scope key whose content matches ``query``.

	Returns up to ``limit`` results as ``[{name, content, metadata}]``, never from
	a different scope key. Ranking depends on the path taken:

	- Trusted dispatch (``ignore_permissions=True``) first tries the hybrid
	  semantic-plus-FULLTEXT ranking (``_semantic_search``), so a memory worded
	  differently from the query still surfaces. Needs the VECTOR column
	  (MariaDB 11.7+) and a working embedding model; otherwise it is skipped.
	- Trusted dispatch with indexable query tokens then
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

	# Hybrid semantic + FULLTEXT ranking, then FULLTEXT alone (both trusted
	# dispatch only: raw SQL cannot apply row permissions). A non-empty result
	# wins; empty/unavailable falls through to the next path.
	if ignore_permissions and query and query.strip():
		rows = _semantic_search(filters, query.strip(), page_length)
		if rows:
			return [_row_dict(r) for r in rows]
	if ignore_permissions and tokens:
		rows = _fulltext_search(filters, " ".join(tokens), page_length)
		if rows:
			return [_row_dict(r) for r in rows]

	# Keyword match: OR each query token against content. `filters` (scope) is
	# AND-ed with `or_filters` (the token match) by DatabaseQuery, so results
	# stay pinned to the exact scope key. Empty/short-only query -> recency list.
	#
	# The valid-only (expires_on) guard is a per-field disjunction (NULL OR future)
	# that can't share DatabaseQuery's single `or_filters` slot with the token
	# match, so we over-fetch and drop expired/superseded rows in Python. `filters`
	# is a dict, so copy it before adding fields we don't want to mutate upstream.
	or_filters = [["content", "like", f"%{tok}%"] for tok in tokens] or None
	rows = frappe.get_list(
		"AI Memory",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "content", "metadata", "expires_on"],
		order_by="modified desc",
		limit_page_length=page_length + _EXPIRY_HEADROOM,
		ignore_permissions=ignore_permissions,
	)
	cutoff = now_datetime()
	valid = [r for r in rows if not r.get("expires_on") or get_datetime(r["expires_on"]) > cutoff]
	return [_row_dict(r) for r in valid[:page_length]]


def memory_list_user_directed(scope: str, scope_key, limit: int = 3, *, ignore_permissions: bool = False) -> list[dict]:
	"""Currently-valid user-directed memories for exactly one scope key, most
	recent first — unconditionally, with no keyword/relevance filter.

	A standing convention the user asked to be remembered ("remember that...")
	won't share vocabulary with whatever the current turn happens to be about,
	so ``memory_search``'s FULLTEXT/``like`` matching can't be relied on to
	surface it — that is the recall gap this exists to close. Called alongside
	``memory_search``, not instead of it; the caller merges both result sets.
	"""
	filters = dict(_resolve_scope(scope, scope_key), user_directed=1)
	page_length = limit if isinstance(limit, int) and limit > 0 else _DEFAULT_LIMIT
	rows = frappe.get_list(
		"AI Memory",
		filters=filters,
		fields=["name", "content", "metadata", "expires_on"],
		order_by="modified desc",
		limit_page_length=page_length + _EXPIRY_HEADROOM,
		ignore_permissions=ignore_permissions,
	)
	cutoff = now_datetime()
	valid = [r for r in rows if not r.get("expires_on") or get_datetime(r["expires_on"]) > cutoff]
	return [_row_dict(r) for r in valid[:page_length]]


def _valid_rows(rows: list) -> list:
	"""Drop expired/superseded rows from a raw ``frappe.get_all`` result — the
	same currently-valid guard ``memory_search`` applies, exposed separately so a
	direct field lookup (not a keyword search) can reuse it."""
	cutoff = now_datetime()
	return [r for r in rows if not r.get("expires_on") or get_datetime(r["expires_on"]) > cutoff]


def _keyed_candidates(keys: dict, dedup_key: str | None) -> list[dict]:
	"""Currently-valid rows in scope sharing ``dedup_key`` — fetched by direct
	field lookup so they reach the reconciler (and the exact-duplicate check)
	even when their wording shares no tokens with the new content, which a
	keyword/FULLTEXT ``memory_search`` would otherwise miss entirely."""
	if not dedup_key:
		return []
	rows = frappe.get_all(
		"AI Memory",
		filters=dict(keys, dedup_key=dedup_key),
		fields=["name", "content", "metadata", "expires_on"],
		ignore_permissions=True,
	)
	return [_row_dict(r) for r in _valid_rows(rows)]


def trust_hierarchy() -> list[str]:
	"""Source types most trusted first: Processa Settings, else the code order."""
	try:
		text = frappe.db.get_single_value("Processa Settings", "memory_trust_hierarchy")
	except Exception:
		text = None
	order = [line.strip() for line in (text or "").splitlines() if line.strip()]
	return order or list(SOURCE_TYPES)


def _trust_rank(source_type: str | None, order: list[str] | None = None) -> int:
	"""Higher is more trusted; a source type not in the hierarchy ranks 0."""
	order = order or trust_hierarchy()
	if source_type in order:
		return len(order) - order.index(source_type)
	return 0


def _normalise_source_type(source_type: str | None, user_directed: bool) -> str:
	if source_type in SOURCE_TYPES:
		return source_type
	return "User Statement" if user_directed else _DEFAULT_SOURCE_TYPE


def effective_confidence(row: dict, now=None) -> float:
	"""Stored confidence decayed by age since the fact was last corroborated (or
	written), halving every ``_CONFIDENCE_HALF_LIFE_DAYS``."""
	now = now or now_datetime()
	confidence = float(row.get("confidence") or 0.0)
	anchor = row.get("last_corroborated") or row.get("modified")
	if not anchor:
		return confidence
	age_days = max(0.0, (now - get_datetime(anchor)).total_seconds() / 86400.0)
	return confidence * 0.5 ** (age_days / _CONFIDENCE_HALF_LIFE_DAYS)


def _resolve_conflict(action: str | None, supersedes: list, source_type: str, confidence: float) -> tuple[str | None, dict]:
	"""Apply the trust hierarchy to a reconciler decision.

	``replace`` (the new fact contradicts existing ones): an existing memory
	from a more trusted source, or an equally trusted one that is still more
	confident, wins; the new fact is rejected and nothing is invalidated.
	``update`` (the new fact restates existing ones): corroboration, so the
	surviving new row inherits the count plus one and a raised confidence.
	Returns ``(action, carry)``; ``carry`` holds field values for the new row."""
	if not supersedes:
		return action, {}
	rows = frappe.get_all(
		"AI Memory",
		filters={"name": ("in", list(supersedes))},
		fields=["name", "source_type", "confidence", "corroboration_count", "last_corroborated", "modified"],
	)
	if action == "replace":
		order = trust_hierarchy()
		new_rank = _trust_rank(source_type, order)
		for r in rows:
			old_rank = _trust_rank(r.get("source_type"), order)
			if old_rank > new_rank or (old_rank == new_rank and effective_confidence(r) > confidence):
				return "rejected_lower_trust", {"kept": r["name"]}
		return action, {}
	if action == "update":
		best = max([confidence] + [effective_confidence(r) for r in rows])
		return action, {
			"confidence": min(1.0, best + _CORROBORATION_BOOST),
			"corroboration_count": max([int(r.get("corroboration_count") or 0) for r in rows] + [0]) + 1,
			"last_corroborated": now_datetime(),
		}
	return action, {}


def _reconcile_and_invalidate(
	scope, scope_key, content, dedup_key, ctx, *, ignore_permissions, source_type=_DEFAULT_SOURCE_TYPE, confidence=None
) -> tuple[str | None, dict]:
	"""Reconcile ``content`` against the most similar currently-valid memories in
	the same scope and invalidate any it supersedes.

	Candidates are the union of (a) currently-valid rows sharing ``dedup_key`` —
	fetched directly, not by keyword match, so a same-topic restatement worded
	differently still surfaces — and (b) the existing scoped ``memory_search``
	keyword/FULLTEXT results, filling up to ``_RECONCILE_K`` after the ``dedup_key``
	rows are pinned first. Before any of that, an exact ``content`` match among the
	``dedup_key`` rows short-circuits the whole call: no LLM is invoked, so a
	reconciler failure can never let that specific duplicate through — the one
	case that used to guarantee an unwanted insert.

	Asks the configured chat model to decide add/update/replace for whatever
	wasn't short-circuited, and for each superseded memory sets ``expires_on =
	now`` via ``doc.save`` — NOT ``db.set_value`` — so the change is captured as a
	Frappe ``Version`` (free history; the row stays in the table).

	The trust hierarchy is applied to the decision (``_resolve_conflict``): a
	contradiction is only allowed to invalidate memories from a source no more
	trusted than the new fact's, and a restatement corroborates.

	Returns ``(action, carry)``: the reconciler action ("add"/"update"/
	"replace"), the sentinel ``"skipped_exact_duplicate"`` or
	``"rejected_lower_trust"`` (caller must insert nothing; ``carry["kept"]``
	names the memory that stood), or ``None`` when there is nothing to reconcile
	against. ``carry`` holds field values the new row inherits (corroboration).
	Never raises; the caller treats any problem as a plain insert.
	"""
	from one_bpmn.agents.memory.reconcile import reconcile as _reconcile

	keys = _resolve_scope(scope, scope_key)
	keyed = _keyed_candidates(keys, dedup_key)

	text = (content or "").strip()
	if any((c.get("content") or "").strip() == text for c in keyed):
		return "skipped_exact_duplicate", {}

	searched = memory_search(scope, scope_key, content, limit=_RECONCILE_K, ignore_permissions=True)
	seen = {c["name"] for c in keyed}
	candidates = list(keyed)
	for c in searched:
		if c["name"] not in seen and len(candidates) < _RECONCILE_K:
			seen.add(c["name"])
			candidates.append(c)

	if not candidates:
		return None, {}

	decision = _reconcile(
		content,
		candidates,
		provider_name=(ctx or {}).get("provider_name"),
		backend=(ctx or {}).get("backend") or "direct_api",
		model=(ctx or {}).get("model"),
	)

	degraded = decision.get("degraded")
	if degraded:
		# The LLM didn't genuinely decide — no model, no output, or a failed
		# call — so this "add" (or whatever action came back) is a fallback, not
		# a judgment. Surfaced two ways: an error log (this app's existing
		# visibility mechanism) and a running counter an admin can check without
		# combing logs.
		frappe.log_error(
			title="AI Memory: reconciliation degraded",
			message=f"reason={degraded} scope={scope} scope_key={scope_key}",
		)
		try:
			frappe.cache().hincrby("ai_memory:reconcile_degraded", degraded, 1)
		except Exception:
			pass

	action, carry = _resolve_conflict(
		decision.get("action"),
		decision.get("supersedes", []),
		source_type,
		_INITIAL_CONFIDENCE.get(source_type, 0.6) if confidence is None else confidence,
	)
	if action == "rejected_lower_trust":
		frappe.logger("one_bpmn").info(
			f"AI Memory: {source_type} fact rejected, contradicts a more trusted memory {carry.get('kept')} in {scope}"
		)
		return action, carry

	stamp = now_datetime()
	for name in decision.get("supersedes", []):
		try:
			old = frappe.get_doc("AI Memory", name)
			old.expires_on = stamp
			# ignore_version=False so the supersession is always captured as a
			# Frappe Version — preserving history is the point of invalidate-and-
			# insert, so we don't leave it to the ambient default (which suppresses
			# versions under frappe.flags.in_test).
			old.save(ignore_permissions=ignore_permissions, ignore_version=False)
		except Exception:
			frappe.log_error(
				title="AI Memory: invalidate superseded failed",
				message=frappe.get_traceback(),
			)
	return action, carry


def _screen_memory_content(content: str, scope: str, keys_source=None) -> str | None:
	"""Screen a memory before it is stored. ``None`` means do not store it.

	Screened against the site default rather than a specific agent's setting:
	this layer is reached from the distiller, the memory tool and direct server
	calls, and only some of those know which agent configuration is in play.
	Erring towards the default is the safe direction — the default is Flag, so
	the fact is still stored, minus the payload.

	Never raises. A screening fault must not lose a memory that would otherwise
	have been written.
	"""
	try:
		from one_bpmn.security.injection import screen_input

		result = screen_input(
			content,
			None,
			boundary="memory-write",
			raise_on_block=False,
		)
		if result.fired and result.action == "Block":
			frappe.logger("injection").warning(
				f"memory write dropped for scope={scope}: {result.summary()}"
			)
			return None
		return result.text
	except Exception:
		try:
			frappe.log_error(
				title="Memory write screening failed — memory stored unscreened",
				message=frappe.get_traceback(),
			)
		except Exception:
			pass
		return content


def memory_write(
	scope: str,
	scope_key,
	content: str,
	dedup_key: str | None = None,
	metadata: dict | None = None,
	source_run: str | None = None,
	*,
	ignore_permissions: bool = False,
	reconcile: bool = False,
	reconcile_ctx: dict | None = None,
	process_model: str | None = None,
	user_directed: bool = False,
	importance: int | None = None,
	source_type: str | None = None,
	confidence: float | None = None,
) -> dict:
	"""Save a memory for a scope key.

	With a ``dedup_key`` that already exists for the same scope + key(s), the
	existing record's content/metadata (and source_run) are overwritten in
	place instead of inserting a duplicate; without a ``dedup_key`` a new record
	is inserted. ``source_run`` records provenance (the AI Agent Run that wrote
	the memory). ``process_model`` records which process run produced the fact —
	it is NOT a scope key (Agent scope still keys strictly on ``agent_element``),
	just optional provenance carried alongside, the same way ``source_run`` is.

	``reconcile=True`` (the background note-taker path) layers write-time semantic
	reconciliation on top of ``dedup_key`` rather than replacing it: a
	``dedup_key``/exact-content match short-circuits straight to "insert nothing"
	(no LLM call, so a reconciler failure can't let that duplicate through
	either); otherwise the most similar currently-valid memories in scope
	(``dedup_key`` matches pinned first, then keyword/FULLTEXT search) are handed
	to the configured chat model (``reconcile_ctx={provider_name, backend,
	model}``), which decides add/update/replace. Superseded memories are
	invalidated (``expires_on = now``, kept for history) and a surviving new fact
	is inserted fresh, carrying ``dedup_key`` forward (the old overwrite-in-place
	lookup below is skipped when reconciling — invalidate-and-insert is the only
	semantics here). If reconciliation can't run (no model, no candidates, any
	error) it degrades to a plain insert — it never raises and never blocks the
	turn.

	Permissions: this writes as the caller's context. ``ignore_permissions=True``
	is the documented escape hatch for TRUSTED server-side dispatch only (the
	agent runs under a system context) — it must NEVER be passed from a
	whitelisted / HTTP-reachable method.

	``importance`` (1..5) is how much the fact matters when it competes for
	recall; the distiller sets it, ranking reads it. Left ``None`` on an insert
	the field default applies; on an overwrite the existing value is kept.

	``source_type`` is where the fact came from (``SOURCE_TYPES``); a
	``user_directed`` write defaults to "User Statement", anything else to
	"Agent Inference". ``confidence`` (0..1) defaults from the source type.
	Under ``reconcile=True`` the trust hierarchy decides a contradiction: a fact
	from a less trusted source than the memory it contradicts is not written and
	the standing memory is returned; a restatement corroborates, raising the
	surviving row's confidence and count.

	``user_directed=True`` marks a memory the user explicitly asked to be
	remembered (e.g. "remember that..."), as opposed to one an agent's output
	happened to produce. It is exempt from Log Settings auto-cleanup
	(``AIMemory.clear_old_logs``) and is recalled unconditionally by
	``memory_list_user_directed`` regardless of a later turn's keywords.

	Returns the resulting record as ``{name, content, metadata}``.
	"""
	# ── Injection screening before persistence ───────────────────────────
	# A memory is re-read on every later turn for its scope, so a payload that
	# reaches this function stops being a one-off message and becomes a standing
	# instruction — the one carrier where a single success buys the attacker
	# persistence. Screened here rather than in the distiller because THIS is the
	# function every write path goes through, including the memory tool.
	#
	# Nobody is waiting on a background writeback, so a Block drops the write
	# instead of raising: refusing here would surface as a failed job, not as an
	# answer to a person. Flag stores the fact with the payload cut out, because
	# a distilled memory usually carries something worth keeping alongside it.
	content = _screen_memory_content(content, scope, keys_source=scope_key)
	if content is None:
		return {}

	keys = _resolve_scope(scope, scope_key)
	source_type = _normalise_source_type(source_type, user_directed)
	if confidence is None:
		confidence = _INITIAL_CONFIDENCE.get(source_type, 0.6)
	confidence = min(1.0, max(0.0, float(confidence)))

	# Write-time reconciliation layers on top of dedup_key (see docstring): a
	# dedup_key/exact-content match short-circuits before any LLM call, and
	# whatever survives is always inserted fresh, carrying dedup_key forward.
	reconcile_action, carry = None, {}
	if reconcile:
		try:
			reconcile_action, carry = _reconcile_and_invalidate(
				scope,
				scope_key,
				content,
				dedup_key,
				reconcile_ctx,
				ignore_permissions=ignore_permissions,
				source_type=source_type,
				confidence=confidence,
			)
		except Exception:
			frappe.log_error(title="AI Memory: reconcile_and_invalidate failed", message=frappe.get_traceback())
			reconcile_action, carry = None, {}  # degrade: plain insert

		if reconcile_action == "rejected_lower_trust":
			# A more trusted memory holds the opposite; it stands and the new
			# fact is not written. Return the standing memory so the caller
			# still gets a row back.
			row = frappe.db.get_value("AI Memory", carry.get("kept"), ["name", "content", "metadata"], as_dict=True) or {}
			return {"name": row.get("name"), "content": row.get("content"), "metadata": _json_loads(row.get("metadata"))}

		if reconcile_action == "skipped_exact_duplicate":
			# The dedup_key/content match already holds this fact — inserting
			# again would recreate the exact duplication reconciliation exists to
			# prevent. The LLM was never on the critical path for this decision.
			found = frappe.get_all(
				"AI Memory", filters=dict(keys, dedup_key=dedup_key), fields=["name", "content", "metadata"], limit=1
			)
			row = found[0] if found else {}
			return {"name": row.get("name"), "content": row.get("content"), "metadata": _json_loads(row.get("metadata"))}

	if reconcile_action:
		metadata = dict(metadata or {}, reconcile_action=reconcile_action)
	metadata_json = json.dumps(metadata) if metadata is not None else None

	# The overwrite-by-dedup_key lookup below is the plain-write semantics
	# (mutate in place); reconciliation's semantics are invalidate-and-insert-
	# fresh, so the two must stay mutually exclusive on this DocType.
	existing = None
	if dedup_key and not reconcile:
		lookup = dict(keys, dedup_key=dedup_key)
		found = frappe.get_all("AI Memory", filters=lookup, pluck="name", limit=1)
		existing = found[0] if found else None

	if existing:
		doc = frappe.get_doc("AI Memory", existing)
		doc.content = content
		doc.metadata = metadata_json
		if source_run is not None:
			doc.source_run = source_run
		if process_model is not None:
			doc.process_model = process_model
		if user_directed:
			doc.user_directed = 1
		if importance is not None:
			doc.importance = min(5, max(1, int(importance)))
		doc.source_type = source_type
		doc.confidence = confidence
		doc.save(ignore_permissions=ignore_permissions)
		store_embedding(doc.name, content)
	else:
		# **keys already carries process_model for Process scope (it's the scope
		# key there); only add the kwarg on top when it's actually passed, so an
		# omitted process_model (the common case) can't clobber that with None.
		doc_fields = {
			"doctype": "AI Memory",
			**keys,
			"content": content,
			"dedup_key": dedup_key,
			"metadata": metadata_json,
			"source_run": source_run,
			"user_directed": 1 if user_directed else 0,
		}
		if process_model is not None:
			doc_fields["process_model"] = process_model
		if importance is not None:
			doc_fields["importance"] = min(5, max(1, int(importance)))
		doc_fields["source_type"] = source_type
		doc_fields["confidence"] = carry.get("confidence", confidence)
		if carry.get("corroboration_count"):
			doc_fields["corroboration_count"] = carry["corroboration_count"]
			doc_fields["last_corroborated"] = carry.get("last_corroborated")
		doc = frappe.get_doc(doc_fields)
		doc.insert(ignore_permissions=ignore_permissions)
		store_embedding(doc.name, content)

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
		"importance": {"type": "integer", "minimum": 1, "maximum": 5, "description": "Optional; how much the fact matters for recall, 1 minor to 5 critical."},
		"source_type": {"type": "string", "enum": list(SOURCE_TYPES), "description": "Optional; where the fact came from. Defaults to Agent Inference."},
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
	"Search durable agent memories for a given scope key by meaning and keyword; returns matching memories.",
	MEMORY_SEARCH_SCHEMA,
	memory_search,
)
_register_tool(
	"memory_write",
	"Persist a durable agent memory for a given scope key; can overwrite by dedup_key.",
	MEMORY_WRITE_SCHEMA,
	memory_write,
)
