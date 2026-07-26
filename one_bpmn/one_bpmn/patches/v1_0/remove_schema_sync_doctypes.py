import frappe


def execute():
	"""Remove the retired BA-sync DocTypes.

	The daily BA → Production schema sync (Custom Fields / Property Setters)
	was removed in favour of the on-demand "Review Doctypes" / "Review
	Workflow Objects" actions on the Processa canvas. Drop the now-orphaned
	log DocTypes and their tables so migrate no longer carries them.
	"""
	# "Processa GitHub Repo" was a short-lived repo-mapping child table that was
	# dropped in favour of deriving the repository from each app's git remote.
	for dt in ("Schema Sync Log", "Schema Sync Detail", "Processa GitHub Repo"):
		if frappe.db.exists("DocType", dt):
			frappe.delete_doc("DocType", dt, force=True, ignore_missing=True)
