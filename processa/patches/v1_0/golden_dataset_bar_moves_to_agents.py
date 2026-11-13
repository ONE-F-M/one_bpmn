"""The golden dataset minimum and target move from Processa Settings to the agent.

One site-wide pair said what counted as a representative dataset for every
agent at once. That is a judgement about one agent's work, so each agent now
carries its own, and an agent that has set none shows a count with no bar.

Whatever the site had set is carried onto every agent that already has an eval
suite, so nothing that read as short yesterday reads as complete today. The two
Singles rows are then removed: the fields are gone from the doctype and would
otherwise sit there looking like settings.
"""

import frappe
from frappe.utils import cint

FIELDS = ("golden_dataset_minimum", "golden_dataset_target")


def _site_value(field: str) -> int:
	# Read raw: the fields are gone from the doctype, and tabSingles has no
	# `modified` column for get_value's default ordering to lean on.
	return cint(frappe.db.get_value(
		"Singles", {"doctype": "Processa Settings", "field": field}, "value", order_by=None
	))


def execute():
	minimum, target = (_site_value(f) for f in FIELDS)
	if minimum or target:
		agents = {
			a for a in frappe.get_all("AI Eval Suite", pluck="agent_configuration")
			if a and frappe.db.exists("AI Agent Configuration", a)
		}
		for agent in sorted(agents):
			frappe.db.set_value(
				"AI Agent Configuration", agent,
				{"golden_dataset_minimum": minimum, "golden_dataset_target": target},
				update_modified=False,
			)
		print(f"golden dataset bar {minimum}/{target} carried onto {len(agents)} agent(s)")
	frappe.db.delete("Singles", {"doctype": "Processa Settings", "field": ["in", list(FIELDS)]})
