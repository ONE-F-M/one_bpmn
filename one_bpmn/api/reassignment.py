# Copyright (c) 2026, ONE BPMN and contributors
# For license information, please see license.txt
#
# "Reassign User Task" — available from the Processa canvas Actions menu only
# when "Connect to Production" is UNCHECKED in Processa Settings.
#
# It lets an authorised user change the Assignment Configuration of User Tasks
# (Assignment Mode, User, DocField, Users, Table Field, Row User Field) on a
# locked process map without requiring an editable Process Implementation. Only
# the whitelisted spiffworkflow assignment attributes of the targeted userTask
# can change — the rest of the BPMN XML is never touched, so this is not a
# bypass of the general editability gate.
#
# Every change is recorded in a "User Task Assignment Log" (previous + new
# values). Each change is written to the XML immediately, but the map is
# recompiled ("Deploy") only ONCE — when the editor exits reassign mode and
# calls deploy_reassignments — so a whole session of edits triggers a single
# Deploy instead of one per task. NOTE: recompiling rebuilds the model's
# serialized spec, so only NEW process instances pick up the new assignment —
# already-running instances keep the assignee frozen in their own snapshot at
# start time.

import frappe
from frappe import _
from frappe.utils import now_datetime
from lxml import etree

SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

# The only attributes this endpoint may write (Assignment Configuration).
# targetDoctype is deliberately excluded — the DocType stays read-only.
ALLOWED_ATTRS = (
	"assigneeMode",
	"assigneeUser",
	"assigneeDocfield",
	"assigneeUsers",
	"assigneeTableField",
	"assigneeTableUserField",
)

VALID_MODES = ("", "User", "DocField", "Round Robin", "Load Balancing", "Table Field")

# spiffworkflow attribute -> (previous field, new field) on User Task Assignment Log
_LOG_FIELDS = {
	"assigneeMode": ("prev_assignment_mode", "new_assignment_mode"),
	"assigneeUser": ("prev_user", "new_user"),
	"assigneeDocfield": ("prev_docfield", "new_docfield"),
	"assigneeUsers": ("prev_users", "new_users"),
	"assigneeTableField": ("prev_table_field", "new_table_field"),
	"assigneeTableUserField": ("prev_row_user_field", "new_row_user_field"),
}


def _read_attrs(task) -> dict:
	"""Current value of every assignment attribute on a userTask element."""
	return {attr: (task.get(f"{{{SPIFF_NS}}}{attr}") or "") for attr in ALLOWED_ATTRS}


@frappe.whitelist(methods=["POST"])
def reassign_user_task(model_name: str, task_id: str, assignment) -> dict:
	"""Update the assignment attributes of one User Task in a process map.

	Records the change in a User Task Assignment Log. Does NOT recompile — the
	editor calls deploy_reassignments() once on exit to Deploy the whole batch.

	Args:
		model_name: BPMN Process Model name.
		task_id: The BPMN element id of the userTask.
		assignment: dict (or JSON string) of attribute → value for the
			whitelisted assignment attributes. Empty/None values remove
			the attribute.
	"""
	settings = frappe.get_cached_doc("Processa Settings")
	if settings.connect_to_production:
		frappe.throw(
			_("Reassign User Task is only available when 'Connect to Production' is disabled."),
			title=_("Not Available"),
		)

	if not model_name or not task_id:
		frappe.throw(_("Process map name and task id are required."))

	assignment = frappe.parse_json(assignment) if isinstance(assignment, str) else (assignment or {})
	if not isinstance(assignment, dict):
		frappe.throw(_("assignment must be a JSON object."))

	unknown = sorted(set(assignment) - set(ALLOWED_ATTRS))
	if unknown:
		frappe.throw(
			_("Only assignment attributes can be changed here. Not allowed: {0}").format(", ".join(unknown))
		)
	if "assigneeMode" in assignment and (assignment.get("assigneeMode") or "") not in VALID_MODES:
		frappe.throw(_("Invalid Assignment Mode: {0}").format(assignment.get("assigneeMode")))

	doc = frappe.get_doc("BPMN Process Model", model_name)
	doc.check_permission("write")

	xml = doc.bpmn_xml or ""
	if not xml.strip():
		frappe.throw(_("This process map has no BPMN content."))

	root = etree.fromstring(xml.encode("utf-8"))
	nodes = root.xpath("//*[local-name()='userTask' and @id=$tid]", tid=task_id)
	if not nodes:
		frappe.throw(_("User Task '{0}' was not found in this process map.").format(task_id))
	task = nodes[0]
	task_label = task.get("name") or task_id

	before = _read_attrs(task)

	# Apply only the provided whitelisted attributes.
	for attr in ALLOWED_ATTRS:
		if attr not in assignment:
			continue
		key = f"{{{SPIFF_NS}}}{attr}"
		value = assignment.get(attr)
		if value in (None, ""):
			task.attrib.pop(key, None)
		else:
			task.set(key, str(value))

	after = _read_attrs(task)

	if before == after:
		return {"updated": False, "task_id": task_id, "redeployed": False}

	doc.bpmn_xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8").decode("utf-8")
	# Trusted, attribute-scoped change — permitted even on locked processes
	# (same flag used by import_bpmn / compile_process_model).
	doc.flags.skip_editability_check = True
	doc.save()

	log_name = _write_log(doc, task_id, task_label, before, after)

	return {
		"updated": True,
		"task_id": task_id,
		"assignment": {k: after[k] for k in ALLOWED_ATTRS},
		"log": log_name,
	}


@frappe.whitelist(methods=["POST"])
def deploy_reassignments(model_name: str, logs=None) -> dict:
	"""Recompile a process map once after a batch of reassignments.

	Called by the editor when the user exits Reassign mode, so a whole session's
	assignment edits trigger a single Deploy instead of one per task. On success
	the referenced User Task Assignment Log rows are marked as redeployed.

	Kept best-effort: the changes and their audit logs are already persisted, so
	a recompile failure never loses a reassignment — the user can Deploy manually.

	Args:
		model_name: BPMN Process Model name.
		logs: list (or JSON string) of User Task Assignment Log names created
			during this reassign session, to mark as redeployed.
	"""
	settings = frappe.get_cached_doc("Processa Settings")
	if settings.connect_to_production:
		frappe.throw(
			_("Reassign User Task is only available when 'Connect to Production' is disabled."),
			title=_("Not Available"),
		)

	if not model_name:
		frappe.throw(_("Process map name is required."))

	log_names = frappe.parse_json(logs) if isinstance(logs, str) else (logs or [])
	if not isinstance(log_names, (list, tuple)):
		log_names = []

	redeployed = False
	deploy_error = None
	try:
		from one_bpmn.api.compilation import compile_process_model

		compile_process_model(model_name)
		redeployed = True
	except Exception:
		deploy_error = _("Automatic redeploy failed — click Deploy to apply the changes to new instances.")
		frappe.log_error(frappe.get_traceback(), "deploy_reassignments: auto-deploy failed")

	if redeployed and log_names:
		for name in log_names:
			try:
				frappe.db.set_value(
					"User Task Assignment Log", name, "redeployed", 1, update_modified=False
				)
			except Exception:
				frappe.log_error(frappe.get_traceback(), "deploy_reassignments: log flag update failed")

	return {"redeployed": redeployed, "deploy_error": deploy_error}


def _write_log(doc, task_id: str, task_label: str, before: dict, after: dict) -> str:
	"""Record the before/after assignment configuration in the audit log.

	Written with redeployed=0; deploy_reassignments() flips it once the batched
	Deploy succeeds. Returns the new log's name.
	"""
	log = frappe.new_doc("User Task Assignment Log")
	log.model = doc.name
	log.process_name = doc.get("process_name")
	log.task_id = task_id
	log.task_label = task_label
	log.reassigned_by = frappe.session.user
	log.reassigned_on = now_datetime()
	log.redeployed = 0
	for attr, (prev_field, new_field) in _LOG_FIELDS.items():
		setattr(log, prev_field, before.get(attr) or "")
		setattr(log, new_field, after.get(attr) or "")
	log.insert(ignore_permissions=True)
	return log.name
