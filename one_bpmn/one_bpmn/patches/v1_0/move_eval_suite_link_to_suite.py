"""
WI-001743: move the Suite<->Agent link onto AI Eval Suite.

The link used to live on AI Agent Configuration.eval_suite (one suite per
agent). It now lives on AI Eval Suite.agent_configuration (the only linkage;
an agent may have many suites). This patch copies every existing
configuration -> suite pairing onto the suite side.

Idempotent: guards on the old column still existing, and skips suites that
already carry the correct link. Frappe does not drop removed columns on
migrate, so the old ``eval_suite`` values are still readable here (this patch
runs post-model-sync, after ``agent_configuration`` has been created).

Collision rule (confirmed): if two configurations referenced the same suite,
the last one processed wins and the overwrite is logged — a single suite can
only point back to one agent.
"""

import frappe
from frappe.query_builder import DocType


def execute():
	# Old column gone (fresh install or already migrated) -> nothing to do.
	if not frappe.db.has_column("AI Agent Configuration", "eval_suite"):
		return

	Cfg = DocType("AI Agent Configuration")
	rows = (
		frappe.qb.from_(Cfg)
		.select(Cfg.name, Cfg.eval_suite)
		.where(Cfg.eval_suite.isnotnull() & (Cfg.eval_suite != ""))
	).run(as_dict=True)

	for row in rows:
		config_name = row["name"]
		suite_name = row["eval_suite"]

		if not frappe.db.exists("AI Eval Suite", suite_name):
			frappe.log_error(
				title="WI-001743 eval-suite migration: dangling suite link",
				message=f"AI Agent Configuration {config_name} pointed at missing "
				f"AI Eval Suite {suite_name}; skipped.",
			)
			continue

		current = frappe.db.get_value("AI Eval Suite", suite_name, "agent_configuration")
		if current == config_name:
			continue  # already migrated
		if current:
			frappe.log_error(
				title="WI-001743 eval-suite migration: link collision",
				message=f"AI Eval Suite {suite_name} was already linked to "
				f"{current}; reassigning to {config_name} (last wins).",
			)

		frappe.db.set_value(
			"AI Eval Suite", suite_name, "agent_configuration", config_name,
			update_modified=False,
		)

	frappe.db.commit()
