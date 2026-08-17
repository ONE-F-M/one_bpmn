# Copyright (c) 2026, one-fm and contributors
"""Close the one-word hole in the instruction-override rules (WI-001840).

Two rules were meant to cover "make the model drop its instructions", and there
was a gap exactly between them:

* ``ignore-previous-instructions`` allowed ``all`` and ``any`` between the verb
  and "previous" — and nothing else.
* ``disregard-your-instructions`` allowed ``your``, but its verb list did not
  include ``ignore``.

So "ignore all previous instructions" was caught and **"ignore your previous
instructions" was not**. One word defeated the flagship rule of the pack, and it
is the phrasing a model is at least as likely to be given. Found while testing
AC4: the payload went into long-term memory verbatim, which is precisely the
"standing instruction that outlives the conversation" that criterion exists to
stop.

The widened rule takes the determiners as a repeated optional group
(``all``/``any``/``the``/``your``/``my``), adds the verbs the sibling rule
already knew about, and adds ``rule``/``rules`` as objects.

Verified not to widen into ordinary language: "ignore the draft rows in the June
report" — the benign control the pack ships for exactly this — still does not
match, because the object has to be an instruction, not a noun that happens to
follow "ignore".

ONLY updates a rule still carrying the shipped pattern. A site that has tuned
its own is left alone — the pack is configuration, and a patch that overwrites
somebody's tuning is worse than one that does nothing.
"""

import frappe

RULE = "ignore-previous-instructions"

# What the seed patch shipped. Matched exactly, so an edited rule is skipped.
OLD = (
	r"\bignore\s+(?:all\s+|any\s+)?(?:previous|prior|earlier|above)\s+"
	r"(?:instruction|instructions|prompt|prompts|direction|directions)\b"
)

NEW = (
	r"\b(?:ignore|disregard|forget|override)\s+"
	r"(?:all\s+|any\s+|the\s+|your\s+|my\s+)*"
	r"(?:previous|prior|earlier|above|preceding)\s+"
	r"(?:instruction|instructions|prompt|prompts|direction|directions|rule|rules)\b"
)


def execute():
	if not frappe.db.table_exists("AI Injection Pattern"):
		return

	name = frappe.db.get_value("AI Injection Pattern", {"pattern_name": RULE}, "name")
	if not name:
		# Site predates the pack, or has retired this rule. The seed patch owns
		# creating it; this one only widens what is already there.
		return

	current = frappe.db.get_value("AI Injection Pattern", name, "pattern")
	if current != OLD:
		frappe.logger("one_bpmn").info(
			f"widen_instruction_override_pattern: {RULE} has been edited on this "
			"site; leaving it as the admin set it"
		)
		return

	doc = frappe.get_doc("AI Injection Pattern", name)
	doc.pattern = NEW
	# Saved through the document so the doctype's own validation compiles the
	# regex. A pattern that cannot compile disables screening for everyone, so
	# it must never reach the database unchecked.
	doc.save(ignore_permissions=True)

	frappe.logger("one_bpmn").info(f"widen_instruction_override_pattern: {RULE} widened")
