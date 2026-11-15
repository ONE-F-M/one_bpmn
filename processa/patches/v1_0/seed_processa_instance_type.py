def execute():
	"""Give Processa Settings an Instance Type on sites that have none."""
	from processa.api.editability import ensure_instance_type_seeded

	ensure_instance_type_seeded()
