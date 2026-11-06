def execute():
	"""Give Processa Settings an Instance Type on sites that have none."""
	from one_bpmn.api.editability import ensure_instance_type_seeded

	ensure_instance_type_seeded()
