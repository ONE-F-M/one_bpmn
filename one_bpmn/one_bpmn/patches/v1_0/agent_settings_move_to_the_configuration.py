import json

import frappe


def execute():
	"""Copy agent settings that live only on a diagram onto the agent's record.

	An AI Agent Task carries its own copy of the agent's settings in the BPMN
	XML, and the linked AI Agent Configuration overlays it, but only where the
	record's field is filled in. A blank record field lets the diagram's value
	through. That is how the same agent came to run with settings nobody could
	see on its record: the answer to "what temperature does this agent use"
	depended on which diagram you opened.

	This makes the record true. For every agent task that names a
	configuration, a setting present on the shape and blank on the record is
	written to the record. A value already on the record is never touched: it
	is the one somebody chose deliberately, and it already wins today.

	Nothing is removed from the XML. The diagrams keep their copies and stay
	loadable; they simply stop being the only place a setting exists.
	"""
	from one_bpmn.agents.agent_config_resolver import _CONFIG_TO_SHAPE

	shape_to_config = {shape: field for field, shape in _CONFIG_TO_SHAPE.items()}
	moved: dict[str, dict[str, str]] = {}

	for model in frappe.get_all("BPMN Process Model", fields=["name", "serialized_spec"]):
		for shape_id, shape in _agent_shapes(model.serialized_spec):
			config_name = shape.get("aiAgentConfig")
			if not config_name or not frappe.db.exists("AI Agent Configuration", config_name):
				continue
			for attribute, value in shape.items():
				field = shape_to_config.get(attribute)
				if not field or value in (None, ""):
					continue
				if not _is_blank(config_name, field):
					continue
				try:
					frappe.db.set_value("AI Agent Configuration", config_name, field, value)
				except Exception:
					# One unwritable field must not stop the rest of the move.
					frappe.log_error(
						title="Agent settings move: one field could not be written",
						message=f"{config_name}.{field} from {model.name}/{shape_id}: {frappe.get_traceback()}",
					)
					continue
				moved.setdefault(config_name, {})[field] = value

	if moved:
		frappe.logger("one_bpmn").info(f"Agent settings moved from diagrams onto their records: {moved}")


def _agent_shapes(serialized_spec):
	"""(shape id, attributes) for every AI Agent Task in one process model.

	A model with no spec, or one that will not parse, yields nothing: a patch
	that cannot read a diagram should leave it alone, not fail the migration.
	"""
	if not serialized_spec:
		return
	try:
		extensions = (json.loads(serialized_spec) or {}).get("service_task_extensions") or {}
	except (ValueError, TypeError):
		return
	for shape_id, shape in extensions.items():
		if isinstance(shape, dict) and shape.get("aiAgentConfig"):
			yield shape_id, shape


def _is_blank(config_name: str, field: str) -> bool:
	"""True when the record has nothing for this field.

	0 counts as blank for the numeric settings, which is the same rule the
	resolver already applies: a 0 there has always meant "not configured here",
	not a deliberate zero.
	"""
	value = frappe.db.get_value("AI Agent Configuration", config_name, field)
	if value in (None, ""):
		return True
	return value == 0 and isinstance(value, int | float)
