"""Give Docu's baseline suite real design turns, drawn from what people asked it on BA.

Each case checks the tool trace and reads the DocType definition the turn proposed, which the
runner appends after the reply. The greeting cases already in the suite are left as they are.
Idempotent by suite and case title.
"""

import json

import frappe

from one_bpmn.one_bpmn.patches.v1_0.seed_lucrusher_eval_suite import _call

AGENT_ID = "docu_agent"
SHAPE = "run_docu_agent"
SUITE_TITLE = "Docu Agent - Baseline"
JUDGE_PROVIDER = "Anthropic"
JUDGE_MODEL = "claude-sonnet-4-5-20250929"

SUITE_DESCRIPTION = (
	"Docu through real turns: a greeting is answered as a greeting, a new DocType is designed with "
	"the fields, options, child table, naming and roles asked for, a change to an existing DocType "
	"keeps the rest of it, and a vague or off-topic message designs nothing."
)

DESIGN_TRACE = [
	_call(1, "classify_intent"),
	_call(2, "write_schema"),
	_call(3, "review_schema"),
	_call(4, "finalize"),
]
# clarify writes the reply and marks the turn done, so a finalize after it is optional.
CLARIFY_TRACE = [_call(1, "classify_intent"), _call(2, "clarify")]
ON_TODO = {"doctype": "ToDo"}


def _judge(rubric):
	return {
		"assertion_type": "llm_judge",
		"value": rubric,
		"judge_provider": JUDGE_PROVIDER,
		"judge_model": JUDGE_MODEL,
		"pass_threshold": 4,
	}


def _regex(pattern):
	return {"assertion_type": "regex", "value": pattern}


IN_ORDER = {"assertion_type": "tool_calls", "value": "IN_ORDER"}
DESIGNS_NOTHING = {"assertion_type": "no_tool_call", "value": "write_schema, review_schema"}

CASES = [
	{
		"title": "A numbering pattern asked for becomes a naming rule that produces it",
		"prompt": (
			"A record for a safety incident with the location, the date, a description and the "
			"severity. Number them INC-00001, INC-00002 and so on."
		),
		"trace": DESIGN_TRACE,
		"assertions": [
			IN_ORDER,
			# "format:INC-.#####" names every record literally "INC-.#####", so it is not accepted.
			_regex(r'"autoname": "(INC-\.#####|format:INC-\{#####\})"'),
			_judge(
				"The DocType definition after the reply has a field for each of: the location, the "
				"date, a description and the severity. Score 5 when all four are present, 1 when any is missing."
			),
			{"assertion_type": "max_tokens", "value": "30000"},
		],
	},
	{
		"title": "A choice with exactly three levels offers exactly those three",
		"prompt": (
			"Create a DocType for gate pass inspections: the date, the inspector, who is an employee, "
			"and a severity with exactly three levels: Minor, Major and Critical."
		),
		"trace": DESIGN_TRACE,
		"assertions": [
			IN_ORDER,
			_regex(r'"options": "Minor\\nMajor\\nCritical"'),
			_regex(r'"options": "Employee"'),
		],
	},
	{
		"title": "A list of parts with a quantity each becomes a child table",
		"prompt": (
			"Create a new DocType for a vehicle service visit: the vehicle, the date, the mechanic, and "
			"a list of the parts used with the quantity of each"
		),
		"trace": DESIGN_TRACE,
		"assertions": [
			IN_ORDER,
			_regex(r'"fieldtype": "Table"'),
			_judge(
				"In the DocType definition after the reply, the parts used are a Table field whose child "
				"fields include the part and a numeric quantity. Score 5 when they are, 1 when the parts "
				"are a text field or the quantity is missing."
			),
		],
	},
	{
		"title": "Who may raise and edit a record is set in its permissions",
		"prompt": "Create a Site Visit Log with a date and notes, and let HR Manager raise and edit them",
		"trace": DESIGN_TRACE,
		"assertions": [
			IN_ORDER,
			_regex(r'"role": "HR Manager"'),
			_judge(
				"In the DocType definition after the reply, the HR Manager permission row allows create "
				"and write. Score 5 when it does, 1 when HR Manager is missing or cannot create or write."
			),
		],
	},
	{
		"title": "A field added to an existing DocType lands where asked and the rest is kept",
		"prompt": "Add a Reviewed By field, a link to Employee, right after the Description field.",
		"context": ON_TODO,
		"trace": DESIGN_TRACE,
		"assertions": [
			IN_ORDER,
			_regex(r'"fieldname": "reviewed_by"'),
			_regex(r'"fieldname": "allocated_to"'),
			_judge(
				"The definition after the reply is the ToDo DocType with a new Reviewed By field that links "
				"to Employee and comes directly after the description field; the existing fields are still "
				"there. Score 5 when all of that holds, 1 when the field is missing, links elsewhere, or "
				"existing fields were dropped."
			),
		],
	},
	{
		"title": "A field shown only for some values gets a display condition on those values",
		"prompt": "Make the Assigned By field only show when the Status is neither Cancelled nor Closed.",
		"context": ON_TODO,
		"trace": DESIGN_TRACE,
		"assertions": [
			IN_ORDER,
			_regex(r'"depends_on": "eval:.*Cancelled'),
			_regex(r'"depends_on": "eval:.*Closed'),
			_judge(
				"In the definition after the reply, the assigned_by field has a depends_on that hides it "
				"when status is Cancelled or Closed and shows it otherwise. Score 5 when the condition is "
				"right, 1 when it is missing, on another field, or inverted."
			),
		],
	},
	{
		"title": "A role that does not exist is reported, not added",
		"prompt": "Give the Keeper Of The Seal role access to this DocType.",
		"context": ON_TODO,
		"assertions": [
			_judge(
				"There is no role called Keeper Of The Seal. The reply says so and the definition after it "
				"grants that role nothing. Score 5 when both hold, 1 when the reply claims to have added "
				"it or a permission row names it."
			),
		],
	},
	{
		"title": "A request too vague to design from gets one question and no design",
		"prompt": "I need a form for my team.",
		"trace": CLARIFY_TRACE,
		"assertions": [IN_ORDER, DESIGNS_NOTHING],
	},
	{
		"title": "A question that is not about designing a DocType designs nothing",
		"prompt": "what DSOT Approval status does",
		"assertions": [
			{"assertion_type": "no_tool_call", "value": "write_schema, review_schema, clarify"},
			{"assertion_type": "max_tokens", "value": "5000"},
		],
	},
]


def execute():
	agent, process_model = frappe.db.get_value(
		"AI Agent Configuration", {"agent_id": AGENT_ID}, ["name", "process_model"]
	) or (None, None)
	if not agent or not process_model:
		return

	suite = _suite(agent, process_model)
	for spec in CASES:
		existing = frappe.db.get_value("AI Eval Case", {"suite": suite, "title": spec["title"]}, "name")
		case = frappe.get_doc("AI Eval Case", existing) if existing else frappe.new_doc("AI Eval Case")
		case.suite = suite
		case.title = spec["title"]
		case.case_type = "Trajectory" if spec.get("trace") else "Output"
		case.process_model = process_model
		case.bpmn_id = SHAPE
		case.input_user_prompt = spec["prompt"]
		case.input_context = json.dumps(spec["context"]) if spec.get("context") else None
		case.set("assertions", spec["assertions"])
		case.set("expected_tool_calls", spec.get("trace") or [])
		if existing:
			case.save(ignore_permissions=True)
		else:
			case.insert(ignore_permissions=True)


def _suite(agent: str, process_model: str) -> str:
	values = {
		"eval_type": "Agent",
		"process_model": process_model,
		"agent_configuration": agent,
		"description": SUITE_DESCRIPTION,
	}
	existing = frappe.db.get_value(
		"AI Eval Suite", {"agent_configuration": agent, "suite_type": "Baseline"}, "name"
	)
	if existing:
		frappe.db.set_value("AI Eval Suite", existing, values)
		return existing
	return frappe.get_doc(
		{"doctype": "AI Eval Suite", "title": SUITE_TITLE, "suite_type": "Baseline", **values}
	).insert(ignore_permissions=True).name
