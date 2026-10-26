"""Say what asked for each eval run that already exists.

Until now it was inferred at read time from scope and backend. The inference is
right for every run made so far, so it is applied once here and the field takes
over — which is the point: the inference is wrong the first time somebody runs a
nightly suite by hand, and a page built on it would mislabel that run forever.
"""

import frappe


def execute():
	frappe.reload_doc("one_bpmn", "doctype", "ai_eval_run")

	# Order matters: the later rules are the more specific ones.
	frappe.db.sql("""update `tabAI Eval Run` set triggered_by = 'By hand' where ifnull(triggered_by,'') = ''""")
	frappe.db.sql("""update `tabAI Eval Run` set triggered_by = 'Pull request'
		where ifnull(triggered_by,'') in ('', 'By hand') and backend = 'deterministic'""")
	frappe.db.sql("""update `tabAI Eval Run` r
		join `tabAI Eval Suite` s on r.suite = s.name
		set r.triggered_by = 'Nightly sweep'
		where ifnull(r.triggered_by,'') in ('', 'By hand') and s.ci_role = 'Nightly' and r.backend = 'live'""")
	frappe.db.sql("""update `tabAI Eval Run` set triggered_by = 'Online sample' where scope = 'Online'""")
	frappe.db.commit()
