"""Docu's write_schema prompt shows an existing DocType without its 0 and empty properties.

The schema writer echoes the definition it is given, so a one-field edit to ToDo came back as 16,000
tokens and 95 seconds. Each anchor must be found exactly once; anything else is logged and left as it is.
"""

import frappe

MODEL_NAME = "Docu – DocType Agent"
# Raw bpmn_xml text, attribute escaping included.
MAP_EDITS = (
	("{{ turn.current_ir | tojson(indent=2) }}", "{{ compact_ir(turn.current_ir) | tojson(indent=2) }}"),
	(
		"every Section/Column/Tab break in the same order.",
		"every Section/Column/Tab break in the same order. A property that is 0 or empty is left out "
		"above; leave it out of your answer too.",
	),
)


def execute():
	xml = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "bpmn_xml")
	if not xml:
		return
	edited = rewrite(xml)
	if edited is None:
		frappe.log_error(
			title="docu_edit_prompt_sends_a_compact_definition: map anchor not found",
			message=f"{MODEL_NAME} does not carry each anchor exactly once; its diagram is left as it is.",
		)
		return
	if edited == xml:
		return
	frappe.db.set_value("BPMN Process Model", MODEL_NAME, "bpmn_xml", edited)

	from one_bpmn.api.compilation import compile_process_model

	compile_process_model(MODEL_NAME)


def rewrite(xml: str) -> str | None:
	"""The map with both edits made, the map unchanged when already edited, or None when an anchor is off."""
	if MAP_EDITS[0][1] in xml:
		return xml
	if any(xml.count(old) != 1 for old, _new in MAP_EDITS):
		return None
	for old, new in MAP_EDITS:
		xml = xml.replace(old, new, 1)
	return xml
