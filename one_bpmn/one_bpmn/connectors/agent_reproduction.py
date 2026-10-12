"""Bug discipline outputs: the not-reproducible outcome, and the reproduction record shown on the pull request."""

import frappe

from one_bpmn.one_bpmn.connectors import agent_sandbox_ops as ops

NOT_REPRODUCIBLE_ACTION = "not_reproducible"
SECTION = "## Reproduction"
OUTPUT_CHARS = 1500


def record_not_reproducible(
	target_app: str, git_branch: str, work_item_description: str, tried, needed, *, bpmn_id: str | None = None, instance=None
) -> dict:
	"""Record that the bug could not be reproduced and tell the agent to stop. A person gets the item next."""
	work_item = ops.work_item_id_for(ops._a2a_task_of(instance))
	frappe.get_doc({
		"doctype": "Agent Sandbox Run", "state": "completed", "completed_at": frappe.utils.now(),
		"action": NOT_REPRODUCIBLE_ACTION, "failure_class": "not-reproducible", "work_item": work_item,
		"agent_name": getattr(instance, "process_model", None), "target_app": target_app, "git_branch": git_branch,
		"bpmn_id": bpmn_id, "caller_instance": getattr(instance, "name", None), "work_item_description": work_item_description,
		"request_payload": frappe.as_json({"action": NOT_REPRODUCIBLE_ACTION, "args": {"tried": str(tried or ""), "needed": str(needed or "")}}),
	}).insert(ignore_permissions=True, ignore_links=True)
	if work_item and frappe.db.exists("Work Item", work_item):
		frappe.get_doc("Work Item", work_item).add_comment(
			"Comment",
			"<b>Could not reproduce</b><br><b>Tried:</b> " + frappe.utils.escape_html(str(tried or "-"))
			+ "<br><b>Needed to go further:</b> " + frappe.utils.escape_html(str(needed or "-")),
		)
	return {
		"ok": True, "outcome": "not_reproducible",
		"message": "Recorded. Make no further changes. Start your final report with NOT REPRODUCIBLE, then say what you tried and what is needed.",
	}


def not_reproducible_error(instance) -> str | None:
	"""The error that holds every change once the run has reported the bug as not reproducible."""
	if instance is None:
		return None
	for _row, action, _paths in ops._run_history(instance):
		if action == NOT_REPRODUCIBLE_ACTION:
			return "You reported this bug as not reproducible. Make no further changes; give your final report."
	return None


def reproduction_section(work_item: str) -> str:
	"""The Markdown that shows the test failing before the fix and passing after it, with the commits, or ''."""
	rows = frappe.get_all(
		"Agent Sandbox Run",
		filters={"work_item": work_item, "action": "run_tests", "state": ["in", ["failed", "completed"]]},
		fields=["state", "result", "commit_sha"],
		order_by="creation asc",
	)
	failing = next((r for r in rows if r.state == "failed" and (frappe.parse_json(r.result or "{}") or {}).get("failing_tests")), None)
	if not failing:
		return ""
	result = frappe.parse_json(failing.result)
	later = [r for r in rows[rows.index(failing) + 1 :] if r.state == "completed"]
	output = (result.get("stderr_tail") or result.get("stdout_tail") or "").strip()[-OUTPUT_CHARS:]
	lines = [SECTION, "", f"Test: `{result['failing_tests'][0]}`", ""]
	lines += [f"Failed before the fix{_at(failing.commit_sha)}:", "", "```", output or "(no output captured)", "```", ""]
	lines.append(f"Passes after the fix{_at(later[-1].commit_sha)}." if later else "No passing run after the fix is recorded.")
	return "\n".join(lines)


def _at(commit: str | None) -> str:
	return f" (commit {commit[:10]})" if commit else ""
