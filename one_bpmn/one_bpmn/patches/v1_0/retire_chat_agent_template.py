"""
WI-001997: retire the shared chat-map template — every agent owns its own map.

The AI Agent Creation Process used to clone the hand-authored "Chat Agent
Template" BPMN Process Model into a per-agent chat map, and RE-provisioning
re-cloned it in place — overwriting the agent's own map and wiping any tool
shapes added to it afterwards (this destroyed four of the AI Assistant's
tools between 2026-08-03 and 2026-08-08). The map is now a designer-chosen
link set at creation (usually the process the agent is created inside), and
the clone machinery (one_bpmn.agents.chat_map_template) has been deleted.

This patch converges existing sites:

1. Replaces the "AAC – Provision" Server Script body: instead of cloning the
   template it validates the config's own process_model link and compiles
   the map when it has never been compiled. A mapless agent (Direct-API
   chat) provisions as-is — provisioned_model stays empty.
2. Deletes the "Chat Agent Template" record — unless something still links
   it (an AI Agent Configuration's process_model, a stray instance), in
   which case it is left in place and the reason is logged.

Idempotent throughout. Existing agent maps are never touched.
"""

import frappe

PROVISION_SCRIPT_NAME = "AAC – Provision"

PROVISION_SCRIPT = '''# AAC – Provision (WI-001997): the agent's map is its own, designer-chosen
# link — nothing is cloned and nothing is ever overwritten. Validate the
# link and make sure the map is compiled; a mapless agent (Direct-API chat)
# provisions as-is.
from one_bpmn.agents.agent_provisioning import _set_status
from one_bpmn.api.compilation import compile_process_model

_set_status(context_docname, "Provisioning")

_model = frappe.db.get_value("AI Agent Configuration", context_docname, "process_model") or ""
if _model and not frappe.db.exists("BPMN Process Model", _model):
    result["provision_error"] = "Linked BPMN Process Model '" + _model + "' does not exist."
elif _model:
    if not frappe.db.get_value("BPMN Process Model", _model, "serialized_spec"):
        compile_process_model(_model)
    result["provisioned_model"] = _model
else:
    result["provisioned_model"] = ""
'''


def _deprovision_aac_script() -> None:
	"""Swap the clone body for the link-and-compile body, in place."""
	if not frappe.db.exists("Server Script", PROVISION_SCRIPT_NAME):
		return  # site without the creation process — nothing to converge
	doc = frappe.get_doc("Server Script", PROVISION_SCRIPT_NAME)
	if (doc.script or "").strip() == PROVISION_SCRIPT.strip():
		return
	doc.script = PROVISION_SCRIPT
	doc.save(ignore_permissions=True)


def _retire_template_record() -> None:
	name = "Chat Agent Template"
	if not frappe.db.exists("BPMN Process Model", name):
		return
	linked = frappe.get_all(
		"AI Agent Configuration", filters={"process_model": name}, pluck="name"
	)
	if linked:
		frappe.log_error(
			title="retire_chat_agent_template: template left in place",
			message=(
				"These AI Agent Configuration records link 'Chat Agent Template' as "
				f"their process_model: {linked}. Point them at their real maps, then "
				"delete the template manually."
			),
		)
		return
	try:
		frappe.delete_doc("BPMN Process Model", name, ignore_missing=True)
	except frappe.LinkExistsError:
		frappe.log_error(
			title="retire_chat_agent_template: template left in place",
			message=frappe.get_traceback(),
		)


def execute():
	_deprovision_aac_script()
	_retire_template_record()
	frappe.db.commit()
