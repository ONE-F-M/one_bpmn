# Copyright (c) 2026, one-fm and contributors
# Scheduled conversation, memory and model jobs.
#
# Registered in hooks.py under scheduler_events.

import frappe
from frappe import _
from frappe.utils import add_to_date, now_datetime



# 3. Stale chat instance cleanup — close abandoned chat conversations


# A chat instance's `modified` timestamp advances on every engine pass
# (message received, AI reply, close). An instance untouched for this many
# hours is an abandoned conversation whose panel never sent the close call
# (tab closed mid-session, or a fire-and-forget close request that died).
STALE_CHAT_HOURS = 24


def close_stale_chat_instances():
	"""
	Deliver ``ChatConversation_Close_Action`` to chat-driven BPMN Process
	Instances that have been idle past ``STALE_CHAT_HOURS``, so their diagram
	runs the close branch (Cleanup → Conversation Ended) and completes.

	Called hourly by the Frappe scheduler.

	Chat process maps park at an event-based gateway waiting for the next
	user message or a close message. The close message normally comes from
	the UI (end_chat_conversation) when the panel closes — this sweep is the
	backstop for instances the UI orphaned.

	Instances mid-engine-pass or waiting on an AI job are skipped; if one is
	parked somewhere other than the close catch event (e.g. suspended for
	human input), the "no task waiting" error is swallowed and it is left
	untouched.

	The message is delivered to each stale instance directly — NOT via
	close_conversation(), whose by-conversation get_value lookup picks an
	arbitrary Active instance when several share one conversation and could
	close a fresh sibling instead of the stale one.
	"""
	cutoff = add_to_date(now_datetime(), hours=-STALE_CHAT_HOURS)

	stale = frappe.get_all(
		"BPMN Process Instance",
		filters={
			"status": "Active",
			"context_doctype": "Chat Conversation",
			"engine_in_progress": 0,
			"waiting_for_ai": 0,
			"modified": ["<", cutoff],
		},
		pluck="name",
	)

	for instance_name in stale:
		try:
			instance = frappe.get_doc("BPMN Process Instance", instance_name)
			instance.receive_message("ChatConversation_Close_Action", payload={})
			if instance.context_docname:
				from one_bpmn.api.skill_tools import clear_conversation_skills
				clear_conversation_skills(instance.context_docname)
		except frappe.ValidationError:
			pass  # not parked at the close catch event — leave it alone
		except Exception:
			frappe.log_error(
				title=f"BPMN stale chat cleanup failed: {instance_name}",
				message=frappe.get_traceback(),
			)


def sweep_conversation_retention():
	"""Daily: archive or delete chat conversations idle past their TTL.

	Off unless an administrator sets a TTL on Processa Settings, so a site that
	has not asked for retention does nothing beyond one settings read.
	"""
	from one_bpmn.agents.memory import retention

	try:
		result = retention.sweep_expired_conversations()
		if result.get("swept"):
			frappe.logger("one_bpmn").info(
				f"Conversation retention: {result['action']}d {result['swept']} conversation(s)"
			)
	except Exception:
		frappe.log_error(
			title="Conversation retention sweep failed", message=frappe.get_traceback()
		)


def apply_due_model_rates():
	"""Daily: apply any model rate whose effective date has passed.

	Folding pricing onto AI Model left one rate per model and no date, so a
	published price rise had nowhere to be recorded in advance and depended on
	somebody remembering it. The catalogue carries the dated changes; this is
	what makes them happen. A no-op on any day nothing is due, and it will not
	touch a rate that does not still match the exact published one it replaces.
	"""
	from one_bpmn.one_bpmn.patches.v1_0.seed_ai_model_catalogue import apply_due_rates

	try:
		for line in apply_due_rates():
			frappe.logger("one_bpmn").info(f"AI Model rate applied: {line}")
	except Exception:
		frappe.log_error(title="Model rate update failed", message=frappe.get_traceback())


def compact_idle_conversations():
	"""Hourly: the TIME trigger for conversation compaction.

	The count and turn-boundary triggers hang off the chat message hook, but an
	idle conversation by definition produces no messages — so the one trigger
	that cannot be a hook is a sweep. It queues exactly the same background job
	the other two do.

	Does nothing at all unless some agent has an idle threshold configured.
	"""
	from one_bpmn.agents.memory import compaction_triggers

	try:
		result = compaction_triggers.sweep_idle_conversations()
		if result.get("queued"):
			frappe.logger("one_bpmn").info(
				f"Conversation compaction: queued {result['queued']} of "
				f"{result['considered']} idle conversations"
			)
	except Exception:
		frappe.log_error(
			title="Conversation compaction: idle sweep failed",
			message=frappe.get_traceback(),
		)


def chase_unanswered_clarifications():
	"""Hourly: nudge a question nobody has answered, then raise it.

	WI-002050. It never answers the question. Every source on human-in-the-loop
	work says the same thing — do not block forever, and do not proceed on a
	timeout — so this does the first half (somebody is told) and deliberately
	not the second (nothing is assumed). The agent stays blocked, which is the
	whole point of having asked.
	"""
	from one_bpmn.agents import clarification

	try:
		result = clarification.chase_unanswered()
		if result.get("reminded") or result.get("escalated"):
			frappe.logger("one_bpmn").info(
				f"AI clarifications: reminded {result['reminded']}, escalated {result['escalated']}"
			)
	except Exception:
		frappe.log_error(
			title="AI Clarification: chasing unanswered questions failed",
			message=frappe.get_traceback(),
		)


def check_ai_model_credentials():
	"""WI-002191: every 15 minutes. Re-checks every enabled model's key — a
	pass lifts the block on a model that was Unhealthy, a credential failure
	marks one nobody has tried to run yet — then alerts once per model per
	distinct problem. Probe first, so an alert describes the current state."""
	from one_bpmn.agents import model_health

	model_health.probe_enabled_models()
	model_health.alert_unhealthy_models()


def prune_ai_memory():
	"""Nightly. Retires decayed, never-corroborated and minor aged memories by
	setting expires_on, with the reason in metadata. Thresholds live on
	Processa Settings, AI Memory section; the rows stay for audit."""
	from one_bpmn.agents.memory.prune import prune_memories

	prune_memories()
def check_ai_memory_volume():
	"""Daily. Tells the platform team when AI Memory has grown past the point
	where exact (index-free) semantic ranking should be reconsidered. The
	thresholds live on Processa Settings, AI Memory section."""
	from one_bpmn.agents.memory.volume_alert import check_volume

	check_volume()
