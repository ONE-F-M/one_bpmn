"""Suite listing, detail, creation, assignment and thresholds for the Evals console."""

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime


def run_title(suite_title: str, seq: int, started_at) -> str:
	"""Human-readable title for an AI Eval Run (which has no title field):
	the suite title + the run's ordinal + its start time."""
	base = f"{suite_title or 'Suite'} - Run {seq}"
	if started_at:
		try:
			return f"{base} · {get_datetime(started_at).strftime('%Y-%m-%d %H:%M')}"
		except Exception:
			pass
	return base


def list_eval_suites() -> dict:
	"""Return the eval suites visible to the current user, each with a summary
	of its latest run, for the Evals console.
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
			names = []  # whole suite - the case list is implicit
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


def get_suite_detail(suite: str, start: int = 0, page_length: int = 25) -> dict:
	"""Suite header, its cases, and one page of its runs, newest first.

	Permission is enforced by check_permission (owner / SM).
	"""
	doc = frappe.get_doc("AI Eval Suite", suite)
	doc.check_permission("read")

	agent_name = None
	if doc.agent_configuration:
		agent_name = frappe.db.get_value("AI Agent Configuration", doc.agent_configuration, "agent_name")

	cases = frappe.get_all(
		"AI Eval Case",
		filters={"suite": suite},
		fields=["name", "title", "source_run"],
		order_by="creation asc",
	)
	# Assertion summary per case (one bulk query on the child table). Kept
	# defensive: a hiccup building the summary must never blank the whole
	# detail view - the cases and runs still return, just without chips.
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

	start = max(cint(start), 0)
	page_length = min(max(cint(page_length), 1), 100)
	run_fields = [
		"name",
		"status",
		"backend",
		"total_cases",
		"passed_cases",
		"failed_cases",
		"started_at",
		"ended_at",
		# How many executions the run actually made, and the rate the
		# deployment gate reads.
		"total_executions",
		"pass_rate",
		# Needed by the dashboard's latest-run tokens/cost tiles.
		"total_tokens",
		"total_cost",
		# Which cases the run covered (follow-up).
		"scope",
		"requested_cases",
	]
	runs = frappe.get_all(
		"AI Eval Run",
		filters={"suite": suite},
		fields=run_fields,
		order_by="creation desc",
		limit_start=start,
		limit_page_length=page_length,
	)
	_annotate_run_scope(runs, cases)
	# Number runs by their absolute order (newest first in the list), and give
	# each a readable title so the UI never shows the raw run id.
	total_runs = frappe.db.count("AI Eval Run", {"suite": suite})
	for idx, r in enumerate(runs):
		r["display_title"] = run_title(doc.title, total_runs - start - idx, r.get("started_at"))

	# The dashboard always reads the latest 20 runs, whatever page the list is on.
	recent = (
		runs
		if start == 0 and page_length >= 20
		else frappe.get_all(
			"AI Eval Run",
			filters={"suite": suite},
			fields=run_fields,
			order_by="creation desc",
			limit_page_length=20,
		)
	)

	# Dashboard metrics for the suite page.
	# Pass-rate sparkline: % of cases passing per run, oldest -> newest.
	spark = []
	for r in reversed(recent[:20]):
		tot = r.get("total_cases") or 0
		if tot:
			spark.append(round(100.0 * (r.get("passed_cases") or 0) / tot))
	spark = spark[-12:]
	latest = recent[0] if recent else None
	with_assertions = sum(1 for c in cases if c.get("assertion_types"))
	metrics = {
		"cases": len(cases),
		"runs": total_runs,
		"latest": {
			"status": latest["status"],
			"passed": latest.get("passed_cases") or 0,
			"total": latest.get("total_cases") or 0,
			"executions": cint(latest.get("total_executions")),
			"pass_rate": flt(latest.get("pass_rate")),
		}
		if latest
		else None,
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
			"gate_deployment": doc.gate_deployment,
			"pass_k": cint(doc.pass_k) or 1,
			"min_pass_rate": flt(doc.min_pass_rate),
			"ci_role": doc.ci_role or "",
		},
		"cases": cases,
		"runs": runs,
		"total_runs": total_runs,
		"start": start,
		"metrics": metrics,
	}


# ── Suite ↔ Agent management from the Evals page ──────────────────
def _assert_process_owned(process_model: str) -> None:
	"""Guard: the current user must own the process behind ``process_model``
	(or be System Manager). Mirrors the scoping chain."""
	from one_bpmn.ai_agent_evals.eval_permissions import is_system_manager, process_model_owned_by

	user = frappe.session.user
	if is_system_manager(user):
		return
	if not process_model_owned_by(process_model, user):
		frappe.throw(
			_("You can only create suites for processes you own."),
			frappe.PermissionError,
		)


def list_assignable_agents(include_all: int = 0) -> list:
	"""Agent configurations for the assign/reassign pickers.

	``include_all`` decides the scope, and it DEFAULTS TO OFF so this keeps
	returning exactly what it always returned - Live and enabled only. Widening
	the default would have changed what every existing caller sees without any
	of them asking, and callers outside this file cannot be assumed to want it.
	The eval screens opt in explicitly.

	With it on, every configuration is returned. The old filter rested on "a
	Draft agent cannot be evaluated", which confuses cause and effect:
	evaluating an agent is how it stops being a Draft. An adversarial suite is
	most useful pointed at something NOT yet Live, and an agent in Needs
	Attention is precisely the one somebody wants to test.

	Lifecycle and enabled travel with every row either way - additive, so a
	caller that ignores them is unaffected, and one that wants to label what it
	is offering has what it needs. Filtering silently would be this function
	deciding for the user with less information than the user has.
	"""
	filters = {} if cint(include_all) else {"lifecycle_status": "Live", "enabled": 1}
	return frappe.get_all(
		"AI Agent Configuration",
		filters=filters,
		fields=[
			"name",
			"agent_name",
			"agent_framework",
			"process_model",
			"lifecycle_status",
			"enabled",
		],
		order_by="agent_name asc",
		limit_page_length=0,
	)


def list_owned_processes() -> list:
	"""BPMN Process Models the current user may attach a suite to - those
	whose process they own; System Manager sees all."""
	user = frappe.session.user
	is_sm = "System Manager" in frappe.get_roles(user)

	owners = {
		p["name"]: p["process_owner"] for p in frappe.get_all("Process", fields=["name", "process_owner"])
	}
	models = frappe.get_all(
		"BPMN Process Model",
		fields=["name", "process_name"],
		order_by="name asc",
		limit_page_length=0,
	)
	return [m for m in models if is_sm or owners.get(m["process_name"]) == user]


def update_suite_thresholds(
	suite: str, pass_k=None, min_pass_rate=None, gate_deployment=None, ci_role=None
) -> dict:
	"""Set how a suite behaves when nobody is driving it: which automated job
	picks it up, how many times each case runs, the rate it must clear, and
	whether falling below that rate blocks the linked map from being activated.

	They belong together: a rate nothing enforces is a note to self, a gate with
	no rate only warns, and a suite no job picks up never produces either.
	Setting any of them anywhere else meant the switch lived in the desk while
	the bar lived here.
	"""
	doc = frappe.get_doc("AI Eval Suite", suite)
	doc.check_permission("write")

	if pass_k is not None:
		k = cint(pass_k)
		if k < 1:
			frappe.throw(_("Runs per case must be at least 1."))
		if k > 20:
			frappe.throw(_("Runs per case is capped at 20 - every run is a billed model call."))
		doc.pass_k = k
	if min_pass_rate is not None:
		rate = flt(min_pass_rate)
		if not 0 <= rate <= 100:
			frappe.throw(_("Minimum pass rate must be between 0 and 100."))
		doc.min_pass_rate = rate
	if gate_deployment is not None:
		doc.gate_deployment = cint(gate_deployment)
	if ci_role is not None:
		role = (ci_role or "").strip()
		if role not in ("", "Smoke", "Nightly"):
			frappe.throw(_("CI Role must be Smoke, Nightly, or blank."))
		doc.ci_role = role

	if doc.gate_deployment and not doc.process_model:
		frappe.throw(
			_(
				"This suite gates a deployment but names no process map, so there is nothing for it "
				"to block. Set the map on the suite first."
			)
		)

	doc.save()
	return {
		"pass_k": doc.pass_k,
		"min_pass_rate": doc.min_pass_rate,
		"gate_deployment": doc.gate_deployment,
		"ci_role": doc.ci_role or "",
	}


def reassign_suite(suite: str, agent_configuration: str = None) -> str:
	"""(Re)assign a suite to an agent - or clear it when agent is empty.
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


SUITE_TYPES = ("Direct", "Agent", "Memory")


def _valid_eval_type(value) -> str:
	"""A suite type, Direct when not given. An unknown one is refused, not
	quietly turned into Direct: a suite silently filed under the wrong type is
	worse than a save that fails, because every run it makes then measures
	something other than what its author asked for."""
	value = (value or "").strip() or "Direct"
	if value not in SUITE_TYPES:
		frappe.throw(
			_("'{0}' is not a suite type. Choose one of: {1}.").format(value, ", ".join(SUITE_TYPES))
		)
	return value


def create_suite(
	title: str,
	process_model: str = None,
	agent_configuration: str = None,
	eval_type: str = "Direct",
	description: str = "",
) -> str:
	"""Create a new suite from the Evals page and assign it to an agent.
	``process_model`` is optional (Direct suites may have none); when set it must
	be one the current user owns (or SM). ``eval_type`` is Direct
	(simple LLM call), Agent (invoke the map) or Memory (score the memory store
	against golden memories, no model call). ``description`` records what the
	suite covers, so a later reader - the Evals console or the AI Assistant
	deciding whether an existing suite already fits - can tell suites apart."""
	if process_model:
		_assert_process_owned(process_model)

	if agent_configuration and not frappe.db.exists("AI Agent Configuration", agent_configuration):
		frappe.throw(_("AI Agent Configuration '{0}' not found.").format(agent_configuration))

	doc = frappe.get_doc(
		{
			"doctype": "AI Eval Suite",
			"title": title,
			"process_model": process_model or None,
			"agent_configuration": agent_configuration or None,
			"eval_type": _valid_eval_type(eval_type),
			"description": description or None,
		}
	)
	doc.insert()
	return doc.name
