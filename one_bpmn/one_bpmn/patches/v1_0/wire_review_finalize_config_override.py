import frappe


def execute():
	_patch("Logix – Tool Review Script", '"aiAgentConfig": "Logix – Script Reviewer",',
		'"aiAgentConfig": ai_agent_config or "Logix – Script Reviewer",')
	_patch("Logix – Tool Finalize", '"aiAgentConfig": "Logix – Test Writer",',
		'"aiAgentConfig": ai_agent_config or "Logix – Test Writer",')


def _patch(script_name, old, new):
	doc = frappe.get_doc("Server Script", script_name)
	if new in doc.script:
		return  # already applied (this patch is run via bench execute, not just migrate)
	if old not in doc.script:
		frappe.throw(f"Expected literal not found in '{script_name}' — script may have changed.")
	doc.script = doc.script.replace(old, new, 1)
	doc.save(ignore_permissions=True)
	frappe.db.commit()
