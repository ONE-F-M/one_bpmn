"""The Orchestrator Baseline gains the routes it was only ever tested against.

Every case so far asserted that no sandbox specialist was called, because a real
delegation runs one in Cloud Run and can open a pull request. Positive routing
was tested through the Connector Agent alone. With delegation recorded and
stopped under eval (a2a_client_ops), a brief that plainly belongs to one
specialist can now assert that specialist was chosen — and that no other was.

Four briefs, one per sandbox specialist. Each is written so the right route is
the only defensible reading: the work names its own surface.

The work item is titled the way its reporter would have titled it, never after
the route the case tests. The title is part of the brief the map builds, so a
title like "A server-side rule change" hands the model the answer before it
reaches the description the decision is supposed to come from. The case keeps the
route in ITS title, where only a person reading the suite sees it, and its prompt
field carries a one-line summary of the brief — that field is never sent on this
path, it is the line shown beside the verdict on a run.

Idempotent — cases are matched by title and their fixtures reused.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0 import agent_baselines_cover_more as more
from one_bpmn.one_bpmn.patches.v1_0 import orchestrator_agent_baseline_covers_every_tool as orchestrator

DELEGATES = more.DELEGATE_TOOLS.split(",")


def _others(chosen: str) -> str:
	return ",".join(t for t in DELEGATES if t != chosen)


def _route(
	key: str,
	tool: str,
	kind: str,
	title: str,
	item_title: str,
	summary: str,
	description: str,
	target_app: str,
) -> dict:
	"""One brief whose only defensible route is ``tool``.

	``title`` names the case, ``item_title`` is what a reporter would have called
	the work, and ``summary`` is the one line a reader of a run sees. They are
	three different jobs and were one string: the case was titled for the route
	it tests, and that title went onto the work item, so the first thing the
	model read was "A server-side rule change" — the answer, handed over before
	the brief it is supposed to be drawn from.

	target_app and git_branch are set because the orchestrator refuses to delegate
	without them — it hands the item back asking for the repository and branch,
	which is correct behaviour and exactly what the first run of these cases
	caught. A routing case has to clear that bar before it can test routing.
	"""
	return {
		"key": key,
		"title": title,
		"summary": summary,
		"case_type": "Trajectory",
		"work_item": orchestrator._item(
			kind, item_title, description,
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
		"Refuse a leave application that starts before the employee joined",
		"Leave Application accepts leave starting before the employee's date of joining. Add a server-side validation in the one_fm app that refuses it on save and names both dates. No screen changes.",
		"<p>Leave Application currently lets an employee apply for leave that starts before their date of "
		"joining. Add a validation in the one_fm app so a Leave Application whose from_date is earlier than "
		"the employee's date_of_joining is refused on save, with a message naming both dates.</p>"
		"<p>Server-side Python only; no screen changes.</p>",
		"one_fm",
	),
	_route(
		"route_frontend", "delegate_frontend_agent", "User Story",
		"A screen-only change goes to the Frontend Agent",
		"Move the Deploy button next to Save in the Processa editor",
		"Users miss the Deploy button at the far right of the Processa editor toolbar. Move it beside Save and give it the primary colour. One Vue component in the spiff app; the deploy endpoint is untouched.",
		"<p>On the Processa editor, the Deploy button sits at the far right of the toolbar and users miss it. "
		"Move it next to Save and give it the primary colour. No backend change: the deploy endpoint and "
		"its behaviour stay exactly as they are.</p>"
		"<p>Vue in the spiff app, one component.</p>",
		"one_bpmn",
	),
	_route(
		"route_mobile", "delegate_mobile_app_agent", "User Story",
		"A change to the Ionic app goes to the Mobile App Agent",
		"Show the check-in time in 12-hour local time",
		"The check-in screen of the Ionic mobile app prints a raw ISO timestamp. Show it as local time in 12-hour format. The change is in the mobile app repository; nothing on the Frappe side moves.",
		"<p>In the ONE FM mobile app, the check-in screen shows the raw ISO timestamp under the button. Show "
		"it as a local time in 12-hour format instead. This is the Ionic app in the mobile_app_ionic "
		"repository; nothing on the Frappe side changes.</p>",
		"mobile_app_ionic",
	),
	_route(
		"route_bug", "delegate_bug_agent", "Bug",
		"A reproducible defect with a traceback goes to the Bug Agent",
		"Saving an Employee with no Department raises AttributeError",
		"Saving an Employee with an empty Department raises AttributeError in the one_fm Employee override instead of the ordinary mandatory-field message. Reproduces every time on staging.",
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
		more._write(existing, baseline, spec, orchestrator.MAP, orchestrator.SHAPE, spec["summary"],
		            {"context_doctype": "Work Item", "context_docname": item})
	frappe.db.commit()
