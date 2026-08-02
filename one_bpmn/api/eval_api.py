"""
Whitelisted endpoints backing the Processa Evals UI (WI-001681).

Every read goes through ``frappe.get_list`` so the AI Evals permission scoping
(WI-001744) applies automatically — a process owner sees only their own suites,
System Manager sees all.
"""

import frappe
from frappe import _
from frappe.utils import flt
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
		pt = (frappe.db.get_value("AI Provider Credentials", judge_provider, "provider_type") or "").lower()
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
def list_assignable_agents() -> list:
	"""Agent configurations offered in the assign/reassign picker: only Live,
	enabled agents, since a Draft or disabled agent cannot be evaluated."""
	return frappe.get_all(
		"AI Agent Configuration",
		filters={"lifecycle_status": "Live", "enabled": 1},
		fields=["name", "agent_name", "agent_framework", "process_model"],
		order_by="agent_name asc",
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
