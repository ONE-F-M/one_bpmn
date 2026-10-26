# Copyright (c) 2026, one-fm and contributors
"""What to do with a failed sandbox run, decided by the class of its failure."""

from __future__ import annotations

from dataclasses import dataclass

import frappe

from one_bpmn.one_bpmn.doctype.agent_sandbox_run.agent_sandbox_run import bounded_error


@dataclass(frozen=True)
class Policy:
	tries: int  # attempts in all, the first included
	delays: tuple[int, ...] = ()  # seconds to wait before attempt 2, attempt 3 and so on
	retry: bool = False  # run it again by itself; otherwise the failure goes back to the agent


POLICIES = {
	"infra": Policy(3, (15, 60), retry=True),
	"model-api": Policy(5, (10, 30, 60, 120), retry=True),
	"env": Policy(2, (0,), retry=True),
	"code": Policy(3),
	"gave-up": Policy(1),
	"policy": Policy(1),
}

_ADVICE = (
	(
		("403", "forbidden", "permission denied", "bad credentials"),
		"The GitHub token in Processa Settings cannot write to {app}. Give it access to that repository, then run it again.",
	),
	(
		("couldn't find remote ref",),
		"The branch {branch} does not exist on GitHub. Correct the Work Item's Branch field, then run it again.",
	),
)


def next_step(run) -> dict:
	"""The action for a failed run: retry it, give the failure back to the agent, or stop."""
	reason = run.failure_class or ""
	policy = POLICIES.get(reason)
	if policy is None:
		return {"action": "return", "attempt": 1, "of": 1, "reason": reason, "delay": 0, "advice": ""}
	attempt = _attempt(run)
	if policy.retry and attempt < policy.tries:
		delay = policy.delays[min(attempt - 1, len(policy.delays) - 1)]
		action = "retry"
	else:
		delay = 0
		action = "stop" if reason == "policy" or attempt >= policy.tries > 1 else "return"
	return {
		"action": action,
		"attempt": attempt,
		"of": policy.tries,
		"reason": reason,
		"delay": delay,
		"advice": _advice(run),
	}


def record(run, step: dict) -> None:
	"""Show the attempt on the Work Item, and put it and any fix in the run's error so the agent reads them."""
	if step["of"] > 1:
		note = f"Attempt {step['attempt']} of {step['of']}, reason: {step['reason']}"
		if run.work_item and frappe.db.exists("Work Item", run.work_item):
			frappe.get_doc("Work Item", run.work_item).add_comment("Comment", note)
		if step["action"] != "retry":
			lines = [f"{note}."]
			if step["action"] == "stop":
				lines.append(
					"No more attempts. Open the pull request with what you have and report what still fails."
				)
			run.db_set(
				"error_message",
				bounded_error(" ".join([*lines, run.error_message or ""])),
				update_modified=False,
			)
	if step["advice"]:
		run.db_set(
			"error_message",
			bounded_error(f"{step['advice']} {run.error_message or ''}"),
			update_modified=False,
		)


def _attempt(run) -> int:
	"""A code failure is the Work Item's Nth failing run of this action; any other is the run's own attempt."""
	if run.failure_class == "code" and run.work_item:
		return frappe.db.count(
			"Agent Sandbox Run", {"work_item": run.work_item, "action": run.action, "failure_class": "code"}
		)
	return max(run.attempt or 1, 2 if run.retry_of else 1)


def _advice(run) -> str:
	text = (run.error_message or "").lower()
	for markers, advice in _ADVICE:
		if any(marker in text for marker in markers):
			return advice.format(app=run.target_app, branch=run.git_branch)
	return ""
