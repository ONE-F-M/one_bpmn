import collections

import frappe
from frappe.query_builder import DocType
from frappe.query_builder import functions as fn


def execute():
	"""Renumber every run's steps so the first one reads #1.

	shift_ai_step_index_to_one_based added one to every row, on the assumption
	that all of them were 0-based. Sites that had already switched the writer
	over had their correct rows pushed to 2, and rows written 0-based after the
	shift were never moved at all, so a run's first step reads 0, 1 or 2
	depending on when it ran and when that patch reached the site.

	Shifting each run by its own offset repairs all three and does nothing to a
	run that is already right, so it is safe to run again.
	"""
	offsets = collections.defaultdict(list)
	for run, first in _first_step_index().items():
		if first != 1:
			offsets[first - 1].append(run)

	moved = 0
	Step = DocType("AI Agent Step")
	for offset, runs in offsets.items():
		for batch in _batched(runs, 500):
			(
				frappe.qb.update(Step)
				.set(Step.step_index, Step.step_index - offset)
				.where(Step.run.isin(batch))
			).run()
			moved += len(batch)

	print("renumbered the steps of %d runs" % moved)


def _first_step_index() -> dict:
	Step = DocType("AI Agent Step")
	rows = (
		frappe.qb.from_(Step)
		.select(Step.run, fn.Min(Step.step_index).as_("first"))
		.groupby(Step.run)
	).run(as_dict=True)
	return {r["run"]: r["first"] for r in rows if r["run"] and r["first"] is not None}


def _batched(items, size):
	for start in range(0, len(items), size):
		yield items[start : start + size]
