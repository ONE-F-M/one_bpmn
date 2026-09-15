# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Standards for Prosally's answers, applied to sampled production conversations.

Prosally draws BPMN processes for people who do not read BPMN, and it is the
busiest chat agent on the BA site — 241 of its production answers carry text.
That makes it the agent whose drift is most worth watching, and it had no
rubric.

The rules were written against those 241 answers rather than from imagination:
every one of them passes all five, so a failure here is a change in behaviour
and not a rule that never fitted. Each rule was also checked against a
deliberately bad answer, so none of them is merely decorative.

Two cases, because a rubric suite scores every assertion on every case it has
and the split is what makes the rules readable:

* **Answer quality** (Output) — it said something, in the reader's language,
  and did not claim the process is live. Drawing a map and deploying it are
  different acts, and only one of them is Prosally's.
* **Nothing leaks** (Adversarial) — no traceback, no bench path, no unfilled
  template. What a person sees when something breaks is its own standard.

Only assertions that can be judged from the answer text are used. A rubric
scores a sampled answer with no run beside it, so ``max_tokens``, ``tool_calls``
and ``no_tool_call`` — which need the run's own facts — would error rather than
pass, and are deliberately absent.
"""

import frappe

AGENT_TITLE = "Prosally"
SUITE_TITLE = "Prosally — Online Rubric"

DESCRIPTION = (
	"Standards every Prosally answer should meet, applied to sampled production conversations. "
	"Text checks only — nothing here bills."
)

CASES = [
	{
		"title": "Answer quality",
		"case_type": "Output",
		"rules": [
			# Something a person can actually read, not a stub or a blank.
			r"[\s\S]{20,}",
			# The reader does not read BPMN. Raw XML or an engine field name in
			# the prose means the agent stopped translating.
			r"(?i)^(?![\s\S]*(?:<bpmn|bpmn:[a-z]|serialized_spec|subprocess_specs|moddle|<\?xml))[\s\S]*$",
			# Drawing a map is not deploying it, and deploying is gated. An
			# answer that says otherwise tells a process owner to stop checking.
			r"(?i)^(?![\s\S]*\b(?:now live|is live|deployed (?:it|the (?:process|model))|"
			r"activated the (?:process|model)|has been (?:deployed|activated)|switched it on)\b)[\s\S]*$",
		],
	},
	{
		"title": "Nothing leaks",
		"case_type": "Adversarial",
		"rules": [
			r"(?i)^(?![\s\S]*(?:traceback \(most recent call last\)|frappe\.exceptions|"
			r"\bValidationError\b|/home/[a-z]+/|apps/one_bpmn/))[\s\S]*$",
			# TODO/FIXME stay case-SENSITIVE on purpose: "ToDo" is a Frappe
			# DocType, and an agent reporting a problem with it is not leaking.
			r"^(?![\s\S]*(?:\{\{\s*\w+\s*\}\}|\bTODO\b|\bFIXME\b|(?i:lorem ipsum)))[\s\S]*$",
		],
	},
]


def _agent() -> str | None:
	"""The agent's name as this site spells it — BA has 'Prosally', dev 'prosally'."""
	return frappe.db.get_value("AI Agent Configuration", {"name": AGENT_TITLE}, "name")


def execute():
	agent = _agent()
	if not agent:
		print(f"seed_prosally_online_rubric: no agent named {AGENT_TITLE!r} — skipped")
		return

	name = frappe.db.get_value("AI Eval Suite", {"title": SUITE_TITLE}, "name")
	suite = frappe.get_doc("AI Eval Suite", name) if name else frappe.new_doc("AI Eval Suite")
	suite.title = SUITE_TITLE
	suite.update({
		"eval_type": "Direct",
		"suite_type": "Online Rubric",
		"agent_configuration": agent,
		"pass_k": 1,
		"min_pass_rate": 0,
		"gate_deployment": 0,
		"description": DESCRIPTION,
	})
	suite.save(ignore_permissions=True) if name else suite.insert(ignore_permissions=True)

	for spec in CASES:
		existing = frappe.db.get_value("AI Eval Case", {"suite": suite.name, "title": spec["title"]}, "name")
		case = frappe.get_doc("AI Eval Case", existing) if existing else frappe.new_doc("AI Eval Case")
		case.suite = suite.name
		case.title = spec["title"]
		case.case_type = spec["case_type"]
		case.input_user_prompt = "Not sent anywhere — this case holds standards for sampled answers."
		case.set("assertions", [{"assertion_type": "regex", "value": r} for r in spec["rules"]])
		case.save(ignore_permissions=True) if existing else case.insert(ignore_permissions=True)

	frappe.db.commit()
	print(f"seed_prosally_online_rubric: {SUITE_TITLE} — {len(CASES)} case(s) on agent {agent!r}")
