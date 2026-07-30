"""
WI-001630: stop AI Agent memory threads masquerading as General Chat.

An AI Agent Task with ``aiConversationStore="document_store"`` persists its own
transcript as a Chat Conversation titled ``one_bpmn:<instance>:<bpmn_id>``. The
store inserted those without an ``agent_mode`` — and Chat Conversation.agent_mode
is a Data field whose DEFAULT is "General Chat".

That was harmless while General Chat had no process map. The moment it got one,
its After-Insert start trigger (``agent_mode == "General Chat"``) began firing on
every memory thread every agent wrote — Docu, Logix, ProsAlly and LuCrusher
included — spawning a phantom General Chat instance per agent turn. Each phantom
parks at "Waiting for User Message" and never receives one, so it never closes:
the symptom is two instances per chat where only one ever completes.

``conversation_store`` now stamps ``AGENT_MEMORY_MODE`` on new threads. This
repairs the ones already written:

  1. Re-stamp every ``one_bpmn:%`` thread so no future deploy re-triggers on it.
  2. Finalise the phantom instances those threads spawned, through the diagram
     rather than behind its back: each is parked at its wait gateway, so
     delivering ``ChatConversation_Close_Action`` runs the map's own close branch
     (Cleanup -> Conversation Ended) and the instance reaches Completed.

Real user conversations are untouched — the title prefix is the discriminator and
only the memory store writes it. Idempotent.
"""

import frappe

from one_bpmn.agents.memory.conversation_store import AGENT_MEMORY_MODE

TITLE_PREFIX = "one_bpmn:"


def execute():
	original_user = frappe.session.user
	try:
		frappe.set_user("Administrator")

		threads = frappe.get_all(
			"Chat Conversation",
			filters={"title": ["like", f"{TITLE_PREFIX}%"]},
			fields=["name", "agent_mode"],
		)
		if not threads:
			return

		restamped = 0
		for thread in threads:
			if thread.agent_mode != AGENT_MEMORY_MODE:
				frappe.db.set_value(
					"Chat Conversation",
					thread.name,
					"agent_mode",
					AGENT_MEMORY_MODE,
					update_modified=False,
				)
				restamped += 1

		# Retire the phantoms. Closing through the diagram keeps the engine's own
		# bookkeeping honest; a direct status write would leave a half-finished
		# workflow_state behind.
		closed, stuck = 0, []
		for thread in threads:
			instances = frappe.get_all(
				"BPMN Process Instance",
				filters={
					"context_doctype": "Chat Conversation",
					"context_docname": thread.name,
					"status": ["in", ["Active", "Queued"]],
				},
				pluck="name",
			)
			for inst_name in instances:
				try:
					instance = frappe.get_doc("BPMN Process Instance", inst_name)
					instance.receive_message("ChatConversation_Close_Action", payload={})
					closed += 1
				except frappe.ValidationError:
					# Not parked on the close event — leave it rather than force it.
					stuck.append(inst_name)
				except Exception:
					stuck.append(inst_name)
					frappe.log_error(
						title=f"Agent memory phantom close failed: {inst_name}",
						message=frappe.get_traceback(),
					)

		frappe.db.commit()

		if restamped or closed or stuck:
			frappe.log_error(
				title="Agent memory threads repaired (WI-001630)",
				message=(
					f"threads re-stamped: {restamped}\n"
					f"phantom instances closed: {closed}\n"
					f"phantom instances left for review: {stuck}"
				),
			)
	finally:
		frappe.set_user(original_user)
