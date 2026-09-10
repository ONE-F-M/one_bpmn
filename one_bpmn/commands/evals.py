# Copyright (c) 2026, one-fm and contributors
"""``bench run-ai-evals`` — run eval suites from a script, and fail on the rate.

Continuous integration needs three things the web entry points do not give it: a
way to pick suites without knowing their names, a pass rate to judge them by,
and an exit code. This is that.

    bench --site <site> run-ai-evals --role Smoke --backend deterministic --min-pass 100
    bench --site <site> run-ai-evals --role Nightly --backend live --min-pass 90
    bench --site <site> run-ai-evals --suite "Docu Agent — Baseline" --backend replay

The deterministic backend makes no model call at all, which is what a pull
request check can run before anyone has decided whose provider key it may spend.
It scores each case's assertions against the answer recorded on the case, so it
catches a broken evaluator, a changed assertion or a prompt that stopped
promising what it promised — and it cannot catch model drift, which is why the
live suites run on a schedule instead.
"""

import json

import click
import frappe
from frappe.commands import get_site, pass_context

from one_bpmn.agents.eval_runner import EVAL_BACKENDS, _execute_eval_suite


def _suites(role: str, suite: str) -> list[dict]:
	filters = {}
	if suite:
		filters["name" if frappe.db.exists("AI Eval Suite", suite) else "title"] = suite
	if role:
		filters["ci_role"] = role
	return frappe.get_all(
		"AI Eval Suite",
		filters=filters,
		fields=["name", "title", "ci_role"],
		order_by="title asc",
	)


def _run_one(suite: dict, backend: str) -> dict:
	"""Execute one suite here and now — no queue, so the exit code can wait for it."""
	run = frappe.get_doc({
		"doctype": "AI Eval Run",
		"suite": suite["name"],
		"status": "Running",
		"backend": backend,
		"scope": "Suite",
		"started_at": frappe.utils.now_datetime(),
		"agent_configuration": frappe.db.get_value(
			"AI Eval Suite", suite["name"], "agent_configuration"
		),
	})
	run.flags.ignore_mandatory = True
	run.insert(ignore_permissions=True)
	frappe.db.commit()

	_execute_eval_suite(run.name)
	frappe.db.commit()
	run.reload()

	checked = [r for r in run.results if r.status != "Skipped"]
	passed = [r for r in checked if r.status == "Passed"]
	titles = {
		c.name: c.title
		for c in frappe.get_all("AI Eval Case", filters={"suite": suite["name"]}, fields=["name", "title"])
	}
	return {
		"suite": suite["title"] or suite["name"],
		"run": run.name,
		"status": run.status,
		"cases": len(run.results or []),
		"checked": len(checked),
		"passed": len(passed),
		"skipped": len(run.results or []) - len(checked),
		# The rate is over what was actually CHECKED. Counting a skipped case as
		# a pass would let a suite whose assertions all need a model report 100%
		# from a run that verified nothing.
		"rate": (len(passed) / len(checked) * 100) if checked else None,
		"failures": [
			{
				"case": titles.get(r.eval_case) or r.eval_case,
				"status": r.status,
				# The assertion that actually failed, not the row's summary note:
				# a CI log is read once, in a hurry, by someone who did not write
				# the case.
				"why": _why(r),
			}
			for r in run.results if r.status in ("Failed", "Error")
		],
	}


def _why(result) -> str:
	"""What to print for a failed case: the assertions that did not hold."""
	try:
		assertions = json.loads(result.assertion_results or "[]")
	except Exception:
		assertions = []

	broken = [a for a in assertions if not a.get("passed")]
	if broken:
		return "; ".join(
			f"{a.get('assertion_type')}"
			+ (f" [{str(a.get('value'))[:60]}]" if a.get("value") else "")
			+ (f": {a.get('message') or a.get('explanation') or ''}".rstrip(": ") if (a.get("message") or a.get("explanation")) else "")
			for a in broken
		)[:400]
	return (result.error_message or "").strip()[:400] or "no detail recorded"


@click.command("run-ai-evals")
@click.option("--suite", default="", help="One suite, by name or title. Omit to select by role.")
@click.option("--role", default="", type=click.Choice(["", "Smoke", "Nightly"]),
			  help="Run every suite carrying this CI role.")
@click.option("--backend", default="deterministic", type=click.Choice(EVAL_BACKENDS),
			  help="deterministic makes no model call; replay re-scores stored answers and still calls the judge; live calls the model.")
@click.option("--min-pass", "min_pass", default=100.0, type=float,
			  help="Percent of checked cases that must pass. Below it, the command exits non-zero.")
@click.option("--skip-if-none", is_flag=True,
			  help="Exit 0 when no suite matches, instead of failing. For a scheduled job that must not go red before anything is tagged.")
@click.option("--allow-unchecked", is_flag=True,
			  help="Do not fail when a suite checked nothing. Off by default: a green check that verified nothing is worse than a red one.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable summary on stdout.")
@pass_context
def run_ai_evals(context, suite, role, backend, min_pass, skip_if_none, allow_unchecked, as_json):
	"""Run eval suites and exit non-zero below the minimum pass rate."""
	site = get_site(context)
	frappe.init(site=site)
	frappe.connect()
	frappe.set_user("Administrator")

	try:
		if not suite and not role:
			raise click.UsageError("Name a --suite or a --role; running every suite on the site is never what you want.")

		selected = _suites(role, suite)
		if not selected:
			what = f"role {role!r}" if role else f"suite {suite!r}"
			if skip_if_none:
				click.echo(f"No eval suite matches {what} on {site}; nothing to run.")
				raise SystemExit(0)
			# Failing here is the point on a pull request: a check that silently
			# runs nothing looks exactly like a check that passed.
			click.echo(f"No eval suite matches {what} on {site}.", err=True)
			raise SystemExit(1)

		summaries = [_run_one(s, backend) for s in selected]

		if as_json:
			click.echo(json.dumps({"site": site, "backend": backend, "min_pass": min_pass,
								   "suites": summaries}, indent=1, default=str))
		else:
			_report(summaries, backend, min_pass)

		failed = _verdict(summaries, min_pass, allow_unchecked)
		raise SystemExit(1 if failed else 0)
	finally:
		frappe.destroy()


def _report(summaries: list[dict], backend: str, min_pass: float) -> None:
	click.echo(f"\nai-evals · backend {backend} · minimum {min_pass:g}%\n")
	for s in summaries:
		rate = "nothing checked" if s["rate"] is None else f"{s['rate']:.1f}%"
		click.echo(f"  {s['suite']}")
		click.echo(f"    {s['passed']}/{s['checked']} checked cases passed ({rate})"
				   + (f", {s['skipped']} skipped" if s["skipped"] else ""))
		for failure in s["failures"]:
			click.echo(f"      {failure['status']}: {failure['case']} — {failure['why'] or 'no detail'}")
	click.echo("")


def _verdict(summaries: list[dict], min_pass: float, allow_unchecked: bool) -> bool:
	"""True when the command should fail. Reasons are printed as they are found."""
	failed = False
	for s in summaries:
		if s["rate"] is None:
			if not allow_unchecked:
				click.echo(f"FAIL {s['suite']}: nothing was checked — every case was skipped.", err=True)
				failed = True
			continue
		if s["rate"] < min_pass:
			click.echo(
				f"FAIL {s['suite']}: {s['rate']:.1f}% of {s['checked']} checked case(s) passed, "
				f"needs {min_pass:g}%.", err=True,
			)
			failed = True
	if not failed:
		click.echo("All selected suites met the minimum.")
	return failed
