import frappe

FIELDS = (
	"processa_approval_section",
	"processa_allowed_modules",
	"processa_approved",
	"processa_approved_by",
	"processa_approved_on",
	"processa_pending_review",
	"processa_approved_hash",
)


def execute():
	"""Remove the Processa Approval fields from Server Script and the report that listed them."""
	for fieldname in FIELDS:
		frappe.delete_doc_if_exists("Custom Field", f"Server Script-{fieldname}")
	frappe.delete_doc_if_exists("Report", "Server Script Approvals")
