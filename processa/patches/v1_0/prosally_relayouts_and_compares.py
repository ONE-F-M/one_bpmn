"""ProsAlly lays a saved diagram out again on request and lists what a pasted specification has that the diagram lacks.

Edits the live Classify Intent Server Script and the intent_classifier sub-prompt by anchor. Text that
already has its marker is left alone.
"""

import frappe

DASH = "\u2013"
AGENT_ID = "prosally_agent"
SCRIPT = f"ProsAlly {DASH} Tool Classify Intent"

# (anchor, replacement). Each anchor must appear exactly once.
SCRIPT_EDITS = (
	(
		"import asks_to_make_call_activity, ",
		"import asks_to_make_call_activity, compare_output, relayout_output, ",
	),
	(
		"\nif confirmed in _ACTION_INTENTS:\n",
		'\nif confirmed == "RELAYOUT":\n'
		'    _output = relayout_output(turn.get("current_xml", ""))\n'
		'    update_turn(context_docname, intent="RELAYOUT", confirmed=True, output=_output, done=True)\n'
		'    result["intent"] = "RELAYOUT"\n'
		'    result["modified"] = "bpmn_xml" in _output\n'
		'    result["next"] = "finalize"\n'
		"elif confirmed in _ACTION_INTENTS:\n",
	),
	(
		'frozenset({"IRRELEVANT"})',
		'frozenset({"IRRELEVANT", "RELAYOUT", "COMPARE"})',
	),
	(
		'    if intent == "IRRELEVANT":\n        result["next"] = "redirect"\n',
		'    if intent == "COMPARE":\n'
		"        update_turn(context_docname, output=compare_output(current_xml, _scope_texts), done=True)\n"
		'        result["next"] = "finalize"\n'
		'    elif intent == "IRRELEVANT":\n        result["next"] = "redirect"\n',
	),
)
SCRIPT_MARKER = "relayout_output"

PROMPT_EDITS = (
	(
		'- CRITICAL: When the user asks to "fix warnings"',
		'- CRITICAL: When the only complaint is the layout, for example "fix the spacing", "remove the crossing '
		'lines", "tidy the diagram" or overlapping shapes, with no step to add or change, classify as RELAYOUT, not '
		"MODIFY_EXISTING, and write the confirmation as laying the diagram out again with every step, arrow and "
		"setting kept.\n"
		"- CRITICAL: When the message pastes a list or specification and asks what is missing from the diagram, or "
		"to compare it with the diagram, classify as COMPARE even when a diagram exists, and do not treat the "
		"list as a request to draw.\n"
		'- CRITICAL: When the user asks to "fix warnings"',
	),
	(
		"or MODIFY_EXISTING, also write the confirmation message",
		"MODIFY_EXISTING, or RELAYOUT, also write the confirmation message",
	),
	("For AMBIGUOUS, INCOMPLETE, and IRRELEVANT, leave", "For AMBIGUOUS, INCOMPLETE, IRRELEVANT, and COMPARE, leave"),
	(
		"GENERATE_NEW|OVERWRITE_EXISTING|MODIFY_EXISTING|AMBIGUOUS|INCOMPLETE|IRRELEVANT",
		"GENERATE_NEW|OVERWRITE_EXISTING|MODIFY_EXISTING|RELAYOUT|COMPARE|AMBIGUOUS|INCOMPLETE|IRRELEVANT",
	),
)
PROMPT_MARKER = "classify as RELAYOUT"


def apply_edits(text, edits):
	"""The text with every edit applied, or None when an anchor is not found exactly once."""
	for anchor, replacement in edits:
		if text.count(anchor) != 1:
			return None
		text = text.replace(anchor, replacement)
	return text


def execute():
	original_user = frappe.session.user
	try:
		frappe.set_user("Administrator")
		if frappe.db.exists("Server Script", SCRIPT):
			doc = frappe.get_doc("Server Script", SCRIPT)
			if SCRIPT_MARKER not in (doc.script or ""):
				edited = apply_edits(doc.script or "", SCRIPT_EDITS)
				if edited is None:
					frappe.log_error(
						title="prosally_relayouts_and_compares: anchor not found",
						message="The Classify Intent script does not contain every expected anchor.",
					)
				else:
					doc.script = edited
					doc.save(ignore_permissions=True)
		name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
		if name:
			agent = frappe.get_doc("AI Agent Configuration", name)
			for row in agent.sub_prompts:
				if row.sub_agent_id != "intent_classifier" or PROMPT_MARKER in (row.prompt_text or ""):
					continue
				edited = apply_edits(row.prompt_text or "", PROMPT_EDITS)
				if edited is None:
					frappe.log_error(
						title="prosally_relayouts_and_compares: anchor not found",
						message="The intent_classifier prompt does not contain every expected anchor.",
					)
				else:
					row.prompt_text = edited
					agent.save(ignore_permissions=True)
	finally:
		frappe.set_user(original_user)
