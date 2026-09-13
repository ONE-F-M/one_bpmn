# Copyright (c) 2026, one-fm and contributors
"""Score real conversations, chosen for what they can teach.

Offline suites answer "does the agent still do what we wrote down". They cannot
answer "how is it doing on the traffic it actually gets", because nobody writes
a case for the question a user asked yesterday.

This samples finished production runs and scores them with the same assertion
machinery the suites use, against a rubric the agent carries — general
standards rather than a case's specific expectations, since a sampled answer
has no case behind it.

Sampling is deliberately NOT a flat percentage. A flat sample of this site's
traffic is mostly runs that went fine: of 3,417 production runs, 2,086
completed and 66 did not. Ten random runs a week would meet the failures about
twice a year. So each candidate carries a weight, and the draw is random
against those weights — the informative ones come up often, the ordinary ones
still come up sometimes, and nothing is guaranteed a place. Taking the worst N
instead would measure only the tail and never notice the middle drifting.
"""

from __future__ import annotations

import json
import random

import frappe
from frappe.utils import flt, now_datetime

# What makes a run worth looking at, and how much. Weights multiply, so a run
# that was expensive AND abandoned outranks either on its own — which is the
# combination most worth reading.
DEFAULT_WEIGHTS = {
	"base": 1.0,
	"abandoned": 6.0,      # the map never reached its end
	"corrected": 5.0,      # a person told us it was wrong
	"errored": 4.0,        # it failed outright
	"retried": 2.0,        # it needed another go
	"expensive": 3.0,      # top decile of spend in the window
}

# A sampled run is scored by every assertion in the agent's rubric suite; each
# llm_judge among them is a billed call, so a sweep is capped.
DEFAULT_SAMPLE_SIZE = 10


def rubric_suite(agent: str) -> str | None:
	"""The suite holding this agent's online standards, if it has one."""
	return frappe.db.get_value(
		"AI Eval Suite",
		{"agent_configuration": agent, "suite_type": "Online Rubric"},
		"name",
	)


def rubric_assertions(suite: str) -> list:
	"""The rubric: every assertion on every case in the rubric suite.

	Assertions live on cases, so a rubric suite is one case (or a few) whose
	assertions are the standards. Reusing the case row keeps the rubric
	editable in the same screen as everything else rather than inventing a
	second place to write assertions.
	"""
	cases = frappe.get_all("AI Eval Case", filters={"suite": suite}, pluck="name")
	if not cases:
		return []
	return frappe.get_all(
		"AI Eval Assertion",
		filters={"parenttype": "AI Eval Case", "parent": ["in", cases]},
		fields=["assertion_type", "value", "judge_provider", "judge_model", "pass_threshold"],
		order_by="idx asc",
	)


def candidates(agent: str, window_hours: int = 24) -> list[dict]:
	"""Finished production runs for *agent* inside the window, with their signals.

	Runs still going, and runs that produced nothing to read, are not
	candidates: there is no answer to score.
	"""
	rows = frappe.db.sql(
		"""
		select r.name, r.status, r.goal_completion, r.retry_count, r.estimated_cost,
		       r.final_output, r.creation
		from `tabAI Agent Run` r
		where r.origin = 'production'
		  and r.agent_configuration = %(agent)s
		  and r.status in ('Success', 'Error')
		  and r.creation >= date_sub(now(), interval %(hours)s hour)
		""",
		{"agent": agent, "hours": int(window_hours)},
		as_dict=True,
	)
	rows = [r for r in rows if (r.get("final_output") or "").strip()]
	if not rows:
		return []

	corrected = set()
	names = [r["name"] for r in rows]
	for row in frappe.get_all(
		"AI Response Feedback",
		filters={"agent_run": ["in", names], "rating": "Negative"},
		fields=["agent_run"],
	):
		corrected.add(row.agent_run)

	# "Expensive" is relative to the window, not to a number someone set last
	# year: a threshold in currency goes stale the moment models are switched.
	#
	# Strictly above the 90th percentile, never equal to it. On a flat window —
	# a dozen runs at the same fraction of a cent — the percentile IS the common
	# value, so ">=" called every run expensive and the signal said nothing.
	costs = sorted(flt(r.get("estimated_cost")) for r in rows)
	cutoff = costs[int(len(costs) * 0.9)] if len(costs) >= 10 else costs[-1]

	for r in rows:
		r["is_abandoned"] = r.get("goal_completion") == "Not Achieved"
		r["is_corrected"] = r["name"] in corrected
		r["is_errored"] = r.get("status") == "Error"
		r["is_retried"] = int(r.get("retry_count") or 0) > 0
		r["is_expensive"] = flt(r.get("estimated_cost")) > cutoff
	return rows


def weigh(run: dict, weights: dict | None = None) -> tuple[float, str]:
	"""How strongly this run should be drawn, and why — the why is recorded on
	the result so a reader knows what the sample was biased by."""
	w = {**DEFAULT_WEIGHTS, **(weights or {})}
	weight = w["base"]
	reasons = []
	for flag, key, label in (
		("is_abandoned", "abandoned", "abandoned"),
		("is_corrected", "corrected", "corrected by a person"),
		("is_errored", "errored", "errored"),
		("is_retried", "retried", "retried"),
		("is_expensive", "expensive", "top-decile cost"),
	):
		if run.get(flag):
			weight *= w[key]
			reasons.append(label)
	return weight, ", ".join(reasons) or "ordinary traffic"


def draw(runs: list[dict], size: int, weights: dict | None = None, seed=None) -> list[dict]:
	"""Pick *size* runs at random, weighted. Never the same run twice.

	Weighted RANDOM, not top-N: the point is a sample that leans toward the
	informative runs while still seeing ordinary ones, because a measure built
	only on the tail cannot notice the middle getting worse.
	"""
	pool = []
	for run in runs:
		weight, reason = weigh(run, weights)
		pool.append({**run, "_weight": weight, "sample_reason": reason})

	rng = random.Random(seed)
	chosen = []
	while pool and len(chosen) < size:
		total = sum(p["_weight"] for p in pool)
		if total <= 0:
			break
		mark = rng.uniform(0, total)
		running = 0.0
		for index, item in enumerate(pool):
			running += item["_weight"]
			if running >= mark:
				chosen.append(pool.pop(index))
				break
		else:
			chosen.append(pool.pop())
	return chosen


def score(run: dict, assertions: list) -> dict:
	"""Score one sampled answer against the rubric, and report what it cost."""
	from one_bpmn.agents.eval_runner import _evaluate_assertion

	answer = run.get("final_output") or ""
	results = [_evaluate_assertion(frappe._dict(a), answer) for a in assertions]
	failed = [r for r in results if not r.get("passed")]
	errored = any(r.get("error") for r in results)
	cost = sum(flt(r.get("judge_cost")) for r in results)

	return {
		"source_run": run["name"],
		"sample_reason": run.get("sample_reason") or "",
		"status": "Error" if errored else ("Passed" if not failed else "Failed"),
		"actual_output": answer[:140000],
		"assertion_results": json.dumps(results, default=str),
		"error_message": "; ".join(
			f"{r.get('assertion_type')}: {r.get('message') or r.get('explanation') or ''}".strip(": ")
			for r in failed
		)[:1000],
		"cost": cost,
		"tokens_used": sum(
			int(r.get("judge_prompt_tokens") or 0) + int(r.get("judge_completion_tokens") or 0)
			for r in results
		),
	}


def sweep(agent: str, window_hours: int = 24, size: int = DEFAULT_SAMPLE_SIZE,
		  spend_cap: float = 0, weights: dict | None = None, seed=None) -> dict:
	"""Sample this agent's recent production runs and score them.

	Returns a summary and, when anything was scored, the AI Eval Run holding
	the detail — the same record every other kind of run lands in, so the
	scores are read where scores are already read.
	"""
	suite = rubric_suite(agent)
	if not suite:
		return {"agent": agent, "scored": 0, "problem": f"{agent} has no Online Rubric suite."}

	assertions = rubric_assertions(suite)
	if not assertions:
		return {"agent": agent, "scored": 0,
				"problem": f"The rubric suite for {agent} has no assertions to judge by."}

	pool = candidates(agent, window_hours)
	if not pool:
		return {"agent": agent, "scored": 0,
				"problem": f"No finished production run for {agent} in the last {window_hours}h."}

	run_doc = frappe.get_doc({
		"doctype": "AI Eval Run",
		"suite": suite,
		"agent_configuration": agent,
		"status": "Running",
		"scope": "Online",
		"backend": "replay",
		"spend_cap": flt(spend_cap),
		"started_at": now_datetime(),
	})
	run_doc.flags.ignore_mandatory = True
	run_doc.insert(ignore_permissions=True)

	spent = 0.0
	passed = failed = 0
	stopped = ""
	for sample in draw(pool, size, weights, seed):
		if spend_cap and spent >= spend_cap:
			stopped = (f"Stopped on budget: spent {spent:.4f} of a {flt(spend_cap):.4f} ceiling "
					   f"after {passed + failed} sample(s).")
			break
		row = score(sample, assertions)
		spent += flt(row["cost"])
		run_doc.append("results", row)
		if row["status"] == "Passed":
			passed += 1
		else:
			failed += 1

	run_doc.total_cases = passed + failed
	run_doc.passed_cases = passed
	run_doc.failed_cases = failed
	run_doc.total_cost = spent
	run_doc.status = "Passed" if not failed else "Failed"
	if stopped:
		run_doc.stop_reason = stopped
	run_doc.ended_at = now_datetime()
	run_doc.save(ignore_permissions=True)

	return {
		"agent": agent,
		"suite": suite,
		"run": run_doc.name,
		"pool": len(pool),
		"scored": passed + failed,
		"passed": passed,
		"failed": failed,
		"spent": spent,
		"stopped": stopped,
		"rate": (passed / (passed + failed) * 100) if (passed + failed) else None,
		"failures": [
			{"run": r.source_run, "why": r.error_message, "sampled_because": r.sample_reason}
			for r in run_doc.results if r.status != "Passed"
		],
	}
