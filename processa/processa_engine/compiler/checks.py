# Copyright (c) 2026, one-fm and contributors
"""Deploy checks that refuse a map: prohibited shapes, User Task setup, workflow state fields and the eval gate."""

import json

import frappe
from frappe import _
from frappe.utils import cint, flt


# BPMN tag of each shape refused in an executable process, with its label and suggested replacement.
PROHIBITED_SHAPES: dict[str, dict[str, str]] = {
	"manualTask": {
		"label": "Manual Task",
		"suggestion": "Use a User Task instead",
	},
	"task": {
		"label": "None-type Task",
		"suggestion": "Use a User Task instead",
	},
}


def validate_prohibited_shapes(bpmn_xml: str) -> None:
	"""Refuse a process that holds a shape listed in PROHIBITED_SHAPES."""
	if not PROHIBITED_SHAPES:
		return

	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"

	if not bpmn_xml or not bpmn_xml.strip():
		return

	try:
		root = _ET.fromstring(bpmn_xml.strip().encode("utf-8") if isinstance(bpmn_xml, str) else bpmn_xml)
	except Exception:
		return  # XML errors are caught elsewhere

	process_el = root.find(f"{{{BPMN_NS}}}process") or root.find("process")
	if process_el is None:
		return

	errors = []

	for child in process_el:
		local_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
		if local_tag in PROHIBITED_SHAPES:
			shape_info = PROHIBITED_SHAPES[local_tag]
			el_name = child.get("name", "").strip()
			el_id = child.get("id", "unknown")
			label = f'"{el_name}" ({el_id})' if el_name else f"({el_id})"
			suggestion = shape_info.get("suggestion", "")
			msg = f'{shape_info["label"]} {label} is not allowed in executable processes.'
			if suggestion:
				msg += f" {suggestion}."
			errors.append(msg)

	if errors:
		frappe.throw(
			_(
				"Prohibited shapes found - the following BPMN elements are not allowed "
				"in executable processes:\n\n"
				+ "\n".join(f"• {e}" for e in errors)
			),
			title=_("Prohibited Shapes Detected"),
		)


def validate_notify_assignee_account(bpmn_xml: str) -> None:
	"""Refuse a User Task that notifies its assignee without naming the Email Account it sends from."""
	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	SPIFF = "http://spiffworkflow.org/bpmn/schema/1.0/core"

	if not bpmn_xml or not bpmn_xml.strip():
		return
	try:
		root = _ET.fromstring(
			bpmn_xml.strip().encode("utf-8") if isinstance(bpmn_xml, str) else bpmn_xml
		)
	except Exception:
		return  # XML errors are caught elsewhere

	offenders = []
	for task in root.iter(f"{{{BPMN_NS}}}userTask"):
		if (task.get(f"{{{SPIFF}}}notifyAssignee") or "").strip().lower() != "true":
			continue
		account = (task.get(f"{{{SPIFF}}}notifyAssigneeAccount") or "").strip()
		if account:
			continue
		el_name = (task.get("name") or "").strip().replace("\n", " ")
		el_id = task.get("id", "unknown")
		offenders.append(f'"{el_name}" ({el_id})' if el_name else f"({el_id})")

	if offenders:
		frappe.throw(
			_(
				"These User Tasks notify their assignee but do not say which mailbox to "
				"send from: {0}. Set 'Send From (Email Account)' on each, or turn off "
				"Notify Assignee. Left blank the site's default outgoing account is used, "
				"which is a delivery decision the diagram does not record."
			).format(", ".join(offenders)),
			title=_("Notify Assignee needs an Email Account"),
		)


def validate_user_task_config(bpmn_xml: str) -> None:
	"""Block deployment when an executable User Task has no Assignment Mode or no Task Action."""
	gaps = user_task_config_gaps(bpmn_xml)
	if gaps:
		frappe.throw(
			"<br>".join(message for _bpmn_id, message in gaps),
			title=_("User Task Configuration Missing"),
		)


def user_task_config_gaps(bpmn_xml: str) -> list:
	"""(bpmn_id, message) for each executable User Task with no Assignment Mode or no Task Action."""
	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

	if not bpmn_xml or not bpmn_xml.strip():
		return []
	try:
		root = _ET.fromstring(bpmn_xml.strip().encode("utf-8") if isinstance(bpmn_xml, str) else bpmn_xml)
	except _ET.ParseError:
		return []

	gaps = []
	for process in root.iter(f"{{{BPMN_NS}}}process"):
		if process.get("isExecutable", "false").strip().lower() != "true":
			continue
		for user_task in process.iter(f"{{{BPMN_NS}}}userTask"):
			bpmn_id = user_task.get("id")
			name = user_task.get("name") or bpmn_id
			if not (user_task.get(f"{{{SPIFF_NS}}}assigneeMode") or "").strip():
				gaps.append((bpmn_id, _('User Task "{0}" requires an Assignment Mode.').format(name)))
			if not _has_task_action(user_task.get(f"{{{SPIFF_NS}}}taskActions")):
				gaps.append((bpmn_id, _('User Task "{0}" requires at least one Task Action.').format(name)))
	return gaps


def _has_task_action(raw: str | None) -> bool:
	"""True when the stored taskActions JSON holds at least one row with a non-empty action."""
	try:
		actions = json.loads(raw or "[]")
	except ValueError:
		return False
	return isinstance(actions, list) and any(
		isinstance(row, dict) and str(row.get("action") or "").strip() for row in actions
	)


def validate_workflow_state_field(model, service_extensions: dict) -> None:
	"""Refuse a model whose workflow-state trigger or Apply Workflow task names a doctype with no workflow_state field."""
	has_workflow_state_trigger = any(
		row.workflow_state_condition for row in (model.start_events or [])
	)
	has_apply_workflow_task = any(
		cfg.get("serviceType") == "apply_workflow"
		for cfg in service_extensions.values()
	)

	if not has_workflow_state_trigger and not has_apply_workflow_task:
		return

	doctypes_to_check = set()

	if has_workflow_state_trigger:
		for row in (model.start_events or []):
			if not row.workflow_state_condition:
				continue
			dt = row.trigger_doctype or model.trigger_doctype
			if dt:
				doctypes_to_check.add(dt)

	if has_apply_workflow_task:
		for cfg in service_extensions.values():
			if cfg.get("serviceType") != "apply_workflow":
				continue
			target = cfg.get("serviceTargetDoctype")
			if target:
				doctypes_to_check.add(target)
			else:
				if model.trigger_doctype:
					doctypes_to_check.add(model.trigger_doctype)
				for row in (model.target_doctypes or []):
					if row.doctype_name:
						doctypes_to_check.add(row.doctype_name)

	missing = []
	for doctype in sorted(doctypes_to_check):
		try:
			meta = frappe.get_meta(doctype)
		except Exception:
			continue  # unknown doctype - let other validations surface it
		if not meta.get_field("workflow_state"):
			missing.append(doctype)

	if not missing:
		return

	error_lines = [_("Workflow State field is missing on: {0}").format(dt) for dt in missing]
	frappe.throw(
		"\n".join(f"• {line}" for line in error_lines),
		title=_("Missing Workflow State Field"),
	)


def enforce_eval_pass_rate(model_name: str) -> None:
	"""Refuse activation while a gating eval suite is below its min_pass_rate; a rate of 0 blocks nothing."""
	suites = frappe.get_list(
		"AI Eval Suite",
		filters={"process_model": model_name, "gate_deployment": 1},
		fields=["name", "title", "min_pass_rate"],
		ignore_permissions=True,  # the deploy gate reads every suite and run linked to the model
	)

	refusals = []
	for suite in suites:
		minimum = flt(suite.min_pass_rate)
		if not minimum:
			continue

		latest = frappe.get_list(
			"AI Eval Run",
			filters={"suite": suite.name},
			fields=["name", "status", "pass_rate", "total_executions"],
			order_by="started_at desc",
			limit_page_length=1,
			ignore_permissions=True,  # the deploy gate reads every suite and run linked to the model
		)
		title = suite.title or suite.name
		if not latest:
			refusals.append(
				_("'{0}' requires a {1}% pass rate and has never been run.").format(title, minimum)
			)
			continue

		run = latest[0]
		rate = flt(run.pass_rate)
		if rate < minimum:
			refusals.append(
				_("'{0}' is at {1}% over {2} execution(s) and requires {3}%.").format(
					title, round(rate, 1), cint(run.total_executions), minimum
				)
			)

	if refusals:
		frappe.throw(
			_("This map cannot be activated until its gating eval suites pass:\n\n")
			+ "\n".join(f"• {r}" for r in refusals),
			title=_("Eval Gate"),
		)
