# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Legacy payload → contract event translators (WI-001671).

The per-agent endpoints' buffered reply dicts carry their information in
private keys (verified on staging: Logix ``intent/diff/modified_script``,
ProsAlly ``intent/bpmn_xml/pending_xml``, Docu ``doctype_ir``, the Assistant
``proposal``/``recommendations``). Until each migration story teaches its
agent to speak events natively, these translators derive the typed
``onefm.*`` CustomEvents from those dicts at the shared-stream boundary — so
the panel consumes only contract events from day one, whatever the runner
returned.

Registered into one_bpmn.agents.agui_stream's translator registry; imported
by that module at load time.
"""

from __future__ import annotations

from ag_ui.core import CustomEvent

from one_bpmn.agents.agui_stream import register_extension_translator


@register_extension_translator
def _script_diff(result: dict):
	"""Logix: CREATE / MODIFY replies with a proposed script."""
	intent = (result.get("intent") or "").upper()
	if intent in ("CREATE", "MODIFY") and result.get("modified_script"):
		yield CustomEvent(
			name="onefm.script_diff",
			value={
				"mode": intent,
				"modified_script": result["modified_script"],
				**({"diff": result["diff"]} if result.get("diff") else {}),
				**({"apply_target": result["apply_target"]} if result.get("apply_target") else {}),
				**({"suggested_name": result["suggested_name"]} if result.get("suggested_name") else {}),
			},
		)


@register_extension_translator
def _test_cases(result: dict):
	"""Logix: the plain-English test checklist that rides CREATE replies.

	Legacy items carry {scenario, when, expect, inputs, expect_success};
	the contract keeps the renderable subset — expect_success was never
	consumed (pass/fail comes from actually running the case)."""
	checklist = result.get("tests_checklist")
	if not isinstance(checklist, list):
		return
	cases = []
	for item in checklist:
		if not isinstance(item, dict):
			continue
		inputs = item.get("inputs")
		case = {"inputs": inputs if isinstance(inputs, dict) else {}}
		if item.get("scenario"):
			case["scenario"] = str(item["scenario"])
		if item.get("when"):
			case["when"] = str(item["when"])
		if item.get("expect"):
			case["expected"] = str(item["expect"])
		cases.append(case)
	if cases:
		yield CustomEvent(name="onefm.test_cases", value={"cases": cases})


@register_extension_translator
def _bpmn_preview(result: dict):
	"""ProsAlly: generated / modified diagrams, and the removal gate.

	The pending_xml confirm becomes mode=pending_removal — the confirm lives
	inside the DiagramPreviewCard, not in loose option buttons."""
	intent = (result.get("intent") or "").upper()
	if intent in ("BPMN_GENERATED", "BPMN_MODIFIED") and result.get("bpmn_xml"):
		yield CustomEvent(
			name="onefm.bpmn_preview",
			value={
				"mode": "generated" if intent == "BPMN_GENERATED" else "modified",
				"bpmn_xml": result["bpmn_xml"],
				**({"summary": result["response"]} if result.get("response") else {}),
			},
		)
	elif intent == "CONFIRM_REMOVAL" and result.get("pending_xml"):
		yield CustomEvent(
			name="onefm.bpmn_preview",
			value={
				"mode": "pending_removal",
				"bpmn_xml": result["pending_xml"],
				**({"summary": result["response"]} if result.get("response") else {}),
			},
		)


@register_extension_translator
def _doctype_schema(result: dict):
	"""Docu: the whole doctype IR in one event."""
	if result.get("doctype_ir"):
		yield CustomEvent(
			name="onefm.doctype_schema",
			value={
				"doctype_ir": result["doctype_ir"],
				**({"exists": bool(result["exists"])} if "exists" in result else {}),
				**({"custom": bool(result["custom"])} if "custom" in result else {}),
			},
		)


@register_extension_translator
def _assistant_proposals(result: dict):
	"""AI Assistant: a whole new agent, or values for the open form.

	Accepts both the legacy key (proposal) and the shaped-reply keys the
	WI-001674 shaper produces (proposed_config / proposed_update /
	recommendations)."""
	summary = result.get("message") or result.get("summary") or ""
	proposal = result.get("proposed_config") or result.get("proposal")
	if proposal:
		yield CustomEvent(
			name="onefm.proposed_config",
			value={"proposal": proposal, **({"summary": summary} if summary else {})},
		)
	fields = result.get("recommendations")
	if not (isinstance(fields, dict) and fields):
		fields = result.get("proposed_update")
	if isinstance(fields, dict) and fields:
		yield CustomEvent(
			name="onefm.proposed_update",
			value={"fields": fields, **({"summary": summary} if summary else {})},
		)


@register_extension_translator
def _table(result: dict):
	"""Any agent returning a structured table under the ``table`` key."""
	table = result.get("table")
	if isinstance(table, dict) and table.get("columns") and "rows" in table:
		yield CustomEvent(name="onefm.table", value=table)
