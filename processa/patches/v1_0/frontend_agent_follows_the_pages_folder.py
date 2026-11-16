"""Locate UI reads the router from spiff/src/router.js, and the six retired Frontend Agent tool scripts are removed.

No map or tool box names those scripts any more. Idempotent.
"""

import frappe

from processa.patches.v1_0.chat_agents_post_failed_turn_error import apply_edit

LOCATE_UI = "Frontend Agent: Tool Locate UI"
OLD_ROUTER = "processa/spiff/src/router/index.js"
NEW_ROUTER = "processa/spiff/src/router.js"
RETIRED_SCRIPTS = (
	"Frontend Agent: Tool Draft Change",
	"Frontend Agent: Tool Finalize",
	"Frontend Agent: Tool Propose Pull Request",
	"Frontend Agent: Tool Read File",
	"Frontend Agent: Tool Register Hook",
	"Frontend Agent: Tool Review Change",
)


def execute():
	_repoint_locate_ui()
	for name in RETIRED_SCRIPTS:
		if frappe.db.exists("Server Script", name):
			frappe.delete_doc("Server Script", name, force=True)


def _repoint_locate_ui():
	if not frappe.db.exists("Server Script", LOCATE_UI):
		return
	doc = frappe.get_doc("Server Script", LOCATE_UI)
	edited = apply_edit(doc.script or "", OLD_ROUTER, NEW_ROUTER)
	if edited is None:
		frappe.log_error(
			title="frontend_agent_follows_the_pages_folder: anchor not found",
			message=f"{LOCATE_UI} has no single '{OLD_ROUTER}' line; the script is left as-is.",
		)
		return
	if edited != doc.script:
		doc.script = edited
		doc.save()
