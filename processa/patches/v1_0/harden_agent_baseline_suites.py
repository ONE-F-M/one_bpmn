# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Make the Orchestrator and Connector baselines into gates, and watch them live.

Both suites were reporting rather than deciding: ``min_pass_rate`` 0 means a
suite cannot fail, so a run at 67% read as red on the row and blocked nothing.
They now declare a bar and enforce it — activating either map is refused while
its latest run is below 75%.

Four smaller repairs travel with it:

* **A case can say nothing came back.** An empty answer used to surface as
  whichever assertion happened to fail first — a live run of the Orchestrator
  reported "no call to wi_hand_back" when the real event was that the agent
  produced nothing at all. Every case now carries a cheap guard so the two
  are told apart.
* **The tool-path case is typed as one.** It asserts a trajectory and was
  filed as Output, which is what the readiness breakdown and skill graduation
  read.
* **The Connector judge is told the answer is JSON.** It grades a JSON object
  against a rubric written for prose, and marked a correct answer down.
* **Both agents get an Online Rubric**, so production sampling stops passing
  over the two agents whose mistakes cost the most.

``ci_role`` is deliberately untouched: whether these run unattended overnight
is a separate decision from whether they are allowed to fail.
"""

import frappe

MIN_PASS_RATE = 75.0
PASS_K = 2

# Any non-whitespace character. An answer that is empty or blank fails this and
# nothing else, so "the agent said nothing" never reads as a wrong decision.
ANSWERED_AT_ALL = r"\S"

BASELINES = ("Orchestrator Agent — Baseline", "Connector Agent — Baseline")

TRAJECTORY_CASE = "The hand-back is an action, not a sentence in the report"

# Prepended to the Connector judge so it grades what the agent actually returns.
JSON_NOTE = (
	"The answer you are grading is a JSON object, not prose. Read its fields: "
	"a connector left disabled shows \"enabled\": false, and the operations it "
	"covers are listed under \"operations\".\n\n"
)

RUBRICS = {
	"Orchestrator Agent": {
		"title": "Orchestrator Agent — Online Rubric",
		"rules": [
			ANSWERED_AT_ALL,
			# A brief that never rendered reaches the agent as its own template.
			r"(?i)^(?![\s\S]*(?:traceback \(most recent call last\)|frappe\.exceptions|\bTODO\b|\bFIXME\b|\{\{\s*\w+\s*\}\}))[\s\S]*$",
			# Done belongs to a person; the Orchestrator may not award it.
			r"(?i)^(?![\s\S]*\b(?:marked (?:it |this )?(?:as )?done|set (?:it |the item )?to done|moved (?:it |this )?to done|status is now done)\b)[\s\S]*$",
		],
	},
	"Connector Agent": {
		"title": "Connector Agent — Online Rubric",
		"rules": [
			ANSWERED_AT_ALL,
			r"(?i)^(?![\s\S]*(?:traceback \(most recent call last\)|frappe\.exceptions|\bTODO\b|\bFIXME\b|\{\{\s*\w+\s*\}\}))[\s\S]*$",
			# A connector ships disabled. Saying otherwise is the failure the
			# baseline suite tests for, and it happens in production.
			r"(?i)^(?![\s\S]*\b(?:now enabled|ready to use|already enabled|is enabled and)\b)[\s\S]*$",
		],
	},
}

RUBRIC_DESCRIPTION = (
	"Standards every answer from this agent should meet, applied to sampled production "
	"conversations. Text checks only — nothing here bills."
)


def _harden(title: str) -> str | None:
	name = frappe.db.get_value("AI Eval Suite", {"title": title}, "name")
	if not name:
		return None
	frappe.db.set_value("AI Eval Suite", name, {
		"min_pass_rate": MIN_PASS_RATE,
		"pass_k": PASS_K,
		"gate_deployment": 1,
	})
	return name


def _guard_cases(suite: str) -> int:
	added = 0
	for case_name in frappe.get_all("AI Eval Case", filters={"suite": suite}, pluck="name"):
		case = frappe.get_doc("AI Eval Case", case_name)
		if any(a.assertion_type == "regex" and a.value == ANSWERED_AT_ALL for a in case.assertions):
			continue
		case.append("assertions", {"assertion_type": "regex", "value": ANSWERED_AT_ALL})
		case.save(ignore_permissions=True)
		added += 1
	return added


def _retype_trajectory(suite: str) -> bool:
	name = frappe.db.get_value("AI Eval Case", {"suite": suite, "title": TRAJECTORY_CASE}, "name")
	if not name or frappe.db.get_value("AI Eval Case", name, "case_type") == "Trajectory":
		return False
	frappe.db.set_value("AI Eval Case", name, "case_type", "Trajectory")
	return True


def _tell_judge_it_is_json(suite: str) -> int:
	touched = 0
	for case_name in frappe.get_all("AI Eval Case", filters={"suite": suite}, pluck="name"):
		case = frappe.get_doc("AI Eval Case", case_name)
		changed = False
		for a in case.assertions:
			if a.assertion_type == "llm_judge" and a.value and not a.value.startswith(JSON_NOTE):
				a.value = JSON_NOTE + a.value
				changed = True
		if changed:
			case.save(ignore_permissions=True)
			touched += 1
	return touched


def _rubric(agent: str, spec: dict) -> str | None:
	if not frappe.db.exists("AI Agent Configuration", agent):
		return None

	name = frappe.db.get_value("AI Eval Suite", {"title": spec["title"]}, "name")
	if name:
		suite = frappe.get_doc("AI Eval Suite", name)
	else:
		suite = frappe.new_doc("AI Eval Suite")
		suite.title = spec["title"]
	suite.update({
		"eval_type": "Direct",
		"suite_type": "Online Rubric",
		"agent_configuration": agent,
		"pass_k": 1,
		"min_pass_rate": 0,
		"gate_deployment": 0,
		"description": RUBRIC_DESCRIPTION,
	})
	suite.save(ignore_permissions=True) if name else suite.insert(ignore_permissions=True)

	case_name = frappe.db.get_value("AI Eval Case", {"suite": suite.name, "title": "Rubric"}, "name")
	case = frappe.get_doc("AI Eval Case", case_name) if case_name else frappe.new_doc("AI Eval Case")
	case.suite = suite.name
	case.title = "Rubric"
	case.case_type = "Output"
	case.input_user_prompt = "Not sent anywhere — this case exists to hold the standards."
	case.set("assertions", [{"assertion_type": "regex", "value": r} for r in spec["rules"]])
	case.save(ignore_permissions=True) if case_name else case.insert(ignore_permissions=True)
	return suite.name


def execute():
	for title in BASELINES:
		suite = _harden(title)
		if not suite:
			continue
		_guard_cases(suite)
		if title.startswith("Orchestrator"):
			_retype_trajectory(suite)
		if title.startswith("Connector"):
			_tell_judge_it_is_json(suite)

	for agent, spec in RUBRICS.items():
		_rubric(agent, spec)

	frappe.db.commit()
