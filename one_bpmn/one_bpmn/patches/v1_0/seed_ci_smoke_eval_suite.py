"""Seed the suite the pull-request check runs.

A check that verifies nothing is worse than no check, so the Smoke role needs at
least one suite whose cases can be scored without calling a model. These are
that: each carries the answer it should hold to, and assertions that are string
matching and JSON validation rather than judgement.

What they defend is the scoring layer, which is the part a pull request most
often breaks: an evaluator that stops matching, an assertion type that changes
meaning, a schema check that starts accepting anything. Model drift is not in
scope here — that is what the Nightly live suites are for.

Idempotent: the suite and its cases are matched by title and brought up to date.
"""

import json

import frappe

SUITE_TITLE = "CI Smoke — assertion evaluators"
SUITE_DESCRIPTION = (
	"Runs on every pull request that touches agent code, with no model call. Each case carries the answer "
	"it should hold to, so a change to an evaluator or an assertion is caught before merge. It says nothing "
	"about whether an agent still behaves — the Nightly suites do that."
)

CASES = [
	{
		"title": "A substring is found, and case does not matter",
		"answer": "Successfully built the Frankfurter connector. It is DISABLED until someone enables it.",
		"assertions": [
			{"assertion_type": "contains", "value": "frankfurter"},
			{"assertion_type": "contains", "value": "disabled"},
		],
	},
	{
		"title": "A negative lookahead still rejects the phrase it forbids",
		"answer": "The connector was created and left disabled.",
		"assertions": [
			{
				"assertion_type": "regex",
				"value": r"(?i)^(?![\s\S]*\b(?:now enabled|ready to use)\b)[\s\S]*$",
			},
			{"assertion_type": "regex", "value": r"(?i)\bcreated\b"},
		],
	},
	{
		"title": "A JSON answer validates against its schema",
		"answer": json.dumps({"connector": "frankfurter", "enabled": False, "operations": ["getLatest"]}),
		"assertions": [
			{
				"assertion_type": "schema_valid",
				"value": json.dumps({
					"type": "object",
					"required": ["connector", "enabled", "operations"],
					"properties": {
						"connector": {"type": "string"},
						"enabled": {"type": "boolean"},
						"operations": {"type": "array", "items": {"type": "string"}},
					},
				}),
			},
			{"assertion_type": "contains", "value": "getLatest"},
		],
	},
	{
		"title": "An exact answer is compared exactly",
		"answer": "ready",
		"assertions": [{"assertion_type": "equals", "value": "ready"}],
	},
]


def _suite() -> str:
	existing = frappe.db.get_value("AI Eval Suite", {"title": SUITE_TITLE}, "name")
	if existing:
		frappe.db.set_value("AI Eval Suite", existing, {
			"eval_type": "Direct",
			"suite_type": "Baseline",
			"ci_role": "Smoke",
			"description": SUITE_DESCRIPTION,
		})
		return existing

	suite = frappe.get_doc({
		"doctype": "AI Eval Suite",
		"title": SUITE_TITLE,
		"eval_type": "Direct",
		"suite_type": "Baseline",
		"ci_role": "Smoke",
		"description": SUITE_DESCRIPTION,
	})
	# No agent: nothing here calls one. The field is mandatory for a suite a
	# person runs, and meaningless for a suite that never leaves the scoring
	# layer.
	suite.flags.ignore_mandatory = True
	return suite.insert(ignore_permissions=True).name


def execute():
	suite = _suite()

	for spec in CASES:
		existing = frappe.db.get_value("AI Eval Case", {"suite": suite, "title": spec["title"]}, "name")
		case = frappe.get_doc("AI Eval Case", existing) if existing else frappe.new_doc("AI Eval Case")
		case.suite = suite
		case.title = spec["title"]
		# The prompt is documentation here: nothing is sent anywhere. The
		# expected output IS the answer a deterministic pass scores against.
		case.input_user_prompt = spec["title"]
		case.expected_output = spec["answer"]
		case.set("assertions", [])
		for assertion in spec["assertions"]:
			case.append("assertions", assertion)
		case.flags.ignore_mandatory = True
		case.save(ignore_permissions=True) if existing else case.insert(ignore_permissions=True)

	frappe.db.commit()
