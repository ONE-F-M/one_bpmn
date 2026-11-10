"""Run-to-run comparison for the Evals console."""

import frappe
from frappe import _
from frappe.utils import flt

from one_bpmn.ai_agent_evals.suites import run_title

# Below this many shared cases the numbers are anecdote, not evidence. The site
# runs eight cases per adversarial suite, so this fires often - which is the
# point: a two-case difference on eight cases is one case changing its mind.
SMALL_SAMPLE_CASES = 10


def _run_agent_totals(run_agents: dict) -> dict:
	"""Per-run latency and the four-way cost split, aggregated from the
	AI Agent Runs each eval run produced (fields).

	``run_agents`` maps eval-run name -> the agent that run tested.

	Read from AI Agent Run rather than AI Eval Result because the result row
	stores only a single rolled-up cost - the cache-read/write split and the
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
			"eval_run",
			"agent_configuration",
			"agent_latency_ms",
			"total_input_cost",
			"total_output_cost",
			"total_cache_read_cost",
			"total_cache_write_cost",
			"estimated_cost",
			"total_cache_read_tokens",
			"total_cache_write_tokens",
			"total_tokens",
		],
		limit_page_length=0,
	)
	out = {}
	for r in rows:
		acc = out.setdefault(
			r["eval_run"],
			{
				"agent_run_count": 0,
				"latencies": [],
				"input_cost": 0.0,
				"output_cost": 0.0,
				"cache_read_cost": 0.0,
				"cache_write_cost": 0.0,
				"estimated_cost": 0.0,
				"cache_read_tokens": 0,
				"cache_write_tokens": 0,
				"tokens": 0,
				"judge_cost": 0.0,
				"judge_call_count": 0,
			},
		)
		# Judge calls carry no agent_configuration. When the eval run itself
		# predates agent tracking, "has an agent at all" is the best available
		# discriminator and still separates the judge correctly.
		expected = run_agents.get(r["eval_run"])
		is_agent_call = r["agent_configuration"] == expected if expected else bool(r["agent_configuration"])
		if not is_agent_call:
			acc["judge_cost"] += flt(r["estimated_cost"])
			acc["judge_call_count"] += 1
			continue
		acc["agent_run_count"] += 1
		# 0 means "not measured" on older runs, not "instant" - averaging those
		# in would quietly drag the mean towards zero.
		if r["agent_latency_ms"]:
			acc["latencies"].append(r["agent_latency_ms"])
		acc["input_cost"] += flt(r["total_input_cost"])
		acc["output_cost"] += flt(r["total_output_cost"])
		acc["cache_read_cost"] += flt(r["total_cache_read_cost"])
		acc["cache_write_cost"] += flt(r["total_cache_write_cost"])
		acc["estimated_cost"] += flt(r["estimated_cost"])
		acc["cache_read_tokens"] += r["total_cache_read_tokens"] or 0
		acc["cache_write_tokens"] += r["total_cache_write_tokens"] or 0
		acc["tokens"] += r["total_tokens"] or 0
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
	protection. The pair is the measurement - the story is explicit that it is
	not accepted without both numbers.

	* Attack success rate - of the Attack cases, the share the agent FAILED.
	  A failed attack case means the agent complied, so the attack got through.
	* False-positive rate - of the Benign Control cases, the share the agent
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
	totals - otherwise a run that happened to cover an extra case would be
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
	these are worth SEEING alongside the numbers - a designer who knows one run
	errored partway can still read the cases that did complete. Only the
	genuinely meaningless comparisons are refused, by the caller.

	Levels, in the order they demand attention:

	* ``pending``  - nothing to show YET, and nothing for the user to do. It
	  resolves on its own. Kept distinct from ``blocking`` because presenting a
	  run that is merely still going as "can't compare" reads as a failure the
	  user has to act on, when the correct response is to wait.
	* ``blocking`` - the comparison cannot be produced and will not fix itself.
	* ``warning``  - produced, but not like for like.
	* ``caution``  - produced and sound, but read it carefully.
	"""
	notes = []

	def note(level, message):
		notes.append({"level": level, "message": message})

	still_running = any(doc.status == "Running" for doc in (a, b))
	for doc in (a, b):
		if doc.status == "Running":
			# A run writes its results in one go when it finishes, so a run in
			# flight has nothing readable at all - not partial numbers.
			note(
				"pending",
				_(
					"Run {0} is still working through its cases. Results are written when a run "
					"finishes, so there is nothing to show for it yet."
				).format(doc.name),
			)
		elif doc.status == "Error":
			note(
				"warning",
				_(
					"Run {0} errored partway through, so it covers fewer cases than it set out to. "
					"Only the cases both runs completed are compared."
				).format(doc.name),
			)

	only_a = sorted(cases_a - cases_b)
	only_b = sorted(cases_b - cases_a)
	if only_a or only_b:
		note(
			"warning",
			_(
				"The two runs did not cover the same cases: {0} ran only in the first, {1} only in the "
				"second. Those are excluded and the {2} shared cases are compared."
			).format(len(only_a), len(only_b), len(shared)),
		)

	if a.get("agent_configuration") and a.get("agent_configuration") == b.get("agent_configuration"):
		note(
			"warning",
			_(
				"Both runs tested the same agent ({0}), so any difference is run-to-run variance "
				"rather than a difference between agents."
			).format(a.get("agent_configuration")),
		)
	if not a.get("agent_configuration") or not b.get("agent_configuration"):
		note(
			"warning",
			_(
				"At least one run does not record which agent it tested - it predates run-level agent "
				"tracking. It used whatever the suite pointed at when it ran, which may have changed since."
			),
		)

	if a.backend != b.backend:
		note(
			"warning",
			_(
				"One run is '{0}' and the other '{1}'. A replay re-scores stored answers without "
				"calling the agent, so its latency and cost are not the agent's."
			).format(a.backend, b.backend),
		)

	if shared and len(shared) < SMALL_SAMPLE_CASES:
		note(
			"caution",
			_(
				"Only {0} cases were compared. That is a small sample - a one-case difference is "
				"{1:.0f} percentage points, so treat a narrow gap as noise."
			).format(len(shared), 100.0 / len(shared)),
		)

	# Only meaningful once both runs have finished. A run still executing has no
	# result rows yet, so "shared" is trivially empty - reporting that as its own
	# blocking reason reads as "these two runs have nothing in common" when the
	# truth is "neither has produced anything yet", which the running note above
	# already says. An ERRORED run with no results is a real instance of this and
	# still reports it.
	if not shared and not still_running:
		note("blocking", _("The two runs share no cases, so there is nothing to compare."))

	return notes


def get_run_comparison(run_a: str, run_b: str = None) -> dict:
	"""Two runs of one suite, side by side.

	``run_b`` may be omitted for a run created by ``run_eval_comparison`` - the
	other side is found through the shared ``comparison_group``.

	Per agent: pass rate, mean agent latency, cost with the cache-read/write
	split visible. Per case: win / loss / tie. Plus ``notes`` saying plainly
	where the comparison is weak, and ``blocked`` when it cannot be made at all.
	"""
	a = frappe.get_doc("AI Eval Run", run_a)
	a.check_permission("read")

	if not run_b:
		if not a.get("comparison_group"):
			frappe.throw(
				_(
					"Run {0} is not part of an A/B pair, so there is no other side to show. "
					"Pick a run to compare it against."
				).format(run_a)
			)
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
		frappe.throw(
			_(
				"These runs are of different suites ({0} and {1}). Only runs of the same suite "
				"can be compared - the cases and assertions differ otherwise."
			).format(a.suite, b.suite)
		)

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
	order = frappe.get_all("AI Eval Case", filters={"suite": a.suite}, pluck="name", order_by="creation asc")
	shared = [c for c in order if c in cases_a and c in cases_b]
	# A case moved out of the suite still belongs in the comparison.
	shared += sorted((cases_a & cases_b) - set(order))

	notes = _comparability(a, b, cases_a, cases_b, shared)
	# Both levels hide the figures; only one of them is the user's problem.
	pending = [n for n in notes if n["level"] == "pending"]
	blocked = [n for n in notes if n["level"] == "blocking"]

	totals = _run_agent_totals(
		{
			a.name: a.get("agent_configuration"),
			b.name: b.get("agent_configuration"),
		}
	)
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
			# Neither passed but they differ (Failed vs Error) - not a win for
			# either side, and calling it one would overstate the loser.
			outcome = "tie"
		cases.append(
			{
				"eval_case": c,
				"case_title": case_titles.get(c) or c,
				"status_a": sa,
				"status_b": sb,
				"outcome": outcome,
			}
		)

	kinds = _case_kinds(shared)

	return {
		"suite": a.suite,
		"suite_title": suite_title,
		"comparison_group": a.get("comparison_group") or None,
		# Read once and handed to both sides - the same case is the same kind in
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


def list_comparable_runs(run: str) -> list:
	"""Finished runs of the same suite that ``run`` could be compared against,
	newest first. Errored runs are included - they are flagged, not hidden,
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
		out.append(
			{
				"name": r["name"],
				"display_title": run_title(suite_title, i + 1, r["started_at"]),
				"status": r["status"],
				"agent": r["agent_configuration"],
				"started_at": r["started_at"],
				# The interesting comparison is against a DIFFERENT agent; same-agent
				# runs stay selectable but the UI can de-emphasise them.
				"same_agent": bool(
					r["agent_configuration"] and r["agent_configuration"] == doc.get("agent_configuration")
				),
			}
		)
	return list(reversed(out))
