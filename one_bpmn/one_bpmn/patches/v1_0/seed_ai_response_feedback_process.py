"""
Seed the AI Response Feedback Handling process.

Every AI Response Feedback record (positive or negative) needs a Process
Owner assigned and notified, and a negative one needs an Investigate & Fix
step before the original rater is told it's resolved. Per the 2026-08-26
roadmap decision, this is a standalone BPMN process — not logic embedded in
each chat agent's own map — so what ships here is the process itself: a
`Process`, its `BPMN Process Model`, and the two Server Scripts its Script
Tasks call, then a compile to deploy it.

The BPMN XML and its Server Scripts are NOT hand-authored inline here.
They live in `exports/ai_response_feedback_handling.bpmn` and
`exports/ai_response_feedback_handling_config.json` — the same
export/import shape `config_export_import.export_bpmn_config` produces —
so there is one source of truth for the diagram, not a second copy that
could drift from it. This patch only reads those files and calls the same
import path a person would use from the Processa editor.

Idempotent: re-running it updates the model's XML and recompiles rather
than erroring, and `import_bpmn_config` already skips Server Scripts that
are unchanged.
"""

import json
import os

import frappe

_PROCESS_NAME = "AI Response Feedback Handling"
_MODEL_TITLE = "AI Response Feedback Handling"
_EXPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "exports")


def execute():
	bpmn_xml = _read_export("ai_response_feedback_handling.bpmn")
	config_json = _read_export("ai_response_feedback_handling_config.json")
	if not bpmn_xml or not config_json:
		frappe.log_error(
			title="AI Response Feedback Handling: seed skipped",
			message="Export files not found under one_bpmn/exports/ — nothing to seed.",
		)
		return

	_ensure_process()

	from one_bpmn.api.config_export_import import import_bpmn_config

	import_bpmn_config(config_json)

	model_name = _ensure_model(bpmn_xml)

	from one_bpmn.api.compilation import compile_process_model

	try:
		compile_process_model(model_name)
	except Exception:
		# A failed compile here (e.g. a site with `Server Script` disabled
		# entirely) should not break `bench migrate` for everything else —
		# the model is left inactive and importable, re-run this patch (or
		# re-compile from the desk) once the blocker is fixed.
		frappe.log_error(
			title="AI Response Feedback Handling: compile failed during seed",
			message=frappe.get_traceback(),
		)


def _read_export(filename: str) -> str:
	path = os.path.join(_EXPORTS_DIR, filename)
	if not os.path.exists(path):
		return ""
	with open(path, "r", encoding="utf-8") as f:
		return f.read()


def _ensure_process() -> None:
	if frappe.db.exists("Process", _PROCESS_NAME):
		return

	owner = _pick_process_owner()
	frappe.get_doc(
		{
			"doctype": "Process",
			"process_name": _PROCESS_NAME,
			"description": (
				"Assigns and notifies the Process Owner of the agent behind every "
				"AI Response Feedback record, and — for a Negative rating — routes "
				"through an Investigate & Fix step before notifying the rater the "
				"issue is resolved."
			),
			"process_owner": owner,
		}
	).insert(ignore_permissions=True, ignore_if_duplicate=True)


def _pick_process_owner() -> str:
	"""Owner of this meta-process — accountable for the workflow itself,
	not the per-reply Process Owner it assigns tasks to at runtime.

	No natural sibling to inherit from (unlike an agent config seed reusing
	another agent's owner), so this defaults to Administrator. A real owner
	should be set before rollout — a deployment detail, not a design
	blocker: the field is editable on the Process record afterwards.
	"""
	return "Administrator"


def _ensure_model(bpmn_xml: str) -> str:
	if frappe.db.exists("BPMN Process Model", _MODEL_TITLE):
		doc = frappe.get_doc("BPMN Process Model", _MODEL_TITLE)
		doc.bpmn_xml = bpmn_xml
		doc.process_name = _PROCESS_NAME
		doc.save(ignore_permissions=True)
		return doc.name

	doc = frappe.get_doc(
		{
			"doctype": "BPMN Process Model",
			"title": _MODEL_TITLE,
			"process_id": "ai_response_feedback_handling_process",
			"process_name": _PROCESS_NAME,
			"bpmn_xml": bpmn_xml,
			"version": 1,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name
