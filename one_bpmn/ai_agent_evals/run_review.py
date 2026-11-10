"""Run review for the Evals console: results, transcripts and per-case history."""

import frappe
from frappe import _

from one_bpmn.ai_agent_evals.suites import run_title


def _agent_transcripts_for_eval_run(eval_run: str) -> dict:
	"""Per-case agent transcripts for one AI Eval Run, keyed by eval case.

	Answers "which tools did this eval actually call?" without leaving the review
	screen. Before AI Agent Run carried ``eval_run`` / ``eval_case`` this could
	only be reconstructed by filtering runs on origin="eval" and matching a time
	window, then opening each AI Agent Step to read its ``tool_calls`` table.

	Judge runs are excluded: they are the assertion's own LLM call, already
	reported per assertion, and carry no steps. Their spend still shows in the
	Result row's totals.

	Three queries regardless of how many runs, steps or tool calls there are -
	the rows are grouped in Python rather than queried per parent.

	Permission: the caller has already passed ``check_permission("read")`` on the
	eval run. This is that run's own execution detail, the same class of data as
	the outputs and judge rubrics the review already shows, so it is not gated
	again on AI Agent Run (which is System-Manager-only at the doctype level and
	would hide it from the process owners this screen is built for).
	"""
	# Imported here rather than at module level: api.evals is loaded on every
	# Processa request, and the eval runner pulls in the executor backends.
	from one_bpmn.ai_agent_evals.runner.assertions import EVAL_RUN_JUDGE

	runs = frappe.get_all(
		"AI Agent Run",
		filters={"eval_run": eval_run, "bpmn_id": ["!=", EVAL_RUN_JUDGE]},
		fields=[
			"name",
			"eval_case",
			"bpmn_id",
			"bpmn_label",
			"element_type",
			"instance",
			"process_model",
			"status",
			"model",
			"provider",
			"total_tokens",
			"estimated_cost",
			"error_message",
			"creation",
		],
		order_by="creation asc",
		limit_page_length=0,
	)
	if not runs:
		return {}

	run_names = [r["name"] for r in runs]
	steps = frappe.get_all(
		"AI Agent Step",
		filters={"run": ["in", run_names]},
		fields=["name", "run", "step_index", "role", "content"],
		order_by="run asc, step_index asc",
		limit_page_length=0,
	)
	calls_by_step = {}
	if steps:
		for call in frappe.get_all(
			"AI Agent Tool Call",
			filters={"parent": ["in", [s["name"] for s in steps]]},
			fields=[
				"parent",
				"tool_name",
				"tool_source",
				"status",
				"tool_args",
				"tool_result",
				"outcome",
				"idx",
			],
			order_by="parent asc, idx asc",
			limit_page_length=0,
		):
			calls_by_step.setdefault(call["parent"], []).append(
				{
					"tool_name": call["tool_name"],
					"tool_source": call["tool_source"],
					# A shape that returns {"error": ...} is still a Success here -
					# execute_shape never raises - so the result is what to read.
					"status": call["status"],
					"tool_args": call["tool_args"],
					"tool_result": call["tool_result"],
					"outcome": call["outcome"],
				}
			)

	steps_by_run = {}
	for s in steps:
		steps_by_run.setdefault(s["run"], []).append(
			{
				"step_index": s["step_index"],
				"role": s["role"],
				"content": s["content"],
				"tool_calls": calls_by_step.get(s["name"], []),
			}
		)

	by_case = {}
	for r in runs:
		run_steps = steps_by_run.get(r["name"], [])
		by_case.setdefault(r["eval_case"] or "", []).append(
			{
				"name": r["name"],
				"bpmn_id": r["bpmn_id"],
				"bpmn_label": r["bpmn_label"],
				"element_type": r["element_type"],
				"instance": r["instance"],
				"process_model": r["process_model"],
				"status": r["status"],
				"model": r["model"],
				"provider": r["provider"],
				"total_tokens": r["total_tokens"],
				"estimated_cost": r["estimated_cost"],
				"error_message": r["error_message"],
				"steps": run_steps,
				"tool_call_count": sum(len(s["tool_calls"]) for s in run_steps),
			}
		)
	return by_case


def get_run_review(run: str, baseline: str = None) -> dict:
	"""Full result of one AI Eval Run for the run-review view:
	summary, per-case results (status, actual output, parsed assertion results
	incl. judge score/reasoning), and a per-case comparison against earlier runs.
	Permission enforced via check_permission (owner/SM).

	``baseline`` optionally pins the comparison to one earlier finished run of the
	same suite. Without it each case is compared against the most recent earlier
	run that actually covered that case - necessary because subset runs mean consecutive runs frequently share no cases at all.
	"""
	doc = frappe.get_doc("AI Eval Run", run)
	doc.check_permission("read")

	suite_title = frappe.db.get_value("AI Eval Suite", doc.suite, "title")
	run_seq = frappe.db.count("AI Eval Run", {"suite": doc.suite, "creation": ["<=", doc.creation]})

	# Look up by the result rows' own case names (not by suite) so a case that
	# was later moved or renamed still resolves. Carries the prompt so the
	# review shows what was evaluated alongside the verdict.
	case_names = [r.eval_case for r in doc.results if r.eval_case]
	case_info = {
		c["name"]: c
		for c in frappe.get_all(
			"AI Eval Case",
			filters={"name": ["in", case_names]} if case_names else {"name": ""},
			fields=["name", "title", "input_user_prompt", "expected_output", "input_context"],
		)
	}

	transcripts = _agent_transcripts_for_eval_run(doc.name)

	results = []
	for r in doc.results:
		info = case_info.get(r.eval_case) or {}
		# Prefer the snapshot taken when the run executed; fall back to the
		# case's current values for runs recorded before snapshots existed.
		results.append(
			{
				"eval_case": r.eval_case,
				"case_title": info.get("title") or r.eval_case,
				"input_user_prompt": r.input_user_prompt or info.get("input_user_prompt") or "",
				"expected_output": r.expected_output or info.get("expected_output") or "",
				"prompt_is_snapshot": bool(r.input_user_prompt),
				# The case's earlier turns and saved state, as the case holds them now.
				"input_context": frappe.parse_json(info.get("input_context"))
				if info.get("input_context")
				else None,
				"status": r.status,
				"runs": r.runs,
				"passes": r.passes,
				"actual_output": r.actual_output,
				"error_message": r.error_message,
				"tokens_used": r.tokens_used,
				"cost": r.cost,
				"assertions": frappe.parse_json(r.assertion_results) or [],
				# What the agent actually did: its steps, and the tools each step
				# called with their arguments and results (WI: eval tool visibility).
				"agent_runs": transcripts.get(r.eval_case, []),
			}
		)

	# Comparison baseline. Every finished run of the suite, oldest first, so the
	# ordinal in each title is its real position and no per-run count query is
	# needed.
	history = frappe.get_all(
		"AI Eval Run",
		filters={"suite": doc.suite, "status": ["in", ["Passed", "Failed"]]},
		fields=["name", "started_at", "creation"],
		order_by="creation asc",
		limit_page_length=0,
	)
	titles = {r["name"]: run_title(suite_title, i + 1, r["started_at"]) for i, r in enumerate(history)}
	earlier = [r for r in history if r["creation"] < doc.creation and r["name"] != doc.name]

	# Selectable baselines, newest first, for the run-vs-run picker.
	baselines = [{"name": r["name"], "display_title": titles[r["name"]]} for r in reversed(earlier)]

	# Which earlier runs to read statuses from. An explicit baseline compares
	# against exactly that run; otherwise each case falls back to the most recent
	# earlier run that actually COVERED it. Since allowed running a
	# subset, consecutive runs often share no cases at all - comparing only
	# against the immediately previous run then yields no deltas even though the
	# case has plenty of history.
	if baseline and baseline not in titles:
		frappe.throw(_("Run '{0}' is not a finished run of this suite.").format(baseline))
	scope = [r for r in earlier if r["name"] == baseline] if baseline else earlier

	case_baselines = {}
	by_run = {}
	if scope and case_names:
		for row in frappe.get_all(
			"AI Eval Result",
			filters={
				"parenttype": "AI Eval Run",
				"parent": ["in", [r["name"] for r in scope]],
				"eval_case": ["in", case_names],
			},
			fields=["parent", "eval_case", "status"],
		):
			by_run.setdefault(row["parent"], {})[row["eval_case"]] = row["status"]
		# Newest first, so the first run carrying a case wins.
		for run in reversed(scope):
			for case, status in by_run.get(run["name"], {}).items():
				case_baselines.setdefault(
					case,
					{
						"status": status,
						"run": run["name"],
						"run_title": titles[run["name"]],
					},
				)

	# Kept for the header back-link: the immediately preceding run.
	previous = None
	if earlier:
		last = earlier[-1]
		previous = {
			"name": last["name"],
			"display_title": titles[last["name"]],
			# Per-case statuses now come from case_baselines; retained so an
			# older frontend build keeps working.
			"case_status": by_run.get(last["name"], {}),
		}

	return {
		"run": {
			"name": doc.name,
			"display_title": run_title(suite_title, run_seq, doc.started_at),
			"suite": doc.suite,
			"status": doc.status,
			"backend": doc.backend,
			"started_at": doc.started_at,
			"ended_at": doc.ended_at,
			"total_cases": doc.total_cases,
			"passed_cases": doc.passed_cases,
			"failed_cases": doc.failed_cases,
			"total_tokens": doc.total_tokens,
			"total_cost": doc.total_cost,
		},
		"results": results,
		"previous": previous,
		# Per-case comparison baseline: {case: {status, run, run_title}}. Each
		# case is compared against the most recent earlier run that covered it,
		# or against ``baseline`` when one was requested.
		"case_baselines": case_baselines,
		# Earlier finished runs of this suite, newest first, for the picker.
		"baselines": baselines,
		"baseline": baseline or None,
	}
