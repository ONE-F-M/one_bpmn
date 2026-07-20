# Copyright (c) 2026, ONE BPMN and contributors
# For license information, please see license.txt
#
# "Reassign User Task" — available from the Processa canvas Actions menu only
# when "Connect to Production" is UNCHECKED in Processa Settings.
#
# It lets an authorised user change the Assignment Configuration of User Tasks
# (Assignment Mode, User, DocField, Users, Table Field) on a locked process
# map without requiring an editable Process Implementation. Only the
# whitelisted spiffworkflow assignment attributes of the targeted userTask can
# change — the rest of the BPMN XML is never touched, so this is not a bypass
# of the general editability gate.

import frappe
from frappe import _
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


@frappe.whitelist(methods=["POST"])
def reassign_user_task(model_name: str, task_id: str, assignment) -> dict:
	"""Update the assignment attributes of one User Task in a process map.

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

	applied = {}
	for attr in ALLOWED_ATTRS:
		if attr not in assignment:
			continue
		key = f"{{{SPIFF_NS}}}{attr}"
		value = assignment.get(attr)
		if value in (None, ""):
			task.attrib.pop(key, None)
			applied[attr] = ""
		else:
			task.set(key, str(value))
			applied[attr] = str(value)

	if not applied:
		return {"updated": False, "task_id": task_id, "assignment": {}}

	doc.bpmn_xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8").decode("utf-8")
	# Trusted, attribute-scoped change — permitted even on locked processes
	# (same flag used by import_bpmn / compile_process_model).
	doc.flags.skip_editability_check = True
	doc.save()

	return {"updated": True, "task_id": task_id, "assignment": applied}
