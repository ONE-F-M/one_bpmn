import frappe


def execute():
	"""Write the documented defaults for the AI Memory number settings.

	The default printed in a DocType JSON applies when a document is first
	created. Processa Settings was created long before these fields existed, so
	each one reads back as 0 on an existing site, and the first save of the form
	stores that 0. Every rule these numbers drive is off at 0, so nightly
	pruning quietly did nothing and the volume alert would have fired on every
	site every night.

	Only fields sitting at 0 or blank are written, so a value somebody chose is
	never overwritten. Sites installed after this patch get the same numbers
	from the field defaults.
	"""
	defaults = {
		"memory_semantic_weight": 0.6,
		"memory_recency_weight": 0.2,
		"memory_importance_weight": 0.2,
		"memory_prune_min_confidence": 0.2,
		"memory_prune_uncorroborated_days": 180,
		"memory_prune_low_importance_days": 90,
		"memory_scope_row_alert": 10000,
		"memory_total_row_alert": 500000,
	}
	meta = frappe.get_meta("Processa Settings")
	written = {}
	for fieldname, default in defaults.items():
		if not meta.get_field(fieldname):
			continue  # the branch carrying that field is not merged here yet
		current = frappe.db.get_single_value("Processa Settings", fieldname)
		if current in (None, "", 0, 0.0, "0"):
			frappe.db.set_single_value("Processa Settings", fieldname, default)
			written[fieldname] = default

	if written:
		frappe.logger("one_bpmn").info(f"AI Memory: seeded settings that had never been set: {written}")
