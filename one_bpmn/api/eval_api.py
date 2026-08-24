"""
Whitelisted endpoints backing the Processa Evals UI (WI-001681).

Every read goes through ``frappe.get_list`` so the AI Evals permission scoping
(WI-001744) applies automatically — a process owner sees only their own suites,
System Manager sees all.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt
from frappe.utils import get_datetime


def _run_title(suite_title: str, seq: int, started_at) -> str:
	"""Human-readable title for an AI Eval Run (which has no title field):
	the suite title + the run's ordinal + its start time."""
	base = f"{suite_title or 'Suite'} — Run {seq}"
	if started_at:
		try:
			return f"{base} · {get_datetime(started_at).strftime('%Y-%m-%d %H:%M')}"
		except Exception:
			pass
	return base


@frappe.whitelist()
def list_eval_suites() -> dict:
	"""Return the eval suites visible to the current user, each with a summary
	of its latest run, for the Evals console (WI-001745).
	"""
	suites = frappe.get_list(
		"AI Eval Suite",
		fields=["name", "title", "process_model", "agent_configuration", "gate_deployment"],
		order_by="modified desc",
		limit_page_length=0,
	)

	names = [s["name"] for s in suites]
	latest_run: dict[str, dict] = {}
	agent_labels: dict[str, str] = {}
	case_counts: dict[str, int] = {}

	if names:
		# Newest run per suite. get_list keeps this scoped to permitted rows.
		for run in frappe.get_list(
			"AI Eval Run",
			filters={"suite": ["in", names]},
			fields=["suite", "status", "total_cases", "passed_cases", "failed_cases", "ended_at"],
			order_by="creation desc",
			limit_page_length=0,
		):
			latest_run.setdefault(run["suite"], run)

		# Case count per suite (one bulk grouped query).
		for row in frappe.get_all(
			"AI Eval Case",
			filters={"suite": ["in", names]},
			fields=["suite", "count(name) as n"],
			group_by="suite",
		):
			case_counts[row["suite"]] = row["n"]

		configs = [s["agent_configuration"] for s in suites if s.get("agent_configuration")]
		if configs:
			for cfg in frappe.get_all(
				"AI Agent Configuration",
				filters={"name": ["in", list(set(configs))]},
				fields=["name", "agent_name"],
			):
				agent_labels[cfg["name"]] = cfg["agent_name"]

	for s in suites:
		s["latest_run"] = latest_run.get(s["name"])
		s["case_count"] = case_counts.get(s["name"], 0)
		s["agent_name"] = agent_labels.get(s.get("agent_configuration"))

	return {
		"suites": suites,
		"is_system_manager": "System Manager" in frappe.get_roles(),
	}


@frappe.whitelist()
def get_evals_overview(from_date: str = None, to_date: str = None) -> dict:
	"""Portfolio metrics for the Evals console dashboard (WI-001745), scoped to
	the suites the user can see. Suites/cases are structural totals; runs,
	tokens and cost respect the optional date range (like the Insights page).
	Cost is ``AI Eval Run.total_cost`` — the same per-1k pricing as observability.
	"""
	names = [s["name"] for s in frappe.get_list("AI Eval Suite", fields=["name"], limit_page_length=0)]
	overview = {
		"suites": len(names),
		"cases": 0,
		"runs": 0,
		"suites_passing": 0,
		"total_tokens": 0,
		"total_cost": 0.0,
	}
	if not names:
		return overview

	overview["cases"] = frappe.db.count("AI Eval Case", {"suite": ["in", names]})

	run_filters = {"suite": ["in", names]}
	if from_date and to_date:
		run_filters["creation"] = ["between", [from_date, f"{to_date} 23:59:59"]]
	period_runs = frappe.get_all(
		"AI Eval Run", filters=run_filters, fields=["total_tokens", "total_cost"], limit_page_length=0
	)
	overview["runs"] = len(period_runs)
	overview["total_tokens"] = sum((r.get("total_tokens") or 0) for r in period_runs)
	overview["total_cost"] = sum(flt(r.get("total_cost")) for r in period_runs)

	# Suites currently passing = each suite's latest run status is "Passed".
	latest: dict[str, str] = {}
	for r in frappe.get_all(
		"AI Eval Run", filters={"suite": ["in", names]},
		fields=["suite", "status"], order_by="creation desc", limit_page_length=0
	):
		latest.setdefault(r["suite"], r["status"])
	overview["suites_passing"] = sum(1 for st in latest.values() if st == "Passed")

	return overview


def _annotate_run_scope(runs: list, cases: list) -> None:
	"""Add ``case_label`` / ``case_names`` to each run: which cases it covered.

	Prefers the scope recorded at request time (so a Running run, or one that
	errored before any result, still reports its scope). Runs from before that
	was tracked have no scope, so it is derived from their result rows instead.
	"""
	titles = {c["name"]: c["title"] for c in cases}
	total_cases = len(cases)

	# Result-row case names, fetched once for the runs that need deriving.
	needs_derive = [r["name"] for r in runs if not r.get("scope")]
	derived: dict[str, list] = {}
	if needs_derive:
		for row in frappe.get_all(
			"AI Eval Result",
			filters={"parenttype": "AI Eval Run", "parent": ["in", needs_derive]},
			fields=["parent", "eval_case"],
		):
			derived.setdefault(row["parent"], []).append(row["eval_case"])

	for r in runs:
		scope = r.get("scope")
		if scope == "Subset":
			names = frappe.parse_json(r.get("requested_cases")) or []
		elif scope == "Suite":
			names = []  # whole suite — the case list is implicit
		else:
			names = derived.get(r["name"], [])
			# A derived run that covered every current case reads as whole-suite.
			if total_cases and len(set(names)) >= total_cases:
				names = []

		r["case_names"] = [titles.get(n, n) for n in names]
		if not names:
			ran = r.get("total_cases") or total_cases
			r["case_label"] = _("All {0} cases").format(ran) if ran != 1 else _("1 case")
		elif len(names) == 1:
			r["case_label"] = titles.get(names[0], names[0])
		else:
			r["case_label"] = _("{0} of {1} cases").format(len(names), total_cases)


@frappe.whitelist()
def get_suite_detail(suite: str) -> dict:
	"""Suite header, its cases, and recent runs for the suite-detail view
	(WI-001746). Permission is enforced by check_permission (owner / SM).
	"""
	doc = frappe.get_doc("AI Eval Suite", suite)
	doc.check_permission("read")

	agent_name = None
	if doc.agent_configuration:
		agent_name = frappe.db.get_value(
			"AI Agent Configuration", doc.agent_configuration, "agent_name"
		)

	cases = frappe.get_all(
		"AI Eval Case",
		filters={"suite": suite},
		fields=["name", "title", "source_run"],
		order_by="creation asc",
	)
	# Assertion summary per case (one bulk query on the child table). Kept
	# defensive: a hiccup building the summary must never blank the whole
	# detail view — the cases and runs still return, just without chips.
	assertions: dict[str, list] = {}
	if cases:
		try:
			for a in frappe.get_all(
				"AI Eval Assertion",
				filters={"parenttype": "AI Eval Case", "parent": ["in", [c["name"] for c in cases]]},
				fields=["parent", "assertion_type"],
			):
				assertions.setdefault(a["parent"], []).append(a["assertion_type"])
		except Exception:
			frappe.log_error(
				title="Evals: assertion summary failed",
				message=frappe.get_traceback(),
			)
	for c in cases:
		c["assertion_types"] = assertions.get(c["name"], [])

	runs = frappe.get_all(
		"AI Eval Run",
		filters={"suite": suite},
		fields=["name", "status", "backend", "total_cases", "passed_cases",
				"failed_cases", "started_at", "ended_at",
				# Needed by the dashboard's latest-run tokens/cost tiles.
				"total_tokens", "total_cost",
				# Which cases the run covered (WI-001746 follow-up).
				"scope", "requested_cases"],
		order_by="creation desc",
		limit_page_length=20,
	)
	_annotate_run_scope(runs, cases)
	# Number runs by their absolute order (newest first in the list), and give
	# each a readable title so the UI never shows the raw run id.
	total_runs = frappe.db.count("AI Eval Run", {"suite": suite})
	for idx, r in enumerate(runs):
		r["display_title"] = _run_title(doc.title, total_runs - idx, r.get("started_at"))

	# Dashboard metrics for the suite page (WI-001746).
	# Pass-rate sparkline: % of cases passing per run, oldest -> newest.
	spark = []
	for r in reversed(runs):
		tot = r.get("total_cases") or 0
		if tot:
			spark.append(round(100.0 * (r.get("passed_cases") or 0) / tot))
	spark = spark[-12:]
	latest = runs[0] if runs else None
	with_assertions = sum(1 for c in cases if c.get("assertion_types"))
	metrics = {
		"cases": len(cases),
		"runs": total_runs,
		"latest": {
			"status": latest["status"],
			"passed": latest.get("passed_cases") or 0,
			"total": latest.get("total_cases") or 0,
		} if latest else None,
		"pass_rate": round(sum(spark) / len(spark)) if spark else None,
		"latest_tokens": (latest.get("total_tokens") or 0) if latest else 0,
		"latest_cost": flt(latest.get("total_cost")) if latest else 0.0,
		"assertion_coverage": {"with_assertions": with_assertions, "total": len(cases)},
		"sparkline": spark,
	}

	return {
		"suite": {
			"name": doc.name,
			"title": doc.title,
			"process_model": doc.process_model,
			"agent_configuration": doc.agent_configuration,
			"agent_name": agent_name,
			"eval_type": doc.eval_type,
		},
		"cases": cases,
		"runs": runs,
		"metrics": metrics,
	}


_ASSERTION_FIELDS = ("assertion_type", "value", "judge_provider", "judge_model", "pass_threshold")


_ASSERTION_VALUE_LABEL = {
	"llm_judge": _("a rubric describing what a correct answer must contain"),
	"contains": _("the substring the output must contain"),
	"regex": _("the pattern the output must match"),
	"equals": _("the exact text the output must equal"),
	"schema_valid": _("the JSON Schema the output must validate against"),
}


def _set_assertions(case, assertions) -> None:
	"""Replace a case's assertions from a list of dicts (WI-001746).

	``value`` is mandatory on AI Eval Assertion and carries the whole meaning of
	the check — the rubric for llm_judge, the substring for contains, and so on.
	An empty one used to be dropped from the row and then surfaced from
	doc.save() as a bare "MandatoryError: value", which named neither the
	assertion nor the field the author had actually left blank. Reject it here
	instead, saying which assertion and what belongs in it.
	"""
	if isinstance(assertions, str):
		assertions = frappe.parse_json(assertions) or []
	case.set("assertions", [])
	for idx, a in enumerate(assertions or [], start=1):
		if not a.get("assertion_type"):
			continue
		kind = a["assertion_type"]
		if not str(a.get("value") or "").strip():
			frappe.throw(
				_("Assertion {0} ({1}) needs a value — {2}.").format(
					idx, kind, _ASSERTION_VALUE_LABEL.get(kind, _("what the output is checked against"))
				)
			)
		row = {"assertion_type": kind}
		for k in _ASSERTION_FIELDS[1:]:
			if a.get(k) not in (None, ""):
				row[k] = a[k]
		# WI-001751: judge_model is now a Link -> AI Model. Make sure the model
		# record exists so the link validates.
		if row.get("judge_model"):
			row["judge_model"] = _ensure_ai_model(row["judge_model"], row.get("judge_provider"))
		case.append("assertions", row)


def _ensure_ai_model(model_name: str, judge_provider: str = None) -> str:
	"""Return an AI Model name, creating the record if it doesn't exist yet
	(AI Model is autonamed by model_name, so name == model_name)."""
	if not model_name or frappe.db.exists("AI Model", model_name):
		return model_name
	provider = "anthropic"
	if judge_provider:
		pt = (frappe.db.get_value("AI Provider", judge_provider, "provider_type") or "").lower()
		if pt in ("openai", "gemini", "anthropic"):
			provider = pt
	frappe.get_doc({"doctype": "AI Model", "model_name": model_name, "provider": provider}).insert(ignore_permissions=True)
	return model_name


@frappe.whitelist()
def create_eval_case(
	suite: str,
	title: str,
	input_user_prompt: str,
	expected_output: str = "",
	assertions=None,
) -> str:
	"""Create a manual AI Eval Case in ``suite`` with optional assertions
	(WI-001746). Provider/model/system prompt come from the suite's agent
	(WI-001751). The current user must be able to write the suite (owner / SM)."""
	suite_doc = frappe.get_doc("AI Eval Suite", suite)
	suite_doc.check_permission("write")

	case = frappe.get_doc({
		"doctype": "AI Eval Case",
		"suite": suite,
		"title": title,
		"process_model": suite_doc.process_model or None,
		"input_user_prompt": input_user_prompt,
		"expected_output": expected_output,
	})
	_set_assertions(case, assertions)
	case.insert()
	return case.name


@frappe.whitelist()
def get_eval_case(name: str) -> dict:
	"""Full case (fields + assertions) for the edit form (WI-001746)."""
	case = frappe.get_doc("AI Eval Case", name)
	frappe.get_doc("AI Eval Suite", case.suite).check_permission("read")
	return {
		"name": case.name,
		"title": case.title,
		"input_user_prompt": case.input_user_prompt,
		"expected_output": case.expected_output,
		"assertions": [{k: a.get(k) for k in _ASSERTION_FIELDS} for a in case.assertions],
	}


@frappe.whitelist()
def update_eval_case(
	name: str,
	title: str = None,
	input_user_prompt: str = None,
	expected_output: str = None,
	assertions=None,
) -> str:
	"""Edit an existing case, including its assertions (WI-001746). Gated by the
	suite's write permission."""
	case = frappe.get_doc("AI Eval Case", name)
	frappe.get_doc("AI Eval Suite", case.suite).check_permission("write")

	for field, val in (
		("title", title),
		("input_user_prompt", input_user_prompt),
		("expected_output", expected_output),
	):
		if val is not None:
			case.set(field, val)
	if assertions is not None:
		_set_assertions(case, assertions)

	case.save()
	return case.name


def _agent_transcripts_for_eval_run(eval_run: str) -> dict:
	"""Per-case agent transcripts for one AI Eval Run, keyed by eval case.

	Answers "which tools did this eval actually call?" without leaving the review
	screen. Before AI Agent Run carried ``eval_run`` / ``eval_case`` this could
	only be reconstructed by filtering runs on origin="eval" and matching a time
	window, then opening each AI Agent Step to read its ``tool_calls`` table.

	Judge runs are excluded: they are the assertion's own LLM call, already
	reported per assertion, and carry no steps. Their spend still shows in the
	Result row's totals.

	Three queries regardless of how many runs, steps or tool calls there are —
	the rows are grouped in Python rather than queried per parent.

	Permission: the caller has already passed ``check_permission("read")`` on the
	eval run. This is that run's own execution detail, the same class of data as
	the outputs and judge rubrics the review already shows, so it is not gated
	again on AI Agent Run (which is System-Manager-only at the doctype level and
	would hide it from the process owners this screen is built for).
	"""
	# Imported here rather than at module level: eval_api is loaded on every
	# Processa request, and eval_runner pulls in the executor backends.
	from one_bpmn.agents.eval_runner import EVAL_RUN_JUDGE

	runs = frappe.get_all(
		"AI Agent Run",
		filters={"eval_run": eval_run, "bpmn_id": ["!=", EVAL_RUN_JUDGE]},
		fields=[
			"name", "eval_case", "bpmn_id", "bpmn_label", "element_type", "instance",
			"process_model", "status", "model", "provider", "total_tokens",
			"estimated_cost", "error_message", "creation",
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
			fields=["parent", "tool_name", "tool_source", "status", "tool_args",
			        "tool_result", "outcome", "idx"],
			order_by="parent asc, idx asc",
			limit_page_length=0,
		):
			calls_by_step.setdefault(call["parent"], []).append({
				"tool_name": call["tool_name"],
				"tool_source": call["tool_source"],
				# A shape that returns {"error": ...} is still a Success here —
				# execute_shape never raises — so the result is what to read.
				"status": call["status"],
				"tool_args": call["tool_args"],
				"tool_result": call["tool_result"],
				"outcome": call["outcome"],
			})

	steps_by_run = {}
	for s in steps:
		steps_by_run.setdefault(s["run"], []).append({
			"step_index": s["step_index"],
			"role": s["role"],
			"content": s["content"],
			"tool_calls": calls_by_step.get(s["name"], []),
		})

	by_case = {}
	for r in runs:
		run_steps = steps_by_run.get(r["name"], [])
		by_case.setdefault(r["eval_case"] or "", []).append({
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
		})
	return by_case


@frappe.whitelist()
def get_run_review(run: str, baseline: str = None) -> dict:
	"""Full result of one AI Eval Run for the run-review view (WI-001747):
	summary, per-case results (status, actual output, parsed assertion results
	incl. judge score/reasoning), and a per-case comparison against earlier runs.
	Permission enforced via check_permission (owner/SM).

	``baseline`` optionally pins the comparison to one earlier finished run of the
	same suite. Without it each case is compared against the most recent earlier
	run that actually covered that case — necessary because subset runs
	(WI-001746) mean consecutive runs frequently share no cases at all.
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
			fields=["name", "title", "input_user_prompt", "expected_output"],
		)
	}

	transcripts = _agent_transcripts_for_eval_run(doc.name)

	results = []
	for r in doc.results:
		info = case_info.get(r.eval_case) or {}
		# Prefer the snapshot taken when the run executed; fall back to the
		# case's current values for runs recorded before snapshots existed.
		results.append({
			"eval_case": r.eval_case,
			"case_title": info.get("title") or r.eval_case,
			"input_user_prompt": r.input_user_prompt or info.get("input_user_prompt") or "",
			"expected_output": r.expected_output or info.get("expected_output") or "",
			"prompt_is_snapshot": bool(r.input_user_prompt),
			"status": r.status,
			"actual_output": r.actual_output,
			"error_message": r.error_message,
			"tokens_used": r.tokens_used,
			"cost": r.cost,
			"assertions": frappe.parse_json(r.assertion_results) or [],
			# What the agent actually did: its steps, and the tools each step
			# called with their arguments and results (WI: eval tool visibility).
			"agent_runs": transcripts.get(r.eval_case, []),
		})

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
	titles = {
		r["name"]: _run_title(suite_title, i + 1, r["started_at"])
		for i, r in enumerate(history)
	}
	earlier = [r for r in history if r["creation"] < doc.creation and r["name"] != doc.name]

	# Selectable baselines, newest first, for the run-vs-run picker.
	baselines = [{"name": r["name"], "display_title": titles[r["name"]]} for r in reversed(earlier)]

	# Which earlier runs to read statuses from. An explicit baseline compares
	# against exactly that run; otherwise each case falls back to the most recent
	# earlier run that actually COVERED it. Since WI-001746 allowed running a
	# subset, consecutive runs often share no cases at all — comparing only
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
				case_baselines.setdefault(case, {
					"status": status,
					"run": run["name"],
					"run_title": titles[run["name"]],
				})

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
			"display_title": _run_title(suite_title, run_seq, doc.started_at),
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


# ── Suite ↔ Agent management from the Evals page (WI-001749) ──────────────────
def _assert_process_owned(process_model: str) -> None:
	"""Guard: the current user must own the process behind ``process_model``
	(or be System Manager). Mirrors the WI-001744 scoping chain."""
	from one_bpmn.agents.eval_permissions import _is_system_manager, _process_model_owned_by

	user = frappe.session.user
	if _is_system_manager(user):
		return
	if not _process_model_owned_by(process_model, user):
		frappe.throw(
			_("You can only create suites for processes you own."),
			frappe.PermissionError,
		)


@frappe.whitelist()
def list_assignable_agents(include_all: int = 0) -> list:
	"""Agent configurations for the assign/reassign pickers.

	``include_all`` decides the scope, and it DEFAULTS TO OFF so this keeps
	returning exactly what it always returned — Live and enabled only. Widening
	the default would have changed what every existing caller sees without any
	of them asking, and callers outside this file cannot be assumed to want it.
	The eval screens opt in explicitly.

	With it on, every configuration is returned. The old filter rested on "a
	Draft agent cannot be evaluated", which confuses cause and effect:
	evaluating an agent is how it stops being a Draft. An adversarial suite is
	most useful pointed at something NOT yet Live, and an agent in Needs
	Attention is precisely the one somebody wants to test.

	Lifecycle and enabled travel with every row either way — additive, so a
	caller that ignores them is unaffected, and one that wants to label what it
	is offering has what it needs. Filtering silently would be this function
	deciding for the user with less information than the user has.
	"""
	filters = {} if cint(include_all) else {"lifecycle_status": "Live", "enabled": 1}
	return frappe.get_all(
		"AI Agent Configuration",
		filters=filters,
		fields=[
			"name", "agent_name", "agent_framework", "process_model",
			"lifecycle_status", "enabled",
		],
		order_by="agent_name asc",
		limit_page_length=0,
	)


@frappe.whitelist()
def list_owned_processes() -> list:
	"""BPMN Process Models the current user may attach a suite to — those
	whose process they own; System Manager sees all (WI-001749 / Q5)."""
	user = frappe.session.user
	is_sm = "System Manager" in frappe.get_roles(user)

	owners = {
		p["name"]: p["process_owner"]
		for p in frappe.get_all("Process", fields=["name", "process_owner"])
	}
	models = frappe.get_all(
		"BPMN Process Model",
		fields=["name", "process_name"],
		order_by="name asc",
		limit_page_length=0,
	)
	return [
		m for m in models
		if is_sm or owners.get(m["process_name"]) == user
	]


@frappe.whitelist()
def reassign_suite(suite: str, agent_configuration: str = None) -> str:
	"""(Re)assign a suite to an agent — or clear it when agent is empty.
	The user must be able to write the suite (owner / SM)."""
	doc = frappe.get_doc("AI Eval Suite", suite)
	doc.check_permission("write")

	if agent_configuration and not frappe.db.exists("AI Agent Configuration", agent_configuration):
		frappe.throw(_("AI Agent Configuration '{0}' not found.").format(agent_configuration))

	# Update only the agent link. Using db_set avoids re-validating the suite's
	# other links (e.g. a stale process_model) that would otherwise block a
	# reassignment for reasons unrelated to it.
	doc.db_set("agent_configuration", agent_configuration or None)
	return doc.name


@frappe.whitelist()
def create_suite(
	title: str,
	process_model: str = None,
	agent_configuration: str = None,
	eval_type: str = "Direct",
	description: str = "",
) -> str:
	"""Create a new suite from the Evals page and assign it to an agent.
	``process_model`` is optional (Direct suites may have none); when set it must
	be one the current user owns (or SM) — WI-001749 / Q5. ``eval_type`` is Direct
	(simple LLM call) or Agent (invoke the map). ``description`` records what the
	suite covers, so a later reader — the Evals console or the AI Assistant
	deciding whether an existing suite already fits — can tell suites apart."""
	if process_model:
		_assert_process_owned(process_model)

	if agent_configuration and not frappe.db.exists("AI Agent Configuration", agent_configuration):
		frappe.throw(_("AI Agent Configuration '{0}' not found.").format(agent_configuration))

	doc = frappe.get_doc({
		"doctype": "AI Eval Suite",
		"title": title,
		"process_model": process_model or None,
		"agent_configuration": agent_configuration or None,
		"eval_type": eval_type if eval_type in ("Direct", "Agent") else "Direct",
		"description": description or None,
	})
	doc.insert()
	return doc.name


# ── A/B comparison of two runs (WI-001821) ────────────────────────────────────
# A comparison is INFORMATIONAL. It deliberately has nothing to do with
# AI Eval Suite.gate_deployment: the gate decides whether a suite blocks a
# deploy, while this only helps a designer choose between two agents. Wiring
# the two together would let a losing variant block a release nobody asked it to.

# Below this many shared cases the numbers are anecdote, not evidence. The site
# runs eight cases per adversarial suite, so this fires often — which is the
# point: a two-case difference on eight cases is one case changing its mind.
SMALL_SAMPLE_CASES = 10


def _run_agent_totals(run_agents: dict) -> dict:
	"""Per-run latency and the four-way cost split, aggregated from the
	AI Agent Runs each eval run produced (WI-001643 fields).

	``run_agents`` maps eval-run name -> the agent that run tested.

	Read from AI Agent Run rather than AI Eval Result because the result row
	stores only a single rolled-up cost — the cache-read/write split and the
	latency live on the agent run. A Direct eval records a lightweight agent run
	too, so both eval types are covered.

	An eval run also produces agent runs for its llm_judge calls, and those are
	NOT the agent under test: the judge is the examiner. Counting its round-trips
	in "mean agent latency" measures the wrong model entirely, and counting its
	spend in the agent's cost split makes a cheap agent look expensive because it
	was marked by an expensive judge. Judge rows are separated out and reported
	as their own figure, so the parts still reconcile with the suite total.
	"""
	if not run_agents:
		return {}
	rows = frappe.get_all(
		"AI Agent Run",
		filters={"eval_run": ["in", list(run_agents)]},
		fields=[
			"eval_run", "agent_configuration", "agent_latency_ms",
			"total_input_cost", "total_output_cost",
			"total_cache_read_cost", "total_cache_write_cost", "estimated_cost",
			"total_cache_read_tokens", "total_cache_write_tokens", "total_tokens",
		],
		limit_page_length=0,
	)
	out = {}
	for r in rows:
		acc = out.setdefault(r["eval_run"], {
			"agent_run_count": 0, "latencies": [],
			"input_cost": 0.0, "output_cost": 0.0,
			"cache_read_cost": 0.0, "cache_write_cost": 0.0, "estimated_cost": 0.0,
			"cache_read_tokens": 0, "cache_write_tokens": 0, "tokens": 0,
			"judge_cost": 0.0, "judge_call_count": 0,
		})
		# Judge calls carry no agent_configuration. When the eval run itself
		# predates agent tracking, "has an agent at all" is the best available
		# discriminator and still separates the judge correctly.
		expected = run_agents.get(r["eval_run"])
		is_agent_call = (
			r["agent_configuration"] == expected if expected else bool(r["agent_configuration"])
		)
		if not is_agent_call:
			acc["judge_cost"] += flt(r["estimated_cost"])
			acc["judge_call_count"] += 1
			continue
		acc["agent_run_count"] += 1
		# 0 means "not measured" on older runs, not "instant" — averaging those
		# in would quietly drag the mean towards zero.
		if r["agent_latency_ms"]:
			acc["latencies"].append(r["agent_latency_ms"])
		acc["input_cost"] += flt(r["total_input_cost"])
		acc["output_cost"] += flt(r["total_output_cost"])
		acc["cache_read_cost"] += flt(r["total_cache_read_cost"])
		acc["cache_write_cost"] += flt(r["total_cache_write_cost"])
		acc["estimated_cost"] += flt(r["estimated_cost"])
		acc["cache_read_tokens"] += (r["total_cache_read_tokens"] or 0)
		acc["cache_write_tokens"] += (r["total_cache_write_tokens"] or 0)
		acc["tokens"] += (r["total_tokens"] or 0)
	for acc in out.values():
		lat = acc.pop("latencies")
		acc["mean_latency_ms"] = round(sum(lat) / len(lat)) if lat else None
		acc["latency_samples"] = len(lat)
	return out


def _case_kinds(cases: list) -> dict:
	"""case name -> Attack / Benign Control / None, for the cases being compared."""
	if not cases:
		return {}
	rows = frappe.get_all(
		"AI Eval Case",
		filters={"name": ("in", list(cases))},
		fields=["name", "case_kind"],
		limit_page_length=0,
	)
	return {r["name"]: r.get("case_kind") for r in rows}


def _security_rates(statuses: dict, shared: list, kinds: dict) -> dict:
	"""Attack success rate and false-positive rate.

	Both, always, because either alone is misleading in the same direction. An
	agent that refuses every message has a perfect attack-success rate and is
	useless; an agent that answers everything has no false positives and no
	protection. The pair is the measurement — the story is explicit that it is
	not accepted without both numbers.

	* Attack success rate — of the Attack cases, the share the agent FAILED.
	  A failed attack case means the agent complied, so the attack got through.
	* False-positive rate — of the Benign Control cases, the share the agent
	  FAILED. A failed control means ordinary traffic was refused.

	Errored cases are excluded from both denominators rather than counted as
	either. An eval that crashed is not evidence the attack worked, and it is
	not evidence the agent was rude to a real user.

	Unlabelled cases are excluded too, and the denominators are returned
	alongside so a rate computed over three cases cannot be read as though it
	were computed over three hundred.
	"""
	def rate(kind):
		scored = [c for c in shared if kinds.get(c) == kind and statuses.get(c) in ("Passed", "Failed")]
		if not scored:
			return None, 0
		failed = sum(1 for c in scored if statuses.get(c) == "Failed")
		return round(failed / len(scored) * 100, 1), len(scored)

	asr, attacks = rate("Attack")
	fpr, controls = rate("Benign Control")
	return {
		"attack_success_rate": asr,
		"attack_cases": attacks,
		"false_positive_rate": fpr,
		"benign_cases": controls,
		# Says plainly when the suite cannot answer the question, rather than
		# reporting a confident-looking null.
		"measurable": bool(attacks and controls),
	}


def _side(doc, totals: dict, statuses: dict, shared: list, kinds: dict | None = None) -> dict:
	"""One column of the comparison.

	Pass rate is computed over the SHARED cases only, not over the run's own
	totals — otherwise a run that happened to cover an extra case would be
	compared on a different denominator to the one beside it.
	"""
	agent = doc.get("agent_configuration")
	passed = sum(1 for c in shared if statuses.get(c) == "Passed")
	errored = sum(1 for c in shared if statuses.get(c) == "Error")
	t = totals.get(doc.name) or {}
	return {
		"run": doc.name,
		"agent": agent,
		"agent_name": frappe.db.get_value("AI Agent Configuration", agent, "agent_name") if agent else None,
		"status": doc.status,
		"backend": doc.backend,
		"started_at": doc.started_at,
		"ended_at": doc.ended_at,
		"cases_compared": len(shared),
		"passed": passed,
		"failed": len(shared) - passed - errored,
		"errored": errored,
		"pass_rate": round(passed / len(shared) * 100, 1) if shared else None,
		**_security_rates(statuses, shared, kinds or {}),
		"mean_latency_ms": t.get("mean_latency_ms"),
		"latency_samples": t.get("latency_samples", 0),
		# Suite cost is the eval-result total (it includes judge calls, which
		# are not the agent's own spend); the split beneath it is the agent's.
		"total_cost": flt(doc.total_cost),
		"total_tokens": doc.total_tokens,
		"cost_split": {
			"input": t.get("input_cost", 0.0),
			"output": t.get("output_cost", 0.0),
			"cache_read": t.get("cache_read_cost", 0.0),
			"cache_write": t.get("cache_write_cost", 0.0),
			"agent_total": t.get("estimated_cost", 0.0),
		},
		"cache_tokens": {
			"read": t.get("cache_read_tokens", 0),
			"write": t.get("cache_write_tokens", 0),
		},
		# Marking cost, not the agent's. Shown separately so the agent split plus
		# this reconciles with the suite total rather than silently disagreeing.
		"judge_cost": t.get("judge_cost", 0.0),
		"agent_calls": t.get("agent_run_count", 0),
	}


def _comparability(a, b, cases_a: set, cases_b: set, shared: list) -> list:
	"""Everything that makes this comparison less than apples-to-apples.

	Returned as a list of {level, message} rather than raised, because most of
	these are worth SEEING alongside the numbers — a designer who knows one run
	errored partway can still read the cases that did complete. Only the
	genuinely meaningless comparisons are refused, by the caller.

	Levels, in the order they demand attention:

	* ``pending``  — nothing to show YET, and nothing for the user to do. It
	  resolves on its own. Kept distinct from ``blocking`` because presenting a
	  run that is merely still going as "can't compare" reads as a failure the
	  user has to act on, when the correct response is to wait.
	* ``blocking`` — the comparison cannot be produced and will not fix itself.
	* ``warning``  — produced, but not like for like.
	* ``caution``  — produced and sound, but read it carefully.
	"""
	notes = []

	def note(level, message):
		notes.append({"level": level, "message": message})

	still_running = any(doc.status == "Running" for doc in (a, b))
	for doc in (a, b):
		if doc.status == "Running":
			# A run writes its results in one go when it finishes, so a run in
			# flight has nothing readable at all — not partial numbers.
			note("pending", _(
				"Run {0} is still working through its cases. Results are written when a run "
				"finishes, so there is nothing to show for it yet."
			).format(doc.name))
		elif doc.status == "Error":
			note("warning", _(
				"Run {0} errored partway through, so it covers fewer cases than it set out to. "
				"Only the cases both runs completed are compared."
			).format(doc.name))

	only_a = sorted(cases_a - cases_b)
	only_b = sorted(cases_b - cases_a)
	if only_a or only_b:
		note("warning", _(
			"The two runs did not cover the same cases: {0} ran only in the first, {1} only in the "
			"second. Those are excluded and the {2} shared cases are compared."
		).format(len(only_a), len(only_b), len(shared)))

	if a.get("agent_configuration") and a.get("agent_configuration") == b.get("agent_configuration"):
		note("warning", _(
			"Both runs tested the same agent ({0}), so any difference is run-to-run variance "
			"rather than a difference between agents."
		).format(a.get("agent_configuration")))
	if not a.get("agent_configuration") or not b.get("agent_configuration"):
		note("warning", _(
			"At least one run does not record which agent it tested — it predates run-level agent "
			"tracking. It used whatever the suite pointed at when it ran, which may have changed since."
		))

	if a.backend != b.backend:
		note("warning", _(
			"One run is '{0}' and the other '{1}'. A replay re-scores stored answers without "
			"calling the agent, so its latency and cost are not the agent's."
		).format(a.backend, b.backend))

	if shared and len(shared) < SMALL_SAMPLE_CASES:
		note("caution", _(
			"Only {0} cases were compared. That is a small sample — a one-case difference is "
			"{1:.0f} percentage points, so treat a narrow gap as noise."
		).format(len(shared), 100.0 / len(shared)))

	# Only meaningful once both runs have finished. A run still executing has no
	# result rows yet, so "shared" is trivially empty — reporting that as its own
	# blocking reason reads as "these two runs have nothing in common" when the
	# truth is "neither has produced anything yet", which the running note above
	# already says. An ERRORED run with no results is a real instance of this and
	# still reports it.
	if not shared and not still_running:
		note("blocking", _("The two runs share no cases, so there is nothing to compare."))

	return notes


@frappe.whitelist()
def get_run_comparison(run_a: str, run_b: str = None) -> dict:
	"""Two runs of one suite, side by side (WI-001821).

	``run_b`` may be omitted for a run created by ``run_eval_comparison`` — the
	other side is found through the shared ``comparison_group``.

	Per agent: pass rate, mean agent latency, cost with the cache-read/write
	split visible. Per case: win / loss / tie. Plus ``notes`` saying plainly
	where the comparison is weak, and ``blocked`` when it cannot be made at all.
	"""
	a = frappe.get_doc("AI Eval Run", run_a)
	a.check_permission("read")

	if not run_b:
		if not a.get("comparison_group"):
			frappe.throw(_(
				"Run {0} is not part of an A/B pair, so there is no other side to show. "
				"Pick a run to compare it against."
			).format(run_a))
		peer = frappe.get_all(
			"AI Eval Run",
			filters={"comparison_group": a.comparison_group, "name": ["!=", a.name]},
			pluck="name",
			limit_page_length=1,
		)
		if not peer:
			frappe.throw(_("The other half of this comparison no longer exists."))
		run_b = peer[0]

	b = frappe.get_doc("AI Eval Run", run_b)
	b.check_permission("read")

	# Same suite is the one hard requirement: different suites mean different
	# cases and different assertions, and no amount of flagging rescues that.
	if a.suite != b.suite:
		frappe.throw(_(
			"These runs are of different suites ({0} and {1}). Only runs of the same suite "
			"can be compared — the cases and assertions differ otherwise."
		).format(a.suite, b.suite))

	statuses_a = {r.eval_case: r.status for r in a.results if r.eval_case}
	statuses_b = {r.eval_case: r.status for r in b.results if r.eval_case}
	cases_a, cases_b = set(statuses_a), set(statuses_b)

	suite_title = frappe.db.get_value("AI Eval Suite", a.suite, "title")
	case_titles = {
		c["name"]: c["title"]
		for c in frappe.get_all(
			"AI Eval Case",
			filters={"name": ["in", list(cases_a | cases_b)]} if (cases_a | cases_b) else {"name": ""},
			fields=["name", "title"],
		)
	}
	# Suite order, so the table reads the same way as the suite page.
	order = frappe.get_all(
		"AI Eval Case", filters={"suite": a.suite}, pluck="name", order_by="creation asc"
	)
	shared = [c for c in order if c in cases_a and c in cases_b]
	# A case moved out of the suite still belongs in the comparison.
	shared += sorted((cases_a & cases_b) - set(order))

	notes = _comparability(a, b, cases_a, cases_b, shared)
	# Both levels hide the figures; only one of them is the user's problem.
	pending = [n for n in notes if n["level"] == "pending"]
	blocked = [n for n in notes if n["level"] == "blocking"]

	totals = _run_agent_totals({
		a.name: a.get("agent_configuration"),
		b.name: b.get("agent_configuration"),
	})
	cases = []
	for c in shared:
		sa, sb = statuses_a[c], statuses_b[c]
		if sa == sb:
			outcome = "tie"
		elif sa == "Passed":
			outcome = "a"
		elif sb == "Passed":
			outcome = "b"
		else:
			# Neither passed but they differ (Failed vs Error) — not a win for
			# either side, and calling it one would overstate the loser.
			outcome = "tie"
		cases.append({
			"eval_case": c,
			"case_title": case_titles.get(c) or c,
			"status_a": sa,
			"status_b": sb,
			"outcome": outcome,
		})

	kinds = _case_kinds(shared)

	return {
		"suite": a.suite,
		"suite_title": suite_title,
		"comparison_group": a.get("comparison_group") or None,
		# Read once and handed to both sides — the same case is the same kind in
		# either run, and looking it up twice would only invite them to disagree.
		"a": _side(a, totals, statuses_a, shared, kinds),
		"b": _side(b, totals, statuses_b, shared, kinds),
		"cases": cases,
		"tally": {
			"a_wins": sum(1 for c in cases if c["outcome"] == "a"),
			"b_wins": sum(1 for c in cases if c["outcome"] == "b"),
			"ties": sum(1 for c in cases if c["outcome"] == "tie"),
		},
		"only_in_a": sorted(cases_a - cases_b),
		"only_in_b": sorted(cases_b - cases_a),
		"notes": notes,
		# blocked = no figures to show. pending = ...and that is temporary.
		"blocked": bool(blocked or pending),
		"pending": bool(pending),
	}


@frappe.whitelist()
def list_comparable_runs(run: str) -> list:
	"""Finished runs of the same suite that ``run`` could be compared against,
	newest first. Errored runs are included — they are flagged, not hidden,
	because the cases they did finish are still worth reading."""
	doc = frappe.get_doc("AI Eval Run", run)
	doc.check_permission("read")

	suite_title = frappe.db.get_value("AI Eval Suite", doc.suite, "title")
	history = frappe.get_all(
		"AI Eval Run",
		filters={"suite": doc.suite, "status": ["in", ["Passed", "Failed", "Error"]]},
		fields=["name", "started_at", "status", "agent_configuration", "creation"],
		order_by="creation asc",
		limit_page_length=0,
	)
	out = []
	for i, r in enumerate(history):
		if r["name"] == doc.name:
			continue
		out.append({
			"name": r["name"],
			"display_title": _run_title(suite_title, i + 1, r["started_at"]),
			"status": r["status"],
			"agent": r["agent_configuration"],
			"started_at": r["started_at"],
			# The interesting comparison is against a DIFFERENT agent; same-agent
			# runs stay selectable but the UI can de-emphasise them.
			"same_agent": bool(
				r["agent_configuration"]
				and r["agent_configuration"] == doc.get("agent_configuration")
			),
		})
	return list(reversed(out))


# ── Response feedback (WI-002068) ────────────────────────────────────────────
#
# The triage queue: what users disliked, and the one action that matters — turn
# a reviewed complaint into a regression test. Read endpoints live here beside
# the other Evals reads; the write path is
# one_bpmn.api.feedback.create_eval_case_from_feedback, reused rather than
# reimplemented, because that is what resolves the agent's "— Regressions" suite
# and keeps cases out of the provisioned Baseline suite (which is wiped on every
# re-provision).

_FEEDBACK_FIELDS = [
	"name",
	"rating",
	"status",
	"comment",
	"rated_by",
	"rated_on",
	"message",
	"conversation",
	"agent_run",
	"agent_configuration",
	"eval_case",
]


def _agent_labels(configs: list) -> dict:
	if not configs:
		return {}
	rows = frappe.get_all(
		"AI Agent Configuration",
		filters={"name": ["in", list({c for c in configs if c})]},
		fields=["name", "agent_name", "chat_mode_label"],
	)
	return {r["name"]: (r["chat_mode_label"] or r["agent_name"] or r["name"]) for r in rows}


def _prompt_for_each_reply(replies: dict) -> dict:
	"""The user message that prompted each rated reply.

	A reply cannot be judged on its own — "that answer was wrong" means nothing
	without the question. Resolved in two bulk queries rather than one per row:
	every User message in the conversations involved, then the latest one before
	each reply.
	"""
	if not replies:
		return {}
	conversations = list({r["conversation"] for r in replies.values() if r.get("conversation")})
	if not conversations:
		return {}

	asked = frappe.get_all(
		"Chat Message",
		filters={"conversation": ["in", conversations], "message_type": "User"},
		fields=["conversation", "text", "creation"],
		order_by="creation asc",
		limit_page_length=0,
	)
	by_conversation: dict[str, list] = {}
	for row in asked:
		by_conversation.setdefault(row["conversation"], []).append(row)

	out = {}
	for message, reply in replies.items():
		candidates = by_conversation.get(reply.get("conversation"), [])
		previous = [c for c in candidates if c["creation"] <= reply["creation"]]
		out[message] = (previous[-1]["text"] if previous else "") or ""
	return out


@frappe.whitelist()
def list_response_feedback(
	rating: str = "Negative",
	status: str = "New",
	agent: str = None,
	from_date: str = None,
	to_date: str = None,
	limit: int = 100,
) -> list:
	"""Feedback rows with enough context to judge them, newest first.

	Defaults to the triage queue — negative and unreviewed — because that is the
	only list anyone needs to act on. Pass "All" for rating or status to widen it.

	Permission scoping is the AI Response Feedback doctype's own: get_list here
	means a user sees exactly the rows their roles allow, with no second
	permission model to keep in step. The Chat Message text is then read with
	get_all for rows already authorised above — a join, not a widening.
	"""
	from frappe.utils import cint

	filters = {}
	if rating and rating != "All":
		filters["rating"] = rating
	if status and status != "All":
		filters["status"] = status
	if agent:
		filters["agent_configuration"] = agent
	if from_date:
		filters["rated_on"] = [">=", from_date]
	if to_date:
		filters["rated_on"] = (
			["between", [from_date, to_date]] if from_date else ["<=", to_date]
		)

	rows = frappe.get_list(
		"AI Response Feedback",
		filters=filters,
		fields=_FEEDBACK_FIELDS,
		order_by="rated_on desc",
		limit_page_length=min(cint(limit) or 100, 500),
	)
	if not rows:
		return []

	names = [r["name"] for r in rows]
	message_ids = [r["message"] for r in rows if r.get("message")]

	replies = {
		m["name"]: m
		for m in frappe.get_all(
			"Chat Message",
			filters={"name": ["in", message_ids]},
			fields=["name", "text", "conversation", "creation"],
			limit_page_length=0,
		)
	} if message_ids else {}
	prompts = _prompt_for_each_reply(replies)

	reasons: dict[str, list] = {}
	for row in frappe.get_all(
		"AI Response Feedback Reason",
		filters={"parent": ["in", names]},
		fields=["parent", "reason"],
		limit_page_length=0,
	):
		reasons.setdefault(row["parent"], []).append(row["reason"])

	labels = _agent_labels([r.get("agent_configuration") for r in rows])

	# The suite each existing case belongs to, so "Open eval case" can go to it
	# inside Processa rather than out to the desk.
	case_suites = {}
	case_names = [r["eval_case"] for r in rows if r.get("eval_case")]
	if case_names:
		case_suites = {
			c["name"]: c["suite"]
			for c in frappe.get_all(
				"AI Eval Case", filters={"name": ["in", case_names]}, fields=["name", "suite"],
				limit_page_length=0,
			)
		}

	out = []
	for row in rows:
		reply = replies.get(row.get("message")) or {}
		# Why a row cannot become a case is answered HERE, so the page can say so
		# instead of offering a button that fails.
		blocked = None
		if row["rating"] != "Negative":
			blocked = _("Only negative feedback becomes a regression test.")
		elif not row.get("agent_run"):
			blocked = _("No agent run behind this reply — there is no prompt or context to build a case from.")
		elif not row.get("agent_configuration"):
			blocked = _("No agent configuration on this feedback, so there is no suite to file it under.")

		out.append({
			**row,
			"agent_label": labels.get(row.get("agent_configuration")) or row.get("agent_configuration") or "",
			"reasons": reasons.get(row["name"], []),
			"reply_text": reply.get("text") or "",
			"prompt_text": prompts.get(row.get("message"), ""),
			"eval_suite": case_suites.get(row.get("eval_case")) or "",
			"can_convert": blocked is None and not row.get("eval_case"),
			"blocked_reason": blocked,
		})
	return out


@frappe.whitelist()
def get_feedback_overview(from_date: str = None, to_date: str = None, agent: str = None) -> dict:
	"""Counts for the cards above the queue.

	Counts WITH their denominator, never a satisfaction percentage. Fewer than 1%
	of replies are rated and the people who rate cluster at the extremes, so an
	average would be confidently wrong — and, sitting beside real cost figures,
	would be trusted exactly as much as they are.
	"""
	filters = {}
	if agent:
		filters["agent_configuration"] = agent
	if from_date and to_date:
		filters["rated_on"] = ["between", [from_date, to_date]]
	elif from_date:
		filters["rated_on"] = [">=", from_date]
	elif to_date:
		filters["rated_on"] = ["<=", to_date]

	rated = frappe.get_list(
		"AI Response Feedback",
		filters=filters,
		fields=["rating", "status"],
		limit_page_length=0,
	)

	# The denominator: agent replies in the same window. Scoped to the agent's
	# conversations when one is selected, so the ratio compares like with like.
	reply_filters = {"message_type": "Bot"}
	if from_date and to_date:
		reply_filters["creation"] = ["between", [from_date, to_date]]
	elif from_date:
		reply_filters["creation"] = [">=", from_date]
	elif to_date:
		reply_filters["creation"] = ["<=", to_date]
	if agent:
		label = frappe.db.get_value("AI Agent Configuration", agent, "chat_mode_label")
		conversations = frappe.get_all(
			"Chat Conversation", filters={"agent_mode": label}, pluck="name", limit_page_length=0
		) if label else []
		reply_filters["conversation"] = ["in", conversations or [""]]
	total_replies = frappe.db.count("Chat Message", reply_filters)

	negative = [r for r in rated if r["rating"] == "Negative"]
	return {
		"total_replies": total_replies,
		"total_rated": len(rated),
		"positive": len(rated) - len(negative),
		"negative": len(negative),
		"awaiting_review": len([r for r in negative if r["status"] == "New"]),
		"reviewed": len([r for r in negative if r["status"] == "Reviewed"]),
		"converted": len([r for r in rated if r["status"] == "Converted"]),
		"dismissed": len([r for r in rated if r["status"] == "Dismissed"]),
	}
