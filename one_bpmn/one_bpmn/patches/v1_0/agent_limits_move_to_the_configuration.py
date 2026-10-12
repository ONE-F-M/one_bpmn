"""Timeout, retries, tool calls and top P that sit only on a diagram are copied onto the agent's record.

A value is written only where the record is blank, and only when every shape of the agent that sets it
agrees; a disagreement is logged and the record stays blank. A second run finds nothing blank to fill.
"""

import frappe
from frappe.utils import cint, flt

from one_bpmn.agents.agent_config_resolver import _ZERO_MEANS_UNSET
from one_bpmn.one_bpmn.patches.v1_0.agent_settings_move_to_the_configuration import (
	_agent_shapes,
	_is_blank,
)


def execute():
	found: dict[tuple[str, str], set[float]] = {}
	for model in frappe.get_all("BPMN Process Model", fields=["name", "serialized_spec"]):
		for _shape_id, shape in _agent_shapes(model.serialized_spec):
			config_name = frappe.db.get_value("AI Agent Configuration", shape["aiAgentConfig"], "name")
			if not config_name:
				continue
			for attribute, field in _ZERO_MEANS_UNSET.items():
				if flt(shape.get(attribute)):
					found.setdefault((config_name, field), set()).add(flt(shape[attribute]))

	for (config_name, field), values in found.items():
		if not _is_blank(config_name, field):
			continue
		if len(values) > 1:
			frappe.log_error(
				title="agent_limits_move_to_the_configuration: shapes disagree",
				message=f"{config_name}.{field} is set to {sorted(values)} on different shapes; the record is left blank.",
			)
			continue
		value = values.pop()
		frappe.db.set_value("AI Agent Configuration", config_name, field, value if field == "top_p" else cint(value))
