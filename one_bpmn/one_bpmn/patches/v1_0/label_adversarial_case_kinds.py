# Copyright (c) 2026, one-fm and contributors
"""Give the adversarial pack's existing cases their kind (WI-001840, AC5).

AC5 asks for two numbers: attack success rate, and false-positive rate. Both are
computed from `case_kind` on AI Eval Case, and an unlabelled case counts toward
NEITHER denominator — deliberately, because guessing what a case measures would
put an untraceable number into a rate somebody acts on.

Every attack case seeded before this story predates the field. Left alone, a
site's adversarial suites look fully populated and report "not measurable", which
is the one outcome AC5 says is not acceptable.

This is a migration, not configuration: these rows were written by the platform's
own pack, and this brings them up to the schema the pack now writes. It does not
create, seed or opt anyone into anything — a site with no adversarial suites gets
no rows and no side effects.

Only titles the pack itself seeds are touched. A case somebody added by hand is
left unlabelled, because we do not know what it measures and inventing an answer
is worse than reporting one fewer case.

adversarial_pack._label_legacy_cases does the same repair whenever a suite is
rebuilt; this covers the sites that never rebuild one.
"""

import frappe


def execute():
	if not frappe.db.table_exists("AI Eval Case"):
		return
	if not frappe.get_meta("AI Eval Case").get_field("case_kind"):
		# The doctype sync has not landed yet on this site; the next migrate
		# runs the patch again with the field in place.
		return

	from one_bpmn.agents.adversarial_pack import BENIGN_CASES, CASES

	kinds = {t: "Attack" for t, _a, _r in CASES}
	kinds.update({t: "Benign Control" for t, _p, _r in BENIGN_CASES})

	rows = frappe.get_all(
		"AI Eval Case",
		filters={"case_kind": ["in", ["", None]], "title": ["in", list(kinds)]},
		fields=["name", "title"],
		limit_page_length=0,
	)
	for row in rows:
		frappe.db.set_value(
			"AI Eval Case", row["name"], "case_kind", kinds[row["title"]], update_modified=False
		)

	if rows:
		frappe.logger("one_bpmn").info(
			f"label_adversarial_case_kinds: labelled {len(rows)} case(s)"
		)
