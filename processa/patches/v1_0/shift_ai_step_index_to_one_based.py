# Copyright (c) 2026, one-fm and contributors
# AI Agent Step.step_index is now 1-based (steps read "#1, #2, …" in the run
# inspector). Shift every existing 0-based row up by one so historical runs
# display consistently with new ones. Idempotence: guarded by patch tracking
# (frappe runs a patch once); the shift itself preserves relative order.

import frappe
from frappe.query_builder import DocType


def execute():
	Step = DocType("AI Agent Step")
	(
		frappe.qb.update(Step)
		.set(Step.step_index, Step.step_index + 1)
	).run()
