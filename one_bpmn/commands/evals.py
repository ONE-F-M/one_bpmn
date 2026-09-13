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

from one_bpmn.agents.eval_ci import run_suite, select_suites
from one_bpmn.agents.eval_runner import EVAL_BACKENDS


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

		selected = select_suites(role, suite)
		if not selected:
			what = f"role {role!r}" if role else f"suite {suite!r}"
			if skip_if_none:
				click.echo(f"No eval suite matches {what} on {site}; nothing to run.")
				raise SystemExit(0)
			# Failing here is the point on a pull request: a check that silently
			# runs nothing looks exactly like a check that passed.
			click.echo(f"No eval suite matches {what} on {site}.", err=True)
			raise SystemExit(1)

		summaries = [run_suite(s, backend) for s in selected]

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
		if s.get("stopped"):
			click.echo(f"    {s['stopped']}")
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
