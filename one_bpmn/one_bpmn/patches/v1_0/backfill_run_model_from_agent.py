# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A run that never recorded its model takes the one its agent configuration
names today. Older runs left the field empty, so the runs page could not say
what they ran on."""

from __future__ import annotations

import frappe
from frappe.query_builder import DocType


def execute():
	Run = DocType("AI Agent Run")
	Agent = DocType("AI Agent Configuration")
	rows = (
		frappe.qb.from_(Run).join(Agent).on(Run.agent_configuration == Agent.name)
		.select(Run.name, Agent.ai_model)
		.where(Run.model.isnull() | (Run.model == ""))
		.where(Agent.ai_model.isnotnull() & (Agent.ai_model != ""))
	).run(as_dict=True)
	for row in rows:
		frappe.db.set_value("AI Agent Run", row.name, "model", row.ai_model, update_modified=False)
	if rows:
		frappe.db.commit()
