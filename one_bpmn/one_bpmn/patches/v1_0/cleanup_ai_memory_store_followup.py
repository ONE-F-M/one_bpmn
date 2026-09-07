# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Follow-up to cleanup_ai_memory_store: one more confirmed echo row (WI-002165).

cleanup_ai_memory_store's hand-review covered 272 rows, nearly all from
run_logix_agent. A live audit against the business-analyst.one-fm.com store on
2026-09-07 (read-only, via its existing API credentials) turned up a
ProsAlly row outside that review:

- v1jsod3l03 ("When a user provides a complete process specification with
  header, lanes, elements, flows, and validation details, classify the intent
  as GENERATE_NEW and proceed to confirmation before creating the process
  model.") is a paraphrase of ProsAlly's own intent-classifier prompt
  (_PA_INTENT_CLASSIFIER's GENERATE_NEW rule in seed_agent_prompts.py) blended
  with vocabulary from its IR-generation prompt (_PA_PROCESS_GENERATOR's
  lanes/flows/validation checks) — an instruction echo, the same pattern
  cleanup_ai_memory_store removed for Logix.

The same audit also surfaced nfvkc9ictb (Docu, topic "form-field-placement":
"place them logically near related fields... near goal or description
fields"). It is NOT included here: Docu's own seeded field-placement rule
(seed_docu_agent_config.py) is close in spirit but not a clear paraphrase, and
this could equally be a genuine generalization about one_bpmn's own DocType
conventions (e.g. an AI Agent Configuration's own goal/description fields).
Read individually and left for a human call, per the discipline the original
patch documents — a patch should not guess at a near-match.

Same shape as the patch it follows: existence-checked (idempotent, safe to
re-run or run on a site without this row), deletes via frappe.delete_doc
(never raw SQL) so the Deleted Document audit record is kept.
"""

import frappe

DELETE_NAMES = ("v1jsod3l03",)


def execute():
	if not frappe.db.exists("DocType", "AI Memory"):
		return

	deleted, missing, failed = 0, 0, 0
	for name in DELETE_NAMES:
		if not frappe.db.exists("AI Memory", name):
			missing += 1
			continue
		try:
			frappe.delete_doc("AI Memory", name, ignore_permissions=True, force=True)
			deleted += 1
		except Exception:
			failed += 1
			frappe.log_error(
				title="AI Memory cleanup (follow-up): could not delete a reviewed row",
				message=f"name={name}\n{frappe.get_traceback()}",
			)

	frappe.db.commit()
	print(
		f"AI Memory cleanup (follow-up): deleted {deleted}, already gone {missing}, "
		f"failed {failed} (of {len(DELETE_NAMES)} reviewed rows)"
	)
