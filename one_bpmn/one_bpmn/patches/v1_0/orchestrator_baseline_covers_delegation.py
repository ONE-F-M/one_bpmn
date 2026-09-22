"""The Orchestrator Baseline gains the routes it was only ever tested against.

Every case so far asserted that no sandbox specialist was called, because a real
delegation runs one in Cloud Run and can open a pull request. Positive routing
was tested through the Connector Agent alone. With delegation recorded and
stopped under eval (a2a_client_ops), a brief that plainly belongs to one
specialist can now assert that specialist was chosen — and that no other was.

Four briefs, one per sandbox specialist. Each is written so the right route is
the only defensible reading: the work names its own surface.

Idempotent — cases are matched by title and their fixtures reused.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0 import agent_baselines_cover_more as more
from one_bpmn.one_bpmn.patches.v1_0 import orchestrator_agent_baseline_covers_every_tool as orchestrator

DELEGATES = more.DELEGATE_TOOLS.split(",")


def _others(chosen: str) -> str:
	return ",".join(t for t in DELEGATES if t != chosen)


def _route(key: str, tool: str, kind: str, title: str, description: str, target_app: str) -> dict:
	"""One brief whose only defensible route is ``tool``.

	target_app and git_branch are set because the orchestrator refuses to delegate
	without them — it hands the item back asking for the repository and branch,
	which is correct behaviour and exactly what the first run of these cases
	caught. A routing case has to clear that bar before it can test routing.
	"""
	return {
		"key": key,
		"title": title,
		"case_type": "Trajectory",
		"work_item": orchestrator._item(
			kind, title.split(" goes to ")[0], description,
			target_app=target_app, git_branch="staging",
		),
		"assertions": [
			more.GUARD,
			{"assertion_type": "no_tool_call", "value": _others(tool)},
			{"assertion_type": "tool_calls", "value": "ANY_ORDER"},
		],
		"expected_tool_calls": [{"call_order": 1, "tool_name": tool}],
	}


CASES = [
	_route(
		"route_dev", "delegate_dev_agent", "User Story",
		"A server-side rule change goes to the Dev Agent",
		"<p>Leave Application currently lets an employee apply for leave that starts before their date of "
		"joining. Add a validation in the one_fm app so a Leave Application whose from_date is earlier than "
		"the employee's date_of_joining is refused on save, with a message naming both dates.</p>"
		"<p>Server-side Python only; no screen changes.</p>",
		"one_fm",
	),
	_route(
		"route_frontend", "delegate_frontend_agent", "User Story",
		"A screen-only change goes to the Frontend Agent",
		"<p>On the Processa editor, the Deploy button sits at the far right of the toolbar and users miss it. "
		"Move it next to Save and give it the primary colour. No backend change: the deploy endpoint and "
		"its behaviour stay exactly as they are.</p>"
		"<p>Vue in the spiff app, one component.</p>",
		"one_bpmn",
	),
	_route(
		"route_mobile", "delegate_mobile_app_agent", "User Story",
		"A change to the Ionic app goes to the Mobile App Agent",
		"<p>In the ONE FM mobile app, the check-in screen shows the raw ISO timestamp under the button. Show "
		"it as a local time in 12-hour format instead. This is the Ionic app in the mobile_app_ionic "
		"repository; nothing on the Frappe side changes.</p>",
		"mobile_app_ionic",
	),
	_route(
		"route_bug", "delegate_bug_agent", "Bug",
		"A reproducible defect with a traceback goes to the Bug Agent",
		"<p>Saving an Employee with an empty Department raises instead of validating:</p>"
		"<pre>AttributeError: 'NoneType' object has no attribute 'strip'\n"
		"  File one_fm/overrides/employee.py, line 41, in validate</pre>"
		"<p>Reproduces every time on staging with a new Employee and no Department. Expected: the ordinary "
		"mandatory-field message.</p>",
		"one_fm",
	),
]


def execute():
	baseline = frappe.db.get_value("AI Eval Suite", {"title": orchestrator.SUITE_TITLE}, "name")
	if not baseline or not frappe.db.exists("BPMN Process Model", orchestrator.MAP):
		return
	sprint = orchestrator._fixture_sprint()
	if not sprint:
		return
	for spec in CASES:
		existing = frappe.db.get_value("AI Eval Case", {"suite": baseline, "title": spec["title"]}, "name")
		item = orchestrator._work_item(existing, sprint, dict(spec["work_item"]), None)
		more._write(existing, baseline, spec, orchestrator.MAP, orchestrator.SHAPE, spec["work_item"]["title"],
		            {"context_doctype": "Work Item", "context_docname": item})
	frappe.db.commit()
