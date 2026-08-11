# Copyright (c) 2026, ONE BPMN and contributors
# For license information, please see license.txt
#
# "Reassign User Task" — available from the Processa canvas Actions menu only
# on a Production instance (Processa Settings → Instance Type = "Production").
#
# It lets an authorised user change the Assignment Configuration of User Tasks
# (Assignment Mode, User, DocField, Users, Table Field, Row User Field) on a
# locked process map without requiring an editable Process Implementation. Only
# the whitelisted spiffworkflow assignment attributes of the targeted userTask
# can change — the rest of the BPMN XML is never touched, so this is not a
# bypass of the general editability gate.
#
# Changes are audited by the document's own version history and nothing else.
# BPMN Process Model has track_changes enabled, so saving the map records a
# Version carrying the bpmn_xml before/after — which is the reassignment. A
# separate log doctype duplicated that in a second place, where it could drift
# from the document it claimed to describe and had to be kept in step by hand.
#
# Each change is written to the XML immediately, but the map is recompiled
# ("Deploy") only ONCE — when the editor exits reassign mode and calls
# deploy_reassignments — so a whole session of edits triggers a single Deploy
# instead of one per task. NOTE: recompiling rebuilds the model's serialized
# spec, so only NEW process instances pick up the new assignment —
# already-running instances keep the assignee frozen in their own snapshot at
# start time.

import frappe
from frappe import _
from lxml import etree

from one_bpmn.api.editability import _is_production_instance

SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"


def _require_production_instance():
	"""Guard: "Reassign User Task" is only available on a Production instance.

	Enforced here (not just in the frontend) so the gate holds even if the
	Actions menu is bypassed.
	"""
	if not _is_production_instance():
		frappe.throw(
			_("Reassign User Task is only available on a Production instance (Processa Settings → Instance Type)."),
			title=_("Not Available"),
		)

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


def _read_attrs(task) -> dict:
	"""Current value of every assignment attribute on a userTask element."""
	return {attr: (task.get(f"{{{SPIFF_NS}}}{attr}") or "") for attr in ALLOWED_ATTRS}


@frappe.whitelist(methods=["POST"])
def reassign_user_task(model_name: str, task_id: str, assignment) -> dict:
	"""Update the assignment attributes of one User Task in a process map.

	The save records the change in the model's version history; nothing is
	logged anywhere else. Does NOT recompile — the editor calls
	deploy_reassignments() once on exit to Deploy the whole batch.

	Args:
		model_name: BPMN Process Model name.
		task_id: The BPMN element id of the userTask.
		assignment: dict (or JSON string) of attribute → value for the
			whitelisted assignment attributes. Empty/None values remove
			the attribute.
	"""
	_require_production_instance()

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

	return {
		"updated": True,
		"task_id": task_id,
		"task_label": task_label,
		"assignment": {k: after[k] for k in ALLOWED_ATTRS},
	}


@frappe.whitelist(methods=["POST"])
def deploy_reassignments(model_name: str) -> dict:
	"""Recompile a process map once after a batch of reassignments.

	Called by the editor when the user exits Reassign mode, so a whole session's
	assignment edits trigger a single Deploy instead of one per task.

	Kept best-effort: each change is already saved, and saving is what records it
	in the version history, so a recompile failure never loses a reassignment —
	the user can Deploy manually.

	Args:
		model_name: BPMN Process Model name.
	"""
	_require_production_instance()

	if not model_name:
		frappe.throw(_("Process map name is required."))

	redeployed = False
	deploy_error = None
	try:
		from one_bpmn.api.compilation import compile_process_model

		compile_process_model(model_name)
		redeployed = True
	except Exception:
		deploy_error = _("Automatic redeploy failed — click Deploy to apply the changes to new instances.")
		frappe.log_error(frappe.get_traceback(), "deploy_reassignments: auto-deploy failed")

	return {"redeployed": redeployed, "deploy_error": deploy_error}
