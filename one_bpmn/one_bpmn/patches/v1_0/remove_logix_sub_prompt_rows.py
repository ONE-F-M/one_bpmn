import frappe

PARENT_CONFIG = "Logix"


def execute():
	"""Delete the Logix config's Sub Prompts rows now that every pipeline stage
	has its own dedicated AI Agent Configuration and nothing in Logix reads
	the Sub Prompts table anymore. Scoped to Logix only — the table/field
	itself stays, since Docu and ProsAlly still read it for their own tools.
	"""
	rows = frappe.get_all(
		"AI Agent Sub Prompt",
		filters={"parent": PARENT_CONFIG, "parenttype": "AI Agent Configuration"},
		pluck="name",
	)
	if not rows:
		return
	for name in rows:
		frappe.delete_doc("AI Agent Sub Prompt", name, ignore_permissions=True, force=True)
