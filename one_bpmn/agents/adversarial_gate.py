# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
The adversarial go-live gate for chat agents.

A conversational agent is reachable by anyone who can open a chat box, so it is
the one surface where an untested prompt is an exposed prompt. This module
answers a single question — *may this chat agent go Live?* — and both halves of
the answer are deliberately strict.

A PASSING ADVERSARIAL SUITE
---------------------------
Not just "a suite that passed". The agent needs at least one AI Eval Suite of
type Adversarial whose most recent completed run had zero failures AND ran
*after* the agent was last changed. The recency clause is the point: without it
a clean run from three months ago keeps clearing a system prompt that was
rewritten yesterday, which is precisely the hole a go-live gate exists to close.

A CONFORMING MAP
----------------
The suite proves the agent resisted the attacks it was shown. The conformance
check proves the screening stage is actually wired into the map that will run in
production, so an agent cannot pass its adversarial suite and then ship a map
with the screen removed. See ``conformance.py``.

WHAT THIS DOES NOT DO
---------------------
It never touches an agent that is already Live. The gate runs when an agent is
provisioned from Draft; agents that went Live before this existed keep running,
and ``ungated_live_agents`` reports them so the gap is visible rather than
resolved by taking production offline.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

# The suite type that satisfies the gate.
ADVERSARIAL = "Adversarial"


def is_conversational(agent: str) -> bool:
	"""Is this agent a CHAT agent, and therefore subject to the release gate?

	Every agent type now walks the Agent Creation Process — the map's start
	condition is lifecycle_status only — so deciding WHO the adversarial gate
	applies to moved here. It applies to chat agents: they are reachable by
	anyone who can open a chat box, which is the exposure the gate exists for.
	A Background agent has no chat surface to attack and no cloned map to keep
	a screening stage in.

	``chat_mode_label`` was considered as a second signal and deliberately not
	used: the doctype only enforces label uniqueness for agent_type == "Chat"
	(validate_unique_chat_mode_label), so a label on a Background agent is
	unvalidated and not a dependable statement about exposure. One signal that
	means something beats two that can disagree.

	Lives here rather than only inside the map's gate step so there is ONE
	definition that can be tested, while the map keeps the decision and the
	routing. Fails CLOSED — an agent that cannot be read is treated as exposed,
	since this feeds a release gate.
	"""
	agent_type = frappe.db.get_value("AI Agent Configuration", agent, "agent_type")
	if agent_type is None:
		return True
	return agent_type == "Chat"


def adversarial_suites(agent: str) -> list[str]:
	"""Adversarial suites linked to this agent."""
	try:
		return frappe.get_all(
			"AI Eval Suite",
			filters={"agent_configuration": agent, "suite_type": ADVERSARIAL},
			pluck="name",
			limit_page_length=0,
		)
	except Exception:
		return []


# AI Eval Run statuses that mean "this run finished". Running is excluded — an
# in-flight run has proved nothing yet — and Error means the run itself broke,
# which is not a pass.
TERMINAL_STATUSES = ("Passed", "Failed", "Error")


def latest_run(suite: str) -> dict | None:
	"""The most recent finished run of a suite, or None."""
	rows = frappe.get_all(
		"AI Eval Run",
		filters={"suite": suite, "status": ("in", list(TERMINAL_STATUSES))},
		fields=["name", "status", "total_cases", "passed_cases", "failed_cases", "ended_at", "creation"],
		order_by="creation desc",
		limit=1,
	)
	return rows[0] if rows else None


def _cutoff(agent: str, suite: str):
	"""The moment a run has to be newer than to count as evidence: whichever of
	the agent or the suite changed last. Shared by check() and ensure_fresh_runs
	so "is this stale?" has one answer."""
	stamps = [
		frappe.db.get_value("AI Agent Configuration", agent, "modified"),
		frappe.db.get_value("AI Eval Suite", suite, "modified"),
	]
	stamps = [d for d in stamps if d]
	return max(stamps) if stamps else None


def has_fresh_run(agent: str, suite: str) -> bool:
	"""Has this suite been executed since the agent and the suite last changed?"""
	run = latest_run(suite)
	if not run:
		return False
	ran_at = run.get("ended_at") or run.get("creation")
	cut = _cutoff(agent, suite)
	if not (cut and ran_at):
		return True
	return get_datetime(ran_at) >= get_datetime(cut)


def ensure_fresh_runs(agent: str) -> list[str]:
	"""Execute any adversarial suite that has no run newer than the last change.

	The gate reads runs; it never used to make them, so an agent could be parked
	for a suite the process was perfectly able to execute itself — the designer
	had to go and press Run, then come back. This closes that.

	Runs SYNCHRONOUSLY and deliberately: the caller is a script task deciding
	whether to open a release gate, and a verdict read before the run finished
	would be worse than a slow one. Enqueuing would return immediately and the
	gate would judge a run still in flight.

	A suite that already has a fresh run is left alone, so clicking again after a
	pass costs nothing. Never raises — a suite that cannot be run stays without a
	fresh result and the gate refuses on that, which is the safe direction.

	Returns the suites it actually ran.
	"""
	from one_bpmn.agents.eval_runner import _execute_eval_suite

	ran = []
	for suite in adversarial_suites(agent):
		if has_fresh_run(agent, suite):
			continue
		try:
			run = frappe.new_doc("AI Eval Run")
			run.suite = suite
			run.status = "Running"
			run.backend = "live"
			run.scope = "Suite"
			run.started_at = now_datetime()
			# System-written record of an action the process is already
			# authorised for, exactly as the other eval entry points do.
			run.insert(ignore_permissions=True)
			_execute_eval_suite(run.name)
			ran.append(suite)
		except Exception:
			frappe.log_error(
				title=f"Adversarial suite could not be run ({suite})",
				message=frappe.get_traceback(),
			)
	return ran


def check(agent: str) -> dict:
	"""Can this chat agent go Live? Returns {"ok": bool, "reason": str, ...}.

	Never raises. A gate that crashes must not become an outage in the creation
	flow — but note it fails CLOSED: an unreadable suite table means "cannot
	prove it is tested", and the honest answer to that is no. That is the
	opposite of the screening controls, and deliberately so: this authorises a
	release rather than observing traffic.
	"""
	try:
		suites = adversarial_suites(agent)
		if not suites:
			return {
				"ok": False,
				"reason": _(
					"No adversarial eval suite is linked to this agent. A chat agent cannot go "
					"Live until it has been tested against injection, jailbreak, exfiltration "
					"and tool coercion."
				),
				"suites": [],
			}

		agent_changed = frappe.db.get_value("AI Agent Configuration", agent, "modified")
		stale, failed = [], []

		for suite in suites:
			# A run is evidence only if it is newer than BOTH the agent and the
			# suite. The suite's own timestamp matters because a suite can be
			# edited — or reassigned to a different agent entirely. Without this,
			# moving a generic suite from a tested agent to an untested one would
			# carry the old pass across and open the gate for an agent nothing
			# has ever attacked.
			changed_at = _cutoff(agent, suite)
			run = latest_run(suite)
			if not run:
				stale.append(f"{suite} (never run)")
				continue
			if run.get("status") == "Error":
				failed.append(f"{suite} (last run errored)")
				continue
			if int(run.get("failed_cases") or 0) > 0 or not int(run.get("total_cases") or 0):
				failed.append(f"{suite} ({run.get('failed_cases')} failed)")
				continue
			ran_at = run.get("ended_at") or run.get("creation")
			if changed_at and ran_at and get_datetime(ran_at) < get_datetime(changed_at):
				what = "the agent" if changed_at == agent_changed else "the suite"
				stale.append(f"{suite} (last passed before {what} was changed)")
				continue
			return {"ok": True, "reason": "", "suite": suite, "run": run.get("name")}

		problems = failed + stale
		return {
			"ok": False,
			"reason": _("No adversarial suite currently passes for this agent: {0}.").format(
				"; ".join(problems)
			),
			"suites": suites,
		}
	except Exception:
		frappe.log_error(
			title=f"Adversarial gate check failed ({agent})",
			message=frappe.get_traceback(),
		)
		return {
			"ok": False,
			"reason": _(
				"The adversarial gate could not be evaluated, so go-live is refused. "
				"See the Error Log."
			),
			"suites": [],
		}


@frappe.whitelist()
def gate_status(agent: str) -> dict:
	"""Whitelisted read of the gate, for a UI to show before someone tries."""
	frappe.has_permission("AI Agent Configuration", "read", throw=True)
	result = check(agent)
	result["agent"] = agent
	return result


@frappe.whitelist()
def ungated_live_agents() -> list[dict]:
	"""Live chat agents with no currently-passing adversarial suite.

	The gate only runs on the way to Live, so agents that went Live before this
	existed are untouched — which is right, but the gap must not be invisible.
	This lists them so someone can decide, rather than discovering it after an
	incident.
	"""
	frappe.has_permission("AI Agent Configuration", "read", throw=True)

	out = []
	for agent in frappe.get_all(
		"AI Agent Configuration",
		filters={"agent_type": "Chat", "lifecycle_status": "Live"},
		fields=["name", "agent_id", "chat_mode_label"],
		limit_page_length=0,
	):
		result = check(agent.name)
		if not result["ok"]:
			out.append({
				"agent": agent.name,
				"agent_id": agent.agent_id,
				"chat_mode_label": agent.chat_mode_label,
				"reason": result["reason"],
			})
	return out
