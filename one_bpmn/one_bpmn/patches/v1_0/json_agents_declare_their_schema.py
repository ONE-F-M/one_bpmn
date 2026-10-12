"""The Logix classifier and clarifier and the Error Log Ticket Agent stop asking for JSON in prose.

Their shapes declare an aiResponseSchema, which the executor sends as the provider's structured output,
so the prompts keep what each field means and drop the "Respond with ONLY a JSON object" lines. The
Error Log Ticket Triage schema also lists ticket_name as required, which OpenAI strict mode needs.
Each anchor must be found exactly once; anything else is logged and left as it is.
"""

import frappe

PROMPT_EDITS = {
	"logix_intent_classifier": (
		"\n\nRespond with ONLY a JSON object \u2014 no other text:\n"
		'{"intent": "CREATE|MODIFY|DISAMBIGUATE", "shape_kind": "script_task|agent_tool", '
		'"next": "clarify|write_script|write_agent_tool"}',
		"",
	),
	"logix_clarifier": (
		"Respond with ONLY a JSON object \u2014 no other text:\n"
		'{"question": "your plain-English question", "options": ["option1", "option2", ...]}',
		'Put the question in "question" and the 2-4 choices in "options".',
	),
	"error_log_ticket_agent": (
		'Respond with ONLY a JSON object matching the schema you were given: {"decision": "match" or '
		'"no_match", "ticket_name": the matched ticket\'s "name" field when decision is "match", '
		"otherwise null}. Never invent a ticket_name that was not in the list you were given. "
		"No markdown, no code fences, no other text.",
		'Put "match" or "no_match" in "decision". "ticket_name" is the matched ticket\'s "name" field '
		'when decision is "match", otherwise null. Never invent a ticket_name that was not in the list '
		"you were given.",
	),
}
JSON_INSTRUCTION = "Respond with ONLY a JSON object"

MODEL_NAME = "Error Log Ticket Triage"
# Raw bpmn_xml text, attribute escaping included.
MAP_EDITS = (
	("&#10;&#10;Respond with the JSON object your instructions specify.", ""),
	(
		"&#34;required&#34;: [&#34;decision&#34;]",
		"&#34;required&#34;: [&#34;decision&#34;, &#34;ticket_name&#34;]",
	),
)


def execute():
	for agent_id, (old, new) in PROMPT_EDITS.items():
		_edit_prompt(agent_id, old, new)
	_edit_map()


def _edit_prompt(agent_id: str, old: str, new: str):
	row = frappe.db.get_value("AI Agent Configuration", {"agent_id": agent_id}, ["name", "system_prompt"])
	if not row:
		return
	name, prompt = row[0], row[1] or ""
	if prompt.count(old) == 1:
		frappe.db.set_value("AI Agent Configuration", name, "system_prompt", prompt.replace(old, new, 1))
	elif JSON_INSTRUCTION in prompt:
		frappe.log_error(
			title="json_agents_declare_their_schema: prompt anchor not found",
			message=f"{name} asks for JSON in words the patch does not recognise; its prompt is left as it is.",
		)


def _edit_map():
	xml = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "bpmn_xml")
	if not xml or MAP_EDITS[1][1] in xml:
		return
	if any(xml.count(old) != 1 for old, _new in MAP_EDITS):
		frappe.log_error(
			title="json_agents_declare_their_schema: map anchor not found",
			message=f"{MODEL_NAME} does not carry each anchor exactly once; its diagram is left as it is.",
		)
		return
	for old, new in MAP_EDITS:
		xml = xml.replace(old, new, 1)
	frappe.db.set_value("BPMN Process Model", MODEL_NAME, "bpmn_xml", xml)

	from one_bpmn.api.compilation import compile_process_model

	compile_process_model(MODEL_NAME)
