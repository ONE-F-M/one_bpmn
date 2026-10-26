"""Repair AI Agent Runs recorded before a resume stopped writing turns again.

A parked and resumed tool-calling run had its earlier turns written again as
new steps on every resume, and a turn cap step that repeated the whole run's
tokens. This removes the repeated steps, zeroes the turn cap steps and
recalculates each touched run's totals from the steps that remain.
"""

import frappe
from frappe.query_builder import DocType
from frappe.query_builder import functions as fn
from frappe.utils import flt

from one_bpmn.agents.observability import _sum_step_metrics

TURN_CAP_MESSAGE = "turn cap exhausted"
TURN_KINDS = ("model_call", "tool_turn")
DUPLICATE_KEY = (
	"role",
	"content",
	"latency_ms",
	"prompt_tokens",
	"completion_tokens",
	"cache_read_tokens",
	"cache_write_tokens",
	"error_message",
)
ZEROED_FIELDS = (
	"prompt_tokens",
	"completion_tokens",
	"cache_read_tokens",
	"cache_write_tokens",
	"cost",
	"input_cost",
	"output_cost",
	"cache_read_cost",
	"cache_write_cost",
	"latency_ms",
)


def execute():
	runs = sorted(_runs_with_repeated_turns() | _runs_with_costed_turn_caps())
	repaired = total_deleted = total_zeroed = 0
	for batch in _batched(runs, 500):
		for run in frappe.get_all("AI Agent Run", filters={"name": ["in", batch]}, pluck="name"):
			before = frappe.db.get_value(
				"AI Agent Run", run, ["total_prompt_tokens", "estimated_cost"], as_dict=True
			)
			deleted = _delete_repeated_turns(run)
			zeroed = _zero_turn_cap_steps(run)
			if not (deleted or zeroed):
				continue
			_recalculate(run)
			after = frappe.db.get_value(
				"AI Agent Run", run, ["total_prompt_tokens", "estimated_cost"], as_dict=True
			)
			repaired += 1
			total_deleted += deleted
			total_zeroed += zeroed
			print(
				f"{run}: {deleted} repeated steps deleted, {zeroed} turn cap steps zeroed, "
				f"prompt tokens {before.total_prompt_tokens} -> {after.total_prompt_tokens}, "
				f"cost {before.estimated_cost} -> {after.estimated_cost}"
			)
	print(
		f"repaired {repaired} runs: {total_deleted} repeated steps deleted, {total_zeroed} turn cap steps zeroed"
	)


def _runs_with_repeated_turns() -> set:
	Step = DocType("AI Agent Step")
	rows = (
		frappe.qb.from_(Step)
		.select(Step.run)
		.where(Step.step_kind.isin(TURN_KINDS))
		.groupby(Step.run, *(Step[f] for f in DUPLICATE_KEY if f != "content"))
		.having(fn.Count("*") > 1)
	).run(as_dict=True)
	return {r["run"] for r in rows if r["run"]}


def _runs_with_costed_turn_caps() -> set:
	Step = DocType("AI Agent Step")
	costed = (Step.prompt_tokens > 0) | (Step.completion_tokens > 0) | (Step.cost > 0) | (Step.latency_ms > 0)
	rows = (
		frappe.qb.from_(Step)
		.select(Step.run)
		.distinct()
		.where(Step.error_message == TURN_CAP_MESSAGE)
		.where(costed)
	).run(as_dict=True)
	return {r["run"] for r in rows if r["run"]}


def _delete_repeated_turns(run: str) -> int:
	steps = frappe.get_all(
		"AI Agent Step",
		filters={"run": run, "step_kind": ["in", TURN_KINDS]},
		fields=["name", *DUPLICATE_KEY],
		order_by="step_index asc",
	)
	seen = set()
	deleted = 0
	for step in steps:
		key = tuple(step.get(f) for f in DUPLICATE_KEY)
		if key in seen:
			frappe.delete_doc("AI Agent Step", step.name, force=True, ignore_permissions=True)
			deleted += 1
		else:
			seen.add(key)
	return deleted


def _zero_turn_cap_steps(run: str) -> int:
	steps = frappe.get_all(
		"AI Agent Step",
		filters={"run": run, "error_message": TURN_CAP_MESSAGE},
		fields=["name", *ZEROED_FIELDS],
	)
	costed = [step.name for step in steps if any(flt(step.get(f)) for f in ZEROED_FIELDS)]
	for name in costed:
		frappe.db.set_value("AI Agent Step", name, dict.fromkeys(ZEROED_FIELDS, 0), update_modified=False)
	return len(costed)


def _recalculate(run: str) -> None:
	totals = _sum_step_metrics(run)
	frappe.db.set_value(
		"AI Agent Run",
		run,
		{
			"total_prompt_tokens": totals["prompt_tokens"],
			"total_completion_tokens": totals["completion_tokens"],
			"total_tokens": totals["prompt_tokens"] + totals["completion_tokens"],
			"total_cache_read_tokens": totals["cache_read_tokens"],
			"total_cache_write_tokens": totals["cache_write_tokens"],
			"estimated_cost": totals["cost"],
			"total_input_cost": totals["input_cost"],
			"total_output_cost": totals["output_cost"],
			"total_cache_read_cost": totals["cache_read_cost"],
			"total_cache_write_cost": totals["cache_write_cost"],
			"agent_latency_ms": totals["agent_latency_ms"],
		},
		update_modified=False,
	)


def _batched(items, size):
	for start in range(0, len(items), size):
		yield items[start : start + size]
