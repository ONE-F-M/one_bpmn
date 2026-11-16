"""One Agent Sandbox Trace per agent run, listing every sandbox call that run made.

Each call stays its own Agent Sandbox Run, because a parked agent waits on that row and the gates read it.
The trace mirrors those rows so a whole run is read in one place.
"""

import frappe
from frappe.utils import cint

OPEN_STATES = ("submitted", "running")
FAILED_STATES = ("failed", "stale", "timed_out")
EDIT_ACTIONS = ("edit_file", "write_file", "apply_edits", "delete_file")
SUMMARY_ARGS = ("path", "paths", "pattern", "prefix", "query")
SUMMARY_LIMIT = 140
TIMING_FIELDS = ("http_ms", "sandbox_ms", "git_ms", "tool_ms", "test_ms", "pr_ms")
CALL_FIELDS = ("action", "state", "started_at", "commit_sha", "pr_url", "error_message", *TIMING_FIELDS)

_ready_sites: set = set()


def _tables_exist() -> bool:
	"""False until bench migrate has created the trace tables, so a deploy ahead of the migrate keeps sandbox calls working."""
	if frappe.local.site in _ready_sites:
		return True
	if not frappe.db.table_exists("Agent Sandbox Trace"):
		return False
	_ready_sites.add(frappe.local.site)
	return True


def sync(run) -> None:
	"""Mirrors one Agent Sandbox Run into its trace and refreshes the trace totals."""
	if not _tables_exist():
		return
	trace = _trace_for(run)
	values = {field: run.get(field) for field in CALL_FIELDS}
	values.update({field: cint(run.get(field)) for field in TIMING_FIELDS})
	values.update(summary=_summary(run), ended_at=run.get("completed_at"))
	line = frappe.db.get_value("Agent Sandbox Trace Call", {"parent": trace, "run": run.name})
	if line:
		frappe.db.set_value("Agent Sandbox Trace Call", line, values, update_modified=False)
	else:
		sequence = frappe.db.count("Agent Sandbox Trace Call", {"parent": trace}) + 1
		call = frappe.get_doc(
			{
				"doctype": "Agent Sandbox Trace Call", "parent": trace, "parenttype": "Agent Sandbox Trace",
				"parentfield": "calls", "idx": sequence, "sequence": sequence, "run": run.name, **values,
			}
		)
		call.flags.ignore_links = True
		call.insert(ignore_permissions=True)
	_roll_up(trace, run)


def _trace_for(run) -> str:
	caller = run.get("caller_instance")
	found = (
		frappe.db.get_value("Agent Sandbox Trace", {"caller_instance": caller})
		if caller
		else frappe.db.get_value("Agent Sandbox Trace Call", {"run": run.name}, "parent")
	)
	if found:
		return found
	trace = frappe.get_doc({"doctype": "Agent Sandbox Trace", "caller_instance": caller, "started_at": run.get("started_at")})
	# The caller is the run's own link, already accepted when the run was saved.
	trace.flags.ignore_links = True
	return trace.insert(ignore_permissions=True).name


def _summary(run) -> str:
	args = (frappe.parse_json(run.get("request_payload") or "{}") or {}).get("args") or {}
	for key in SUMMARY_ARGS:
		value = args.get(key)
		if value:
			return (", ".join(map(str, value)) if isinstance(value, list) else str(value))[:SUMMARY_LIMIT]
	return ""


def _same_file_edit(before, line) -> bool:
	return line.action == before.action == "edit_file" and bool(line.summary) and line.summary == before.summary


def _roll_up(trace: str, run) -> None:
	lines = frappe.get_all(
		"Agent Sandbox Trace Call", parent_doctype="Agent Sandbox Trace", filters={"parent": trace},
		fields=["action", "state", "summary", "ended_at", "commit_sha", "pr_url", "error_message", *TIMING_FIELDS],
		order_by="sequence asc", limit_page_length=0,
	)
	running = any(line.state in OPEN_STATES for line in lines)
	totals = {field: sum(line.get(field) or 0 for line in lines) for field in TIMING_FIELDS}
	totals.update(
		call_count=len(lines),
		edit_count=sum(1 for line in lines if line.action in EDIT_ACTIONS and line.state == "completed"),
		test_runs=sum(1 for line in lines if line.action == "run_tests"),
		repeat_edits=sum(1 for before, line in zip(lines, lines[1:]) if _same_file_edit(before, line)),
		failed_calls=sum(1 for line in lines if line.state in FAILED_STATES),
		state="running" if running else "finished",
		ended_at=None if running else max((line.ended_at for line in lines if line.ended_at), default=None),
		pr_url=next((line.pr_url for line in reversed(lines) if line.pr_url), None),
		last_commit_sha=next((line.commit_sha for line in reversed(lines) if line.commit_sha), None),
		last_error=next((line.error_message for line in reversed(lines) if line.error_message), None),
	)
	identity = frappe.db.get_value("Agent Sandbox Trace", trace, ["agent_name", "work_item", "target_app", "git_branch"], as_dict=True)
	for field, value in identity.items():
		if not value and run.get(field):
			totals[field] = run.get(field)
	frappe.db.set_value("Agent Sandbox Trace", trace, totals, update_modified=False)
