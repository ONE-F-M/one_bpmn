"""Acceptance criteria: read from the delegation, checked against the plan and the diff, and shown on the pull request."""

import os
import re

import frappe

from one_bpmn.one_bpmn.connectors import agent_sandbox_ops as ops

CRITERION = re.compile(r"^\s*(?:[-*]\s*)?\**(AC\d+)\**\s*[:.)\-]\s*(.+?)\s*$", re.MULTILINE)
STATUSES = ("done", "partial", "not_done")
EVIDENCE_ACTION = "submit_evidence"
SECTION = "## Acceptance criteria"
TEST_TOKEN = re.compile(r"(^|[/\s])(tests?/|test_\w+|\w+\.(test|spec)\.\w+)", re.IGNORECASE)
CHANGING_ACTIONS = ("edit_file", "write_file", "apply_edits", "delete_file")


def criteria_for(instance) -> list[dict]:
	"""The numbered criteria the orchestrator wrote into this run's delegation, or [] when it gave none."""
	if getattr(instance, "context_doctype", None) != "A2A Task":
		return []
	found = {}
	for criterion_id, text in CRITERION.findall(ops._a2a_instruction(instance.context_docname)):
		found.setdefault(criterion_id, text)
	return [{"id": criterion_id, "text": text} for criterion_id, text in found.items()]


def has_tool(instance, script_name: str) -> bool:
	"""Whether the agent's map offers the tool whose Server Script name ends with script_name. A gate that asks for
	a step the agent cannot take would block it for good, so a gate applies only when the tool is there. When the
	map cannot be found the gate stays on."""
	model = getattr(instance, "process_model", None)
	key = f"agent_has_tool:{model}:{script_name}"
	known = frappe.cache.get_value(key, expires=True)
	if known is None:
		xml = frappe.db.get_value("BPMN Process Model", model, "bpmn_xml") if model else None
		known = 1 if xml is None else int(re.search(rf'serverScript="[^"]*{re.escape(script_name)}"', xml) is not None)
		frappe.cache.set_value(key, known, expires_in_sec=600)
	return bool(known)


def plan_gap_error(instance) -> str | None:
	"""None unless the run has criteria that its latest plan does not mention, for an agent that can submit a plan."""
	criteria = criteria_for(instance)
	if not criteria or not has_tool(instance, "Submit Plan"):
		return None
	plan = str(_latest_args(instance, ops._PLAN_ACTION).get("plan") or "")
	missing = [c for c in criteria if not re.search(rf"\b{c['id']}\b", plan)]
	if not missing:
		return None
	listing = "; ".join(f"{c['id']}: {c['text']}" for c in missing)
	return (
		f"Your plan does not address {', '.join(c['id'] for c in missing)}. For each acceptance criterion, name the "
		f"files and tests that address it, then call submit_plan again before changing anything. Missing: {listing}"
	)


def evidence_gap_error(instance) -> str | None:
	"""None unless the run has criteria and no accepted evidence table, for an agent that can submit one."""
	if not criteria_for(instance) or not has_tool(instance, "Submit Evidence"):
		return None
	if _latest_args(instance, EVIDENCE_ACTION) and not _latest_args(instance, EVIDENCE_ACTION).get("problems"):
		return None
	return "Call submit_evidence with one row per acceptance criterion, and fix anything it reports, before opening the pull request."


def record_evidence(
	target_app: str, git_branch: str, work_item_description: str, rows, *, bpmn_id: str | None = None, instance=None
) -> dict:
	"""Check the agent's criteria table against the branch's diff, record it, and say what to fix."""
	criteria = criteria_for(instance)
	if not criteria:
		return {"ok": True, "message": "This work order has no numbered acceptance criteria, so there is nothing to record."}
	rows = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
	work_item = ops.work_item_id_for(ops._a2a_task_of(instance))
	problems = evidence_problems(criteria, rows, _branch_files(target_app, git_branch, work_item))
	frappe.get_doc({
		"doctype": "Agent Sandbox Run", "state": "completed", "completed_at": frappe.utils.now(),
		"action": EVIDENCE_ACTION, "agent_name": getattr(instance, "process_model", None), "work_item": work_item,
		"target_app": target_app, "git_branch": git_branch, "bpmn_id": bpmn_id,
		"caller_instance": getattr(instance, "name", None), "work_item_description": work_item_description,
		"request_payload": frappe.as_json({
			"action": EVIDENCE_ACTION, "args": {"criteria": criteria, "evidence": rows, "problems": problems},
		}),
	}).insert(ignore_permissions=True, ignore_links=True)
	if problems:
		return {"ok": False, "problems": problems, "message": "Fix these and call submit_evidence again."}
	unmet = [r["id"] for r in rows if r.get("status") != "done"]
	return {"ok": True, "unmet": unmet, "message": "Evidence recorded." + (f" Still unmet: {', '.join(unmet)}." if unmet else "")}


def evidence_problems(criteria: list[dict], rows: list[dict], changed_files: list[str] | None) -> list[str]:
	"""What is wrong with the table: a missing criterion, a bad status, or a 'done' that cites no changed file and no test."""
	by_id = {row.get("id"): row for row in rows}
	problems = []
	for criterion in criteria:
		row = by_id.get(criterion["id"])
		if row is None:
			problems.append(f"{criterion['id']} has no row.")
		elif row.get("status") not in STATUSES:
			problems.append(f"{criterion['id']}: status must be one of {', '.join(STATUSES)}.")
		elif row["status"] == "done":
			evidence = str(row.get("evidence") or "").strip()
			if not evidence:
				problems.append(f"{criterion['id']}: done needs evidence, a changed file or a test name.")
			elif not _cites(evidence, changed_files):
				problems.append(f"{criterion['id']}: the evidence names no file changed on this branch and no test.")
	return problems


def criteria_report(work_item: str) -> dict:
	"""The criteria of a Work Item with the status the agent reported for each, as a Markdown table."""
	latest = {}
	for row in frappe.get_all(
		"Agent Sandbox Run",
		filters={"work_item": work_item, "action": ["in", [EVIDENCE_ACTION, ops._PLAN_ACTION]], "state": "completed"},
		fields=["action", "request_payload"],
		order_by="creation desc",
	):
		args = (frappe.parse_json(row.request_payload) or {}).get("args") or {}
		if args.get("criteria"):
			latest.setdefault(row.action, args)
	args = latest.get(EVIDENCE_ACTION) or latest.get(ops._PLAN_ACTION)
	if not args:
		return {"has_criteria": False, "unmet": [], "markdown": ""}
	reported = {r.get("id"): r for r in args.get("evidence") or []}
	lines, unmet = ["| Criterion | Status | Evidence |", "|---|---|---|"], []
	for criterion in args["criteria"]:
		row = reported.get(criterion["id"]) or {}
		status = row.get("status") or "not reported"
		if status != "done":
			unmet.append(criterion["id"])
		lines.append(f"| {criterion['id']}: {_cell(criterion['text'])} | {status} | {_cell(row.get('evidence') or '')} |")
	return {"has_criteria": True, "unmet": unmet, "markdown": "\n".join(lines)}


def publish_criteria(work_item: str, repo: str, pr: dict, token: str) -> dict:
	"""Put the criteria table and the bug reproduction record in the pull request body in one update, and turn a
	PR with unmet criteria into a draft."""
	from one_bpmn.one_bpmn.connectors.agent_reproduction import SECTION as REPRODUCTION, reproduction_section

	report = criteria_report(work_item)
	reproduction = reproduction_section(work_item)
	if not (report["has_criteria"] or reproduction):
		return {}
	body = pr.get("body") or ""
	new_body = body
	if report["has_criteria"]:
		section = f"{SECTION}\n\n{report['markdown']}"
		if report["unmet"]:
			section += f"\n\nUnmet: {', '.join(report['unmet'])}. Opened as a draft until these are done."
		new_body = _with_section(new_body, SECTION, section)
	if reproduction:
		new_body = _with_section(new_body, REPRODUCTION, reproduction)
	if new_body != body:
		_github("PATCH", f"/repos/{repo}/pulls/{pr['number']}", token, {"body": new_body})
	if report["unmet"] and not pr.get("draft") and pr.get("node_id"):
		_github("POST", "/graphql", token, {
			"query": "mutation($id: ID!) { convertPullRequestToDraft(input: {pullRequestId: $id}) { pullRequest { isDraft } } }",
			"variables": {"id": pr["node_id"]},
		})
	if report["unmet"] and new_body != body:
		frappe.get_doc("Work Item", work_item).add_comment(
			"Comment", "<b>Unmet acceptance criteria</b><br>" + frappe.utils.escape_html(", ".join(report["unmet"]))
		)
	return {"criteria_unmet": report["unmet"]} if report["has_criteria"] else {}


def _with_section(body: str, heading: str, section: str) -> str:
	"""The body with this section added, or replaced in place when it is already there."""
	if heading in body:
		return re.sub(rf"{heading}.*?(?=\n## |\Z)", lambda _: section, body, flags=re.S)
	return f"{body}\n\n{section}".strip()


def _latest_args(instance, action: str) -> dict:
	rows = frappe.get_all(
		"Agent Sandbox Run",
		filters={"caller_instance": instance.name, "action": action, "state": "completed"},
		fields=["request_payload"],
		order_by="creation desc",
		limit_page_length=1,
	)
	return (frappe.parse_json(rows[0].request_payload) or {}).get("args") or {} if rows else {}


def _cites(evidence: str, changed_files: list[str] | None) -> bool:
	if TEST_TOKEN.search(evidence):
		return True
	if changed_files is None:
		return True
	return any(path in evidence or os.path.basename(path) in evidence for path in changed_files)


def _compare(target_app: str, git_branch: str, work_item: str) -> dict | None:
	"""GitHub's comparison of the Work Item's branch with its base, or None when GitHub cannot be asked."""
	import requests

	access = ops.github_access(target_app)
	if not (access and work_item and git_branch):
		return None
	repo, token = access
	response = requests.get(
		f"https://api.github.com/repos/{repo}/compare/{git_branch}...{work_item}",
		headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
		timeout=15,
	)
	return response.json() if response.status_code == 200 else None


def _branch_files(target_app: str, git_branch: str, work_item: str) -> list[str] | None:
	"""Files changed on the Work Item's branch against its base, or None when GitHub cannot be asked."""
	compared = _compare(target_app, git_branch, work_item)
	return None if compared is None else [f["filename"] for f in compared.get("files", [])]


def branch_summary(work_item: str, target_app: str, git_branch: str) -> str:
	"""What an earlier attempt left on the Work Item's branch, for the orchestrator's brief, or '' when it left nothing."""
	compared = _compare(target_app, git_branch, work_item)
	if not compared or not compared.get("ahead_by"):
		return ""
	commits = [c["commit"]["message"].splitlines()[0][:100] for c in compared.get("commits", [])][-5:]
	files = [f["filename"] for f in compared.get("files", [])][:20]
	lines = [
		f"Branch {work_item} already has {compared['ahead_by']} commit(s) from an earlier attempt, ahead of {git_branch}. "
		"Continue from them and do not start over.",
		"Latest commits:", *[f"- {message}" for message in commits],
		"Files changed so far:", *[f"- {name}" for name in files],
	]
	return "\n".join(lines)


def _github(method: str, path: str, token: str, body: dict):
	import requests

	response = requests.request(
		method, f"https://api.github.com{path}", json=body, timeout=20,
		headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
	)
	response.raise_for_status()
	return response.json()


def _cell(text: str) -> str:
	return " ".join(str(text).split()).replace("|", "/")[:300]
