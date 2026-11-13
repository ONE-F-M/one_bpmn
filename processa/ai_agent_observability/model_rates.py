# Copyright (c) 2026, one-fm and contributors
# Scheduled model jobs, registered in hooks.py under scheduler_events.

import frappe


def apply_due_model_rates():
	"""Daily: apply any model rate whose effective date has passed.

	Folding pricing onto AI Model left one rate per model and no date, so a
	published price rise had nowhere to be recorded in advance and depended on
	somebody remembering it. The catalogue carries the dated changes; this is
	what makes them happen. A no-op on any day nothing is due, and it will not
	touch a rate that does not still match the exact published one it replaces.
	"""
	from processa.patches.v1_0.seed_ai_model_catalogue import apply_due_rates

	try:
		for line in apply_due_rates():
			frappe.logger("processa").info(f"AI Model rate applied: {line}")
	except Exception:
		frappe.log_error(title="Model rate update failed", message=frappe.get_traceback())


