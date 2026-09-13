"""Rename the case type "Generation" to "Output".

The six types a case can be were settled as Output, Trajectory, Trigger,
Adversarial, Co-Load Budget and Memory. "Generation" was the old name for the
first of those, and it is the only value with rows behind it — everything else
in the old list was never used.

Written against the column rather than the documents: nothing else on a case
changes, and there is no validation to re-run.
"""

import frappe


def execute():
	frappe.reload_doc("one_bpmn", "doctype", "ai_eval_case")
	frappe.db.sql("""update `tabAI Eval Case` set case_type = 'Output' where case_type = 'Generation'""")
	frappe.db.commit()
