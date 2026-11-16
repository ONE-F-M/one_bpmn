"""Creates the Sandbox Tool scripts the Testing Agent uses to seed test data through the controllers and to learn what a DocType needs."""

import frappe

from processa.patches.v1_0.add_testing_agent_sandbox_tools import HEADER, NEEDS_BRIEF

SEED_DOCS = (
	"""\
# Sandbox tool: seed_docs. Inserts each document with frappe.get_doc(...).insert() on the test site, as Administrator, so the
# controller's validation runs. An entry may instead name a test factory, which the sandbox calls only if it is on its allowed list.
from processa.agents_sandbox.sandbox.ops import sandbox_dispatch

"""
	+ HEADER
	+ f"""\
docs = task_data.get("docs")
if isinstance(docs, str):
    docs = frappe.parse_json(docs)

if not (target_app and git_branch and work_item_description and run_id):
    result["error"] = {NEEDS_BRIEF}
elif not isinstance(docs, list) or not docs:
    result["error"] = "docs is required: a list of documents (each with a doctype) or factory calls, at most 50 per call."
else:
    _dispatch = sandbox_dispatch(
        "seed_docs", target_app, git_branch, work_item_description, {{"run_id": run_id, "docs": docs}}, context_docname,
        bpmn_id=bpmn_id, instance=instance
    )
    if not _dispatch.get("ok"):
        result["error"] = _dispatch.get("error")
    else:
        result.update(_dispatch["response"])
"""
)

SEED_CONTEXT = (
	"""\
# Sandbox tool: seed_context. For the given DocTypes, in dependency order: required fields, Link targets, Select options,
# mandatory_depends_on, the controller's validate source and the known factories. Read only.
from processa.agents_sandbox.sandbox.ops import sandbox_dispatch

"""
	+ HEADER
	+ f"""\
doctypes = task_data.get("doctypes")
if isinstance(doctypes, str):
    doctypes = frappe.parse_json(doctypes)

if not (target_app and git_branch and work_item_description and run_id):
    result["error"] = {NEEDS_BRIEF}
elif not isinstance(doctypes, list) or not doctypes:
    result["error"] = "doctypes is required: a list of DocType names, at most 10 per call."
else:
    _dispatch = sandbox_dispatch(
        "seed_context", target_app, git_branch, work_item_description, {{"run_id": run_id, "doctypes": doctypes}}, context_docname,
        bpmn_id=bpmn_id, instance=instance
    )
    if not _dispatch.get("ok"):
        result["error"] = _dispatch.get("error")
    else:
        result.update(_dispatch["response"])
"""
)

SCRIPTS = {"Sandbox Tool: Seed Docs": SEED_DOCS, "Sandbox Tool: Seed Context": SEED_CONTEXT}


def execute():
	for name, script in SCRIPTS.items():
		if frappe.db.exists("Server Script", name):
			frappe.db.set_value("Server Script", name, "script", script)
			continue
		frappe.get_doc({
			"doctype": "Server Script", "name": name, "script_type": "API",
			"allow_guest": 0, "disabled": 0, "script": script,
		}).insert(ignore_permissions=True)
