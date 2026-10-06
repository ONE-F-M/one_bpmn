"""Docu's baseline cases match what Docu does now.

The classifier prompt gains a rule that a question about what something means is OFF_TOPIC. The
display-condition case expects the field-property stage on a DocType of its own, and the numbering case's
token ceiling is the measured cost. Each edit applies once, and only those two cases are refreshed.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0 import seed_docu_baseline_cases as seed
from one_bpmn.one_bpmn.patches.v1_0.chat_agents_post_failed_turn_error import apply_edit

CLASSIFIER_ANCHOR = (
	"- When DISAMBIGUATE, suggest in your reason whether a Yes/No (polar) question or a multiple-choice "
	"question would resolve it fastest.\n"
)
CLASSIFIER_RULE = (
	'- A question about what something means or does ("what does this status do", "how does X work") is '
	"OFF_TOPIC, never DISAMBIGUATE, even when you do not know what it refers to.\n"
)
REFRESHED_CASES = (
	"A numbering pattern asked for becomes a naming rule that produces it",
	"A field shown only for some values gets a display condition on those values",
)


def execute():
	_edit_classifier()
	_refresh_cases()


def _edit_classifier():
	agent = frappe.db.get_value("AI Agent Configuration", {"agent_id": seed.AGENT_ID}, "name")
	row = agent and frappe.db.get_value(
		"AI Agent Sub Prompt",
		{"parent": agent, "sub_agent_id": "intent_classifier"},
		["name", "prompt_text"],
		as_dict=True,
	)
	if not row:
		return
	text = row.prompt_text or ""
	edited = apply_edit(text, CLASSIFIER_ANCHOR, CLASSIFIER_ANCHOR + CLASSIFIER_RULE)
	if edited is None:
		frappe.log_error(
			title="docu_baseline_matches_the_current_agent: anchor not found",
			message=f"{agent} intent_classifier has no single DISAMBIGUATE question line; the prompt is left as it is.",
		)
		return
	if edited != text:
		frappe.db.set_value("AI Agent Sub Prompt", row.name, "prompt_text", edited, update_modified=False)
		frappe.cache.delete_value(f"agent_config:{seed.AGENT_ID}")


def _refresh_cases():
	agent, process_model = frappe.db.get_value(
		"AI Agent Configuration", {"agent_id": seed.AGENT_ID}, ["name", "process_model"]
	) or (None, None)
	suite = agent and frappe.db.get_value(
		"AI Eval Suite", {"agent_configuration": agent, "suite_type": "Baseline"}, "name"
	)
	if not suite:
		return
	seed.ensure_probe_doctype()
	for spec in seed.CASES:
		if spec["title"] in REFRESHED_CASES and frappe.db.exists(
			"AI Eval Case", {"suite": suite, "title": spec["title"]}
		):
			seed.upsert_case(suite, process_model, spec)
