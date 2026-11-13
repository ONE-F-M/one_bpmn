# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Give the nightly sweep something to run.

The sweep picks up every suite whose CI Role is Nightly. On the BA site no
suite carries that role at all, so the 02:30 process would wake, find nothing,
and report an empty night — which reads exactly like a night where nothing went
wrong.

The two agent baselines are what the nightly is for: they call the real agents
on the site where those agents live, which is the one question a pull request
can never answer. They also gate deployment, so a nightly run keeps the number
that gate reads fresh instead of it ageing until someone happens to deploy.

Only these two, and only if they are here. A site without an agent has nothing
to measure, and tagging a suite it cannot run would spend the night failing.
"""

import frappe

SUITES = ("Connector Agent — Baseline", "Orchestrator Agent — Baseline")


def execute():
	tagged = []
	for title in SUITES:
		name = frappe.db.get_value("AI Eval Suite", {"title": title}, "name")
		if not name:
			continue
		if frappe.db.get_value("AI Eval Suite", name, "ci_role") == "Nightly":
			continue
		frappe.db.set_value("AI Eval Suite", name, "ci_role", "Nightly")
		tagged.append(title)

	if tagged:
		frappe.db.commit()
		print(f"agent_baselines_run_nightly: {', '.join(tagged)}")
