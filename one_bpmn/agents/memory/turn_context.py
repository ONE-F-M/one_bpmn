# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""The platform's history step: what a chat turn already knows, assembled once.

Returns the prior transcript as real messages and the established facts as one
block. How an agent presents its own scratchpad stays in its map.
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import cint

# Heads the facts block in every chat prompt and in AI Agent Run transcripts.
ESTABLISHED_HEADER = "Established so far in this conversation:"

# Messages sent when the agent's configuration names no window.
DEFAULT_WINDOW = 20

# A fact longer than this is a document, not a decision, and stays out of the block.
FACT_MAX_CHARS = 600


def conversation_of(instance) -> str:
	"""The Chat Conversation this turn belongs to, or "" for anything else."""
	if getattr(instance, "context_doctype", "") != "Chat Conversation":
		return ""
	return str(getattr(instance, "context_docname", "") or "")


def load_history(
	conversation: str, limit: int = 0, token_budget=None, current_message: str = ""
) -> list[dict]:
	"""Prior messages: the summary of what aged out, then the tail, minus ``current_message``."""
	if not conversation:
		return []
	try:
		from one_bpmn.agents.memory.compaction import build_history

		history = build_history(
			conversation,
			limit=cint(limit) or DEFAULT_WINDOW,
			strip_html=True,
			token_budget=token_budget,
		)
		return _without_current_turn(history, current_message)
	except Exception:
		# History is an enhancement to the turn, never a precondition for it.
		frappe.log_error(
			title=f"Turn context: history load failed ({conversation})",
			message=frappe.get_traceback(),
		)
		return []


def _without_current_turn(history: list[dict], current_message: str) -> list[dict]:
	"""Drop a trailing user message that is this turn's own question."""
	current = (current_message or "").strip()
	if not current or not history:
		return history
	last = history[-1]
	if last.get("role") == "user" and str(last.get("content") or "").strip() == current:
		return history[:-1]
	return history


def established_block(conversation: str) -> str:
	"""What this conversation has already settled, or "" when nothing is recorded."""
	if not conversation:
		return ""
	try:
		from one_bpmn.agents.memory.session_state import get_state

		state = get_state(conversation)
	except Exception:
		frappe.log_error(
			title=f"Turn context: session_state read failed ({conversation})",
			message=frappe.get_traceback(),
		)
		return ""
	facts = established_facts(state)
	if not facts:
		return ""
	return f"{ESTABLISHED_HEADER}\n{json.dumps(facts, indent=2, default=str)}"


def established_facts(state: dict) -> dict:
	"""Scalars and short lists of scalars; nested working material stays with the scripts that read it."""
	facts = {}
	for key, value in state.items():
		if str(key).startswith("_"):
			continue
		if isinstance(value, (dict, tuple, set)):
			continue
		if isinstance(value, list) and any(isinstance(v, (dict, list)) for v in value):
			continue
		if value in (None, "", []):
			continue
		if len(json.dumps(value, default=str)) > FACT_MAX_CHARS:
			continue
		facts[key] = value
	return facts
