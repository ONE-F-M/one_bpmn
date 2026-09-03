"""
Conversation compaction: replace covered turns with a persisted summary.

A chat map rebuilds the history it sends on every single turn, by re-reading
the last N Chat Messages. That is why a long conversation costs more each time
it is used AND still loses its own beginning — the window slides forward, and
everything that falls off the back is simply gone.

Compaction fixes both halves at once. The messages that would fall off the back
are summarised ONCE into a Chat Conversation Summary, and from then on the
dispatch sends that summary plus the verbatim tail that follows it. A covered
message is never read again, so the cost of the covered range is paid once
rather than on every turn, and the thread keeps its beginning.

Two entry points, deliberately separate:

- ``build_history`` is the READ path. It is a drop-in replacement for the
  ``frappe.get_all("Chat Message", ...)`` block that each agent's "Build
  Context" Server Script currently open-codes, and it returns the same
  ``[{"role", "content"}]`` shape those scripts already produce.
- ``compact_conversation`` is the WRITE path. It generates a summary and stores
  it. Nothing in this module calls it automatically: WHEN to compact (count,
  time, and task-boundary triggers, and running it off the hot path) is a
  separate story. Until then it is called by hand, from a test, or from a
  Server Script.

Summaries CHAIN. Each new one absorbs the text of the one before it and points
at it through ``supersedes``, so only the newest summary is ever read and the
older ones remain as an audit trail.
"""

from __future__ import annotations

import re

import frappe
from frappe.utils import cint, now_datetime

SUMMARY_DOCTYPE = "Chat Conversation Summary"
MESSAGE_DOCTYPE = "Chat Message"
CONVERSATION_DOCTYPE = "Chat Conversation"

# The message types that make up the visible conversation. Matches what every
# Build Context script already filters on, so switching a script to this module
# cannot change which messages are considered.
VISIBLE_MESSAGE_TYPES = ("User", "Bot")

# How many recent messages stay verbatim when nothing says otherwise. Agents
# that already carry a chat_history_limit constant should pass it instead.
DEFAULT_KEEP_TAIL = 10

# Bound the prose handed to the summariser so one enormous conversation cannot
# produce a request that is refused for length.
_MAX_INPUT_CHARS = 24000

# A summary only pays for itself if it is materially smaller than the prose it
# replaces. Both guards below exist because a compaction that grows the prompt
# is worse than no compaction at all — it costs a model call AND loses detail.
#
# _MAX_SUMMARY_RATIO is the real defence and is checked against what the model
# actually wrote. The minimum below is only there to skip a call that cannot
# possibly clear it, so it is DERIVED from the other two constants rather than
# guessed: below this, even a summary written at the minimum output budget
# would exceed the ratio.
#
# It was hardcoded at 1500, which was calibrated against a summary written
# before the output budget scaled with its input — 966 characters replacing
# 1538. Once the budget was fixed the same job produced 363 characters for a
# comparable range, so 1500 was rejecting conversations that compact well. A
# derived bound cannot drift from its own reasoning that way.
_MAX_SUMMARY_RATIO = 0.5

# The summariser's output cap scales with what it is replacing rather than
# sitting at a flat ceiling, so it is never invited to write more prose than it
# is compacting. Floor and ceiling keep it sane at both extremes.
_SUMMARY_BUDGET_DIVISOR = 3
_MIN_SUMMARY_TOKENS = 150
_MAX_SUMMARY_TOKENS = 700

# Derived, not chosen: the smallest covered range where a minimum-length summary
# could still come in under _MAX_SUMMARY_RATIO.
_MIN_REPLACED_CHARS = int(_MIN_SUMMARY_TOKENS * 4 / _MAX_SUMMARY_RATIO)

# Shape attribute -> the Processa Settings field holding its site-wide default,
# mirroring dispatchers._MEMORY_MODEL_SETTINGS so the two read alike.
_COMPACTION_MODEL_SETTING = "default_compaction_model"

_SYSTEM_PROMPT = """You are compacting the early part of a conversation so it can
be dropped from the context window without losing what it established.

Write a summary that lets someone pick the conversation up cold. Keep:
- decisions made and the reasoning behind them
- facts, names, identifiers, numbers and preferences the user supplied
- anything the user asked for that has NOT been done yet
- corrections the user made, and what they corrected

Drop pleasantries, restatements, and anything already superseded by a later turn.

Write plain prose in the third person ("the user asked for...", "it was decided
that..."). Do not address the user. Do not add anything that was not said. If an
earlier summary is provided, fold it in and return ONE combined summary rather
than appending to it.

Be SUBSTANTIALLY shorter than the conversation you are compacting — aim for
about a third of its length. A summary the same size as the transcript has
saved nothing and is the one outcome to avoid."""

_USER_PROMPT = """{previous}Conversation to compact:
---
{transcript}
---
Write the combined summary now."""


def _strip_html(text: str) -> str:
	"""Chat Message text is stored with markup; a summariser should read prose.

	Mirrors the cleaner already inlined in Lumina's Build Context rather than
	inventing a second one.
	"""
	if not text:
		return ""
	clean = re.sub(r"<[^>]+>", " ", text)
	for entity, char in (
		("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
		("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " "),
	):
		clean = clean.replace(entity, char)
	return re.sub(r"\s+", " ", clean).strip()


def _chars_per_token() -> int:
	try:
		value = cint(frappe.db.get_single_value("Processa Settings", "token_estimator_chars_per_token"))
		return value if value > 0 else 4
	except Exception:
		return 4


def _role(message_type: str) -> str:
	return "user" if message_type == "User" else "assistant"


# ── Reading ─────────────────────────────────────────────────────────────────
def latest_summary(conversation: str) -> dict | None:
	"""The one summary that counts: the newest for this conversation.

	Older summaries in the chain are already folded into this one's text, so
	reading only the newest is both correct and the reason compaction does not
	grow more expensive the more often it runs.
	"""
	if not conversation:
		return None
	rows = frappe.get_all(
		SUMMARY_DOCTYPE,
		filters={"conversation": conversation},
		fields=["name", "summary", "covered_upto", "covered_count"],
		order_by="covered_upto desc",
		limit=1,
	)
	return rows[0] if rows else None


def _messages_after(conversation: str, covered_upto, limit: int | None = None) -> list[dict]:
	"""Visible messages strictly newer than ``covered_upto``, oldest first.

	Strictly newer is the whole guarantee: a message whose creation ties with
	the cursor is treated as already covered. A tie can therefore only drop one
	message from the tail, never re-send one that the summary already stands
	in for — and re-sending is the failure this story exists to prevent.
	"""
	filters = {
		"conversation": conversation,
		"message_type": ["in", list(VISIBLE_MESSAGE_TYPES)],
	}
	if covered_upto:
		filters["creation"] = [">", covered_upto]

	rows = frappe.get_all(
		MESSAGE_DOCTYPE,
		filters=filters,
		fields=["name", "text", "message_type", "creation"],
		# Newest-first with a limit, then reversed: taking the LAST n rows means
		# the database does the trimming. Ordering ascending and slicing in
		# Python would read the whole conversation to throw most of it away.
		order_by="creation desc",
		limit=limit,
	)
	rows.reverse()
	return rows


def resolve_token_budget(conversation: str) -> int:
	"""The agent's context token budget, or the site default, or 0 for none.

	Resolved HERE rather than passed in by each caller, so an agent's Build
	Context script needs no change to gain a budget — the maps travel by export
	and asking every agent to be re-exported to pick up a platform setting would
	make the setting nearly impossible to roll out.
	"""
	if not conversation:
		return 0
	try:
		mode = frappe.db.get_value(CONVERSATION_DOCTYPE, conversation, "agent_mode")
		budget = 0
		if mode:
			budget = cint(
				frappe.db.get_value(
					"AI Agent Configuration", {"chat_mode_label": mode}, "context_token_budget"
				)
			)
		if budget > 0:
			return budget
		return cint(frappe.db.get_single_value("Processa Settings", "default_context_token_budget"))
	except Exception:
		# A budget that cannot be read must not stop history being assembled —
		# the thread still works, it is simply untrimmed, which is what happened
		# before this setting existed.
		return 0


def build_history(
	conversation: str,
	limit: int = DEFAULT_KEEP_TAIL,
	*,
	strip_html: bool = False,
	summary_role: str = "user",
	token_budget: int | None = None,
) -> list[dict]:
	"""The history to send this turn: the summary, then the verbatim tail.

	Drop-in replacement for the open-coded Chat Message query in an agent's
	Build Context script — same ``[{"role", "content"}]`` output, same message
	types, same oldest-first order.

	``limit`` counts the VERBATIM messages, not the summary. An agent asking for
	10 gets its 10 most recent turns whether or not a summary exists, so turning
	compaction on never silently shortens what the agent can see.

	``token_budget`` caps the assembled history by estimated size as well as by
	message count. ``None`` resolves it from the agent (then the site default);
	0 disables it. The summary is never dropped to fit — it stands in for every
	message it replaced.

	Returns ``[]`` for an unknown conversation, exactly as the query it replaces
	would.
	"""
	if not conversation:
		return []

	summary = latest_summary(conversation)
	covered_upto = summary["covered_upto"] if summary else None
	rows = _messages_after(conversation, covered_upto, limit=limit)

	history: list[dict] = []
	if summary and (summary.get("summary") or "").strip():
		history.append(
			{
				"role": summary_role,
				"content": "Summary of the earlier conversation:\n"
				+ summary["summary"].strip(),
			}
		)

	for row in rows:
		text = row.get("text") or ""
		if not text:
			continue
		history.append(
			{
				"role": _role(row.get("message_type")),
				"content": _strip_html(text) if strip_html else text,
			}
		)

	budget = resolve_token_budget(conversation) if token_budget is None else int(token_budget)
	if budget > 0:
		from one_bpmn.agents.memory.conversation_store import ContextWindowPolicy

		# max_messages=0 because the caller's ``limit`` has already applied the
		# count limit at the database. This pass is purely the size limit, and
		# the summary rides in `protected` so a budget can never discard it.
		policy = ContextWindowPolicy(max_messages=0, max_tokens=budget,
		                             chars_per_token=_chars_per_token())
		protected = history[:1] if summary else []
		history = policy._trim_to_budget(protected, history[len(protected):])
	return history


def needs_compaction(conversation: str, keep_tail: int = DEFAULT_KEEP_TAIL) -> bool:
	"""True when there is uncovered history beyond the verbatim tail.

	Exposed for the triggers story to call; nothing in this module acts on it.
	"""
	if not conversation or keep_tail is None or keep_tail < 0:
		return False
	summary = latest_summary(conversation)
	covered_upto = summary["covered_upto"] if summary else None
	filters = {
		"conversation": conversation,
		"message_type": ["in", list(VISIBLE_MESSAGE_TYPES)],
	}
	if covered_upto:
		filters["creation"] = [">", covered_upto]
	return frappe.db.count(MESSAGE_DOCTYPE, filters) > keep_tail


# ── Model resolution ────────────────────────────────────────────────────────
def resolve_compaction_model(explicit: str | None = None, fallback: str | None = None) -> str | None:
	"""Explicit choice, then the site-wide default, then the caller's fallback.

	The same three-step shape as ``dispatchers._memory_model``, for the same
	reason: summarising is a cheap, high-volume job that should not be billed at
	the rate of the agent's own reasoning model, but it must still work on a
	site where nobody has configured anything.

	The Model Routing epic will eventually own this choice; when it does, only
	this function changes.
	"""
	if explicit and str(explicit).strip():
		return str(explicit).strip()
	try:
		default = frappe.db.get_single_value("Processa Settings", _COMPACTION_MODEL_SETTING)
		if default:
			return default
	except Exception:
		# A missing or unreadable setting must never be the reason a
		# conversation cannot be compacted.
		pass
	return fallback or None


def _resolve_agent_id(conversation: str) -> str | None:
	"""The agent that owns this conversation, derived rather than passed in.

	A conversation already records which agent it belongs to, so requiring the
	caller to repeat it just means the field is blank whenever somebody compacts
	by hand — which is every caller today, and was.

	``Chat Conversation.agent_mode`` holds the agent's chat label ("Docu"), so
	the agent_id is one lookup away. The label is kept as the fallback: a
	conversation for an agent whose configuration has since been renamed or
	removed should still record what it was, rather than nothing.
	"""
	if not conversation:
		return None
	try:
		mode = frappe.db.get_value(CONVERSATION_DOCTYPE, conversation, "agent_mode")
		if not mode:
			return None
		return frappe.db.get_value(
			"AI Agent Configuration", {"chat_mode_label": mode}, "agent_id"
		) or mode
	except Exception:
		return None


def _summary_token_budget(replaced_chars: int) -> int:
	"""An output cap proportionate to the input, not a flat ceiling."""
	target = (replaced_chars // 4) // _SUMMARY_BUDGET_DIVISOR
	return max(_MIN_SUMMARY_TOKENS, min(target, _MAX_SUMMARY_TOKENS))


def _provider_for_model(model: str | None, fallback: str | None) -> str | None:
	"""The provider that serves ``model`` — a model only works against the
	credentials that serve it, so the two are resolved together."""
	if not model:
		return fallback
	try:
		provider = frappe.db.get_value("AI Model", {"model_name": model}, "provider")
		if provider:
			return provider
	except Exception:
		pass
	return fallback


# ── Writing ─────────────────────────────────────────────────────────────────
def _render_transcript(rows: list[dict]) -> str:
	lines = []
	for row in rows:
		who = "User" if row.get("message_type") == "User" else "Assistant"
		text = _strip_html(row.get("text") or "")
		if text:
			lines.append(f"{who}: {text}")
	return "\n".join(lines)


def _summarise(transcript: str, previous: str, *, model: str, provider_name: str | None,
               backend: str, max_tokens: int = _MAX_SUMMARY_TOKENS) -> str | None:
	"""One LLM call. Returns None on any failure — the caller must then leave
	the conversation uncompacted rather than store a summary it cannot trust."""
	from one_bpmn.agents.executor import (
		ErrorCode,
		ExecutorConfig,
		ExecutorContext,
		get_executor,
	)
	from one_bpmn.agents.executor.direct_api import DirectApiExecutor  # noqa: F401

	previous_block = ""
	if previous:
		previous_block = f"Earlier summary to fold in:\n---\n{previous.strip()}\n---\n\n"

	config = ExecutorConfig(
		backend=backend or "direct_api",
		provider_name=provider_name,
		model=model,
		system_prompt=_SYSTEM_PROMPT,
		user_prompt=_USER_PROMPT.format(
			previous=previous_block, transcript=transcript[:_MAX_INPUT_CHARS]
		),
		temperature=0.0,
		max_tokens=max_tokens,
	)
	result = get_executor(config.backend)().run(config, ExecutorContext())
	if result.error_code != ErrorCode.SUCCESS:
		frappe.log_error(
			title="Conversation compaction: summariser returned an error",
			message=f"model={model} provider={provider_name} error={result.error_message}",
		)
		return None
	text = result.output if isinstance(result.output, str) else str(result.output or "")
	return text.strip() or None


def compact_conversation(
	conversation: str,
	*,
	keep_tail: int = DEFAULT_KEEP_TAIL,
	model: str | None = None,
	provider_name: str | None = None,
	backend: str = "direct_api",
	agent_id: str | None = None,
	min_replaced_chars: int = _MIN_REPLACED_CHARS,
) -> dict:
	"""Summarise everything before the last ``keep_tail`` messages and store it.

	Returns ``{"compacted": bool, "reason"|"summary": ..., ...}``. Never raises:
	a conversation that cannot be compacted must keep working uncompacted, which
	it does — ``build_history`` simply finds no newer summary and sends what it
	always sent.

	Idempotent by construction. The covered range is defined by the cursor on
	the newest summary, so calling this twice with no new messages in between
	finds nothing left to cover and does nothing the second time.

	``min_replaced_chars`` is how much prose must be at stake before a summary
	can pay for itself. An agent whose turns are habitually one line may want it
	lower; the default assumes conversations worth compacting have real text in
	them.
	"""
	if not conversation or not frappe.db.exists(CONVERSATION_DOCTYPE, conversation):
		return {"compacted": False, "reason": "unknown conversation"}
	if keep_tail is None or keep_tail < 0:
		return {"compacted": False, "reason": "invalid keep_tail"}

	previous = latest_summary(conversation)
	covered_upto = previous["covered_upto"] if previous else None

	# Everything not yet covered, oldest first. No limit: the point is to find
	# what is ABOVE the tail, which a limit would hide.
	uncovered = _messages_after(conversation, covered_upto, limit=None)
	to_cover = uncovered[:-keep_tail] if keep_tail else uncovered
	if not to_cover:
		return {
			"compacted": False,
			"reason": "nothing above the tail to compact",
			"uncovered": len(uncovered),
		}

	transcript = _render_transcript(to_cover)
	if not transcript:
		return {"compacted": False, "reason": "covered range has no readable text"}

	# What this compaction would actually replace: the covered messages, plus the
	# summary being absorbed (which stops being sent once this one exists).
	previous_text = (previous or {}).get("summary") or ""
	replaced_chars = len(transcript) + len(previous_text)
	if replaced_chars < min_replaced_chars:
		# Not a failure — there simply is not enough prose here for a summary to
		# be smaller than the thing it replaces. Checked BEFORE the model call so
		# a doomed compaction costs nothing.
		return {
			"compacted": False,
			"reason": "too little text to be worth compacting",
			"replaced_chars": replaced_chars,
			"minimum": min_replaced_chars,
		}

	model = resolve_compaction_model(model)
	if not model:
		# Deliberately visible rather than silent: an unconfigured site should
		# discover this from the log, not from context costs that never fall.
		frappe.log_error(
			title="Conversation compaction skipped (no model configured)",
			message=(
				f"conversation={conversation} — set a Default Compaction Model on "
				f"Processa Settings or pass one explicitly."
			),
		)
		return {"compacted": False, "reason": "no model configured"}

	provider_name = _provider_for_model(model, provider_name)

	try:
		summary_text = _summarise(
			transcript,
			previous_text,
			model=model,
			provider_name=provider_name,
			backend=backend,
			max_tokens=_summary_token_budget(replaced_chars),
		)
	except Exception:
		frappe.log_error(
			title="Conversation compaction failed", message=frappe.get_traceback()
		)
		return {"compacted": False, "reason": "summariser raised"}

	if not summary_text:
		return {"compacted": False, "reason": "summariser produced nothing"}

	# Backstop for the case the budget did not prevent: a summary that is not
	# meaningfully smaller than what it replaces would make every future turn
	# BIGGER while also losing detail. Storing it would be strictly worse than
	# doing nothing, so it is discarded and the conversation stays uncompacted.
	if len(summary_text) > replaced_chars * _MAX_SUMMARY_RATIO:
		return {
			"compacted": False,
			"reason": "summary was not smaller than the text it replaces",
			"summary_chars": len(summary_text),
			"replaced_chars": replaced_chars,
		}

	last = to_cover[-1]
	doc = frappe.get_doc(
		{
			"doctype": SUMMARY_DOCTYPE,
			"conversation": conversation,
			"agent_id": agent_id or _resolve_agent_id(conversation),
			"summary": summary_text,
			"covered_from": to_cover[0]["name"],
			"covered_to": last["name"],
			"covered_upto": last["creation"],
			# The chain's count is cumulative: this summary stands in for its
			# own range AND everything the summary it absorbs stood in for.
			"covered_count": len(to_cover) + ((previous or {}).get("covered_count") or 0),
			"supersedes": (previous or {}).get("name"),
			"model": model,
			"provider": provider_name,
			"generated_on": now_datetime(),
		}
	)
	doc.insert(ignore_permissions=True)

	return {
		"compacted": True,
		"summary_name": doc.name,
		"covered_count": len(to_cover),
		"covered_upto": str(last["creation"]),
		"tail_kept": len(uncovered) - len(to_cover),
		"model": model,
		# The point of the exercise, reported rather than assumed: how much
		# smaller every subsequent turn's history became.
		"replaced_chars": replaced_chars,
		"summary_chars": len(summary_text),
		"saved_chars": replaced_chars - len(summary_text),
	}
