import frappe


def execute():
	"""Move the Embedding Model setting from free text onto the list of choices.

	The field was a text box, so it could hold any name, including one that
	produces the wrong number of dimensions for the stored column. Such a value
	does not fail on save; it fails on every later memory write, inside a
	try/except, leaving semantic search off with nothing on screen to say so.

	Anything already set that is not one of the choices becomes the standard
	model, and the change is logged so an administrator can see it happened. A
	blank value already meant the standard model, so it is written out
	explicitly instead of relying on that.
	"""
	from one_bpmn.agents.llm_provider.embedding import DEFAULT_MODEL, SEMANTIC_DISABLED

	meta = frappe.get_meta("Processa Settings")
	field = meta.get_field("memory_embedding_model")
	if not field or field.fieldtype != "Select":
		return

	allowed = {line.strip() for line in (field.options or "").splitlines() if line.strip()}
	allowed.add(SEMANTIC_DISABLED)
	current = (frappe.db.get_single_value("Processa Settings", "memory_embedding_model") or "").strip()
	if current in allowed:
		return

	frappe.db.set_single_value("Processa Settings", "memory_embedding_model", DEFAULT_MODEL)
	if current:
		frappe.logger("one_bpmn").warning(
			f"AI Memory: Embedding Model was {current!r}, which is not one of the supported choices; "
			f"set to {DEFAULT_MODEL}."
		)
