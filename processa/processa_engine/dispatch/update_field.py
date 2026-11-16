# Copyright (c) 2026, one-fm and contributors
"""Service Task serviceType="update_field": set fields on the context document."""

import json

import frappe
import frappe.utils


def dispatch_update_field(instance, task, task_cfg: dict, bpmn_id: str) -> None:
	"""Write updateFieldRows ([{field, value}], each value Jinja-rendered) to the document in one set_value.

	Without updateFieldRows the single updateFieldName / updateFieldValue pair is used. updateFieldDoctype defaults to the context doctype.
	"""
	doctype = task_cfg.get("updateFieldDoctype") or instance.context_doctype
	docname = instance.context_docname

	if not (doctype and docname):
		frappe.log_error(
			title=f"BPMN ServiceTask: update_field misconfigured ({bpmn_id})",
			message=f"Task {bpmn_id} is missing doctype={doctype!r} or docname={docname!r}.",
		)
		return

	rows_json = task_cfg.get("updateFieldRows", "")
	if rows_json:
		try:
			rows = json.loads(rows_json)
			if not isinstance(rows, list):
				frappe.log_error(
					title=f"BPMN ServiceTask: update_field misconfigured ({bpmn_id})",
					message=(
						f"updateFieldRows decoded to {type(rows).__name__}, expected list. "
						f"Raw value: {rows_json!r}"
					),
				)
				return
		except Exception:
			frappe.log_error(
				title=f"BPMN ServiceTask: update_field invalid JSON ({bpmn_id})",
				message=f"updateFieldRows is not valid JSON: {rows_json!r}",
			)
			return
	else:
		legacy_field = task_cfg.get("updateFieldName", "")
		legacy_value = task_cfg.get("updateFieldValue", "")
		if not legacy_field:
			frappe.log_error(
				title=f"BPMN ServiceTask: update_field misconfigured ({bpmn_id})",
				message=f"Task {bpmn_id} has no updateFieldRows and no updateFieldName.",
			)
			return
		rows = [{"field": legacy_field, "value": legacy_value}]

	if not rows:
		return

	try:
		doc = frappe.get_doc(doctype, docname)
	except Exception:
		frappe.log_error(
			title=f"BPMN ServiceTask: update_field doc load failed ({bpmn_id})",
			message=frappe.get_traceback(),
		)
		return

	updates = {}
	for row in rows:
		if not isinstance(row, dict):
			continue
		fieldname = (row.get("field") or "").strip()
		raw_value = row.get("value", "")
		if not fieldname:
			continue
		if "{{" in str(raw_value) or "{%" in str(raw_value):
			try:
				raw_value = frappe.render_template(
					raw_value,
					{"doc": doc, "instance": instance, "frappe": frappe},
				)
			except Exception:
				frappe.log_error(
					title=f"BPMN ServiceTask: update_field Jinja render failed ({bpmn_id})",
					message=frappe.get_traceback(),
				)
		updates[fieldname] = raw_value

	if not updates:
		return

	actor = frappe.session.user or instance.initiated_by or "Administrator"
	# modified_by rides in the same write so the audit trail names the user who triggered the task.
	update_payload = {**updates, "modified_by": actor}

	try:
		old_flag = getattr(frappe.flags, "bpmn_engine_action", False)
		frappe.flags.bpmn_engine_action = True
		try:
			frappe.db.set_value(doctype, docname, update_payload, update_modified=False)
		finally:
			frappe.flags.bpmn_engine_action = old_flag

	except Exception:
		frappe.log_error(
			title=f"BPMN ServiceTask: update_field failed ({bpmn_id})",
			message=frappe.get_traceback(),
		)
		raise

	frappe.publish_realtime(
		"doc_update",
		{"modified": str(frappe.utils.now_datetime()), "modified_by": actor},
		doctype=doctype,
		docname=docname,
		after_commit=True,
	)
