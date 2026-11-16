# Copyright (c) 2026, one-fm and contributors
"""LuCrusher records the links between processes and drafts them as message, signal and call activity objects.

Edits the topology, migration task and ProsAlly prompt skills. A skill that already carries its
marker is left as it is, and one whose anchor moved is reported and not written.
"""

import frappe

from processa.patches.v1_0.lucrusher_prosally_follows_code_and_workflow import apply_edits
from processa.patches.v1_0.seed_lucrusher_skills import PROSALLY_SKILL, TASKS_SKILL, TOPOLOGY_SKILL

R5 = '- R5: Names use "Verb Noun", for example "Submit Leave Request".'
RECOMMEND = '3. Recommend "1:1" or "1:Many".'
CATCH = "- IntermediateCatchEvent (Message): waits for an inbound message."
MESSAGE = (
	"- MESSAGE: one per external integration (SendTask or ReceiveTask). "
	"Give the message name, direction, payload and existing code."
)
ELEMENT_TYPES = "IntermediateCatchEvent, EndEvent."
RULES_HEADING = "## Rules\n"

TOPOLOGY_EDITS = [
	(
		R5,
		R5
		+ "\n- R6: A link is a message (a hand-off to a process that is already running), a call activity "
		"(a parent starts a child and waits) or a signal (a broadcast inside one process instance only). "
		"A signal never crosses to another process.",
	),
	(
		RECOMMEND,
		'3. Recommend "1:1" or "1:Many", and list each link in the summary as "A -> B: mechanism, name". '
		"Take links from the links field of read_doctype_logic and from related maps found with "
		"search_processes_on_production.",
	),
]

TASKS_EDITS = [
	(
		CATCH,
		CATCH
		+ "\n- IntermediateThrowEvent (Message or Signal): sends a message or broadcasts a signal."
		"\n- IntermediateCatchEvent (Signal): waits for a signal thrown in the same process instance."
		"\n- CallActivity: starts another process map as a child and waits for it; called_process_id names the map.",
	),
	(
		MESSAGE,
		MESSAGE
		+ "\n- LINK: one per link in the topology. Give the mechanism (Message, Call Activity or Signal), "
		"the name, the sender and receiver process, the payload and the existing code as file:method.",
	),
]

LINKS_SECTION = """## Cross-process links
Draw every link in the topology with the object that matches its mechanism.
- Call Activity when a parent starts a child and waits for it. Its config carries called_process_id.
- Message when a process hands off to one that is already running: a SendTask or IntermediateThrowEvent in the sender, a ReceiveTask or IntermediateCatchEvent in the receiver, both with the identical message name.
- Signal throw and catch only inside one process. A signal never reaches another process.
- Name the other process by its process_id from the topology, even when its block is not drafted yet.
- In section E: every throw has a catch with the same name, every call activity names a process_id from the topology, and no signal crosses processes.

"""

PROSALLY_EDITS = [
	(ELEMENT_TYPES, "IntermediateCatchEvent, IntermediateThrowEvent, CallActivity, EndEvent."),
	(RULES_HEADING, LINKS_SECTION + RULES_HEADING),
]

SKILL_EDITS = [
	(TOPOLOGY_SKILL, "- R6:", TOPOLOGY_EDITS),
	(TASKS_SKILL, "- LINK:", TASKS_EDITS),
	(PROSALLY_SKILL, "## Cross-process links", PROSALLY_EDITS),
]


def execute():
	for skill_name, marker, edits in SKILL_EDITS:
		_patch_skill(skill_name, marker, edits)


def _patch_skill(skill_name, marker, edits):
	name = frappe.db.get_value("AI Skill", {"skill_name": skill_name}, "name")
	if not name:
		return
	body = frappe.db.get_value("AI Skill", name, "body") or ""
	patched = apply_edits(body, edits, marker)
	if patched != body:
		frappe.db.set_value("AI Skill", name, "body", patched)
	elif marker not in body:
		frappe.log_error(
			title=f"lucrusher_drafts_cross_process_links: {skill_name} anchor not found",
			message=f"Skill {skill_name} no longer matches the text this patch edits; apply the change by hand.",
		)
