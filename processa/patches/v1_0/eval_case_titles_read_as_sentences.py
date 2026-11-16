"""Eval case titles read as sentences, not as a label, a dash and a fragment.

The Connector and Orchestrator suites titled their cases "Trajectory — the
reference is read before the connector is written": the case type first, a dash,
then the point. The type is already a field on the case, so the prefix said
nothing the row did not, and the dash left a fragment where a sentence should
be. The seed patches now write the sentence; this brings the cases those seeds
already created into line, matched by their old titles, so a site that has run
them reads the same as one that has not.
"""

import frappe

RENAMES = {
	# Orchestrator Agent — Baseline
	"Work no specialist covers — none is invented":
		"Work no specialist covers is reported, not handed to an invented one",
	"Work needing a person — handed over, not just described":
		"Work that needs a person is handed over, not just described",
	# Connector Agent — Baseline
	"Documented public API — a connector is written and left disabled":
		"A documented public API becomes a connector that is left disabled",
	"Authenticated API — the missing credential is reported, not invented":
		"An authenticated API has its missing credential reported, not invented",
	"Unreadable reference — says so instead of inventing a manifest":
		"An unreadable reference is admitted instead of inventing a manifest",
	# Connector Agent — Case Types
	"Output — the answer says the connector was left disabled":
		"The answer says the connector was left disabled",
	"Trajectory — the reference is read before the connector is written":
		"The reference is read before the connector is written",
	"Trigger Positive — the skill fires on a documented API":
		"The skill fires on a documented API",
	"Trigger Negative — the skill stays quiet when there is nothing to read":
		"The skill stays quiet when there is nothing to read",
	"Adversarial — a connector is not enabled on request":
		"A connector is not enabled on request",
	"Co-Load Budget — loading the skill stays inside its context cost":
		"Loading the skill stays inside its context cost",
	"Memory — the API named earlier is the one built":
		"The API named earlier is the one built",
	# Connector Agent — Trajectory Modes
	"ANY_ORDER — the reference is read and the connector written, in either order":
		"The reference is read and the connector written, in either order",
	"EXACT — given no work order, it reads, finds nothing, and stops":
		"Given no work order, it reads, finds nothing, and stops",
}


def execute():
	renamed = 0
	for old, new in RENAMES.items():
		for name in frappe.get_all("AI Eval Case", filters={"title": old}, pluck="name"):
			frappe.db.set_value("AI Eval Case", name, "title", new, update_modified=False)
			renamed += 1
	frappe.db.commit()
	print(f"eval_case_titles_read_as_sentences: {renamed} case(s) renamed")
