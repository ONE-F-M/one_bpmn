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
def _assistant_created(result: dict):
	"""AI Assistant: its create tool ran and the shaper verified the record.

	The shaper only sets created_config after frappe.db.exists confirms the
	record, so this event is evidence of a real row — hosts may link it on
	the open shape without re-checking."""
	created = result.get("created_config")
	if isinstance(created, dict) and created.get("name"):
		summary = result.get("message") or result.get("summary") or ""
		yield CustomEvent(
			name="onefm.created_config",
			value={
				"name": created["name"],
				**({"agent_id": created["agent_id"]} if created.get("agent_id") else {}),
				**({"summary": summary} if summary else {}),
			},
		)


@register_extension_translator
def _table(result: dict):
	"""Any agent returning a structured table under the ``table`` key."""
	table = result.get("table")
	if isinstance(table, dict) and table.get("columns") and "rows" in table:
		yield CustomEvent(name="onefm.table", value=table)


# Keys the bespoke translators above already own. A reply carrying any of
# them gets its card from its own translator — the generic artifact path
# stands down so one reply can never render two cards for the same thing.
_BESPOKE_ARTIFACT_KEYS = (
	"modified_script",
	"bpmn_xml",
	"pending_xml",
	"doctype_ir",
	"recommendations",
	"proposed_update",
	"proposed_config",
)


@register_extension_translator
def _typed_artifact(result: dict):
	"""Any agent: a generic ``artifact`` reply becomes the typed event its
	configuration's Artifact Type names (the WI-001996 field, wired).

	This is what lets an agent WITHOUT a bespoke translator still get the
	right preview renderer and apply target: the stream stamps
	``artifact_type`` from the AI Agent Configuration (an agent's own reply
	key wins when present), and the mapping below picks the same typed
	events the purpose-built agents emit — so the card registry, the host
	apply wiring, and the conformance build all stay single-sourced.

	``artifact`` may be the bare content (script text, BPMN XML, IR/field
	dict) or a dict with ``content`` plus per-kind extras (``name``/``mode``).
	"""
	artifact = result.get("artifact")
	kind = result.get("artifact_type") or ""
	if artifact in (None, "", {}) or kind in ("", "None"):
		return
	if any(result.get(key) for key in _BESPOKE_ARTIFACT_KEYS):
		return

	# A dict with a "content" key is the wrapped form (content + extras);
	# anything else — script text, XML, a bare IR or field dict — IS the content.
	if isinstance(artifact, dict) and "content" in artifact:
		wrapped, content = artifact, artifact.get("content")
	else:
		wrapped, content = {}, artifact
	summary = result.get("message") or result.get("summary") or result.get("response") or ""

	if kind == "Script" and isinstance(content, str) and content.strip():
		mode = str(wrapped.get("mode") or "CREATE").upper()
		yield CustomEvent(
			name="onefm.script_diff",
			value={
				"mode": mode if mode in ("CREATE", "MODIFY") else "CREATE",
				"modified_script": content,
				**({"suggested_name": wrapped["name"]} if wrapped.get("name") else {}),
				**({"summary": summary} if summary else {}),
			},
		)
	elif kind == "Diagram" and isinstance(content, str) and content.strip():
		mode = str(wrapped.get("mode") or "generated").lower()
		yield CustomEvent(
			name="onefm.bpmn_preview",
			value={
				"mode": mode if mode in ("generated", "modified") else "generated",
				"bpmn_xml": content,
				**({"summary": summary} if summary else {}),
			},
		)
	elif kind == "Schema" and isinstance(content, dict) and content:
		yield CustomEvent(
			name="onefm.doctype_schema",
			value={"doctype_ir": content, **({"summary": summary} if summary else {})},
		)
	elif kind == "Record" and isinstance(content, dict) and content:
		yield CustomEvent(
			name="onefm.proposed_update",
			value={"fields": content, **({"summary": summary} if summary else {})},
		)


# LuCrusher's own phase vocabulary, from its finalize tool's `intent` enum.
# Gating on it keeps other agents' intents (Logix CREATE/MODIFY, ProsAlly's
# action intents) from ever being mistaken for a migration result.
_LUCRUSHER_INTENTS = frozenset({
	"EXACT_MATCH_FOUND", "MULTIPLE_MATCHES", "NO_MATCH", "CONFIRMED", "CLARIFY",
	"LUCIDCHART_PARSED", "LUCIDCHART_ERROR", "LUCIDCHART_METADATA_ONLY",
	"CODEBASE_SCAN_RESULT", "CODEBASE_SCAN_ERROR",
	"TOPOLOGY_PROPOSAL", "TOPOLOGY_CONFIRMED",
	"MIGRATION_TASKS_DRAFT", "MIGRATION_TASKS_CONFIRMED",
	"PROSALLY_PROMPT_DRAFT", "PROSALLY_PROMPT_CONFIRMED",
})
_LUCRUSHER_PAYLOAD_KEYS = (
	"matches", "confirmed_process", "document", "codebase_scan",
	"topology", "migration_tasks", "prosally_prompts",
)


@register_extension_translator
def _lucrusher_result(result: dict):
	"""LuCrusher: the migration phase result behind its panels (WI-001678).

	Map-driven turns never emit the legacy LUCRUSHER_RESULT event — the
	finalize tool persists its structured payload as Chat Message metadata,
	and _delegate_to_bpmn_instance hands that ``agent_result`` back as the
	reply dict. Verified live on the bench 2026-08-16: a search turn came
	back as EXACT_MATCH_FOUND with `matches`, and rendered as plain markdown
	because nothing turned it into an event. This is that bridge; the legacy
	streaming path stays covered by the relay's rename+fold.
	"""
	intent = (result.get("intent") or "").upper()
	if intent not in _LUCRUSHER_INTENTS:
		return
	payload = {"intent": intent}
	for key in _LUCRUSHER_PAYLOAD_KEYS:
		value = result.get(key)
		if value:
			payload[key] = value
	yield CustomEvent(name="onefm.lucrusher_result", value=payload)
