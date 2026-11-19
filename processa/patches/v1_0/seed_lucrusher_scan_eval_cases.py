"""LuCrusher Baseline gains three codebase scan cases: a small process, an HD Ticket false match, and steps naming a DocType that does not exist.

A module of its own, so running it seeds only these cases and leaves the suite and the older cases as they are.
"""

from processa.patches.v1_0.seed_lucrusher_eval_suite import IN_ORDER, _call, _judge
from processa.patches.v1_0.seed_lucrusher_skill_eval_cases import seed_cases


def _scan_case(title, steps, rubric, extra=()):
	return {
		"title": title,
		"prompt": "I have no Lucidchart for this one. Scan the codebase for these steps: " + ", ".join(steps),
		"context": {},
		"calls": [
			_call(1, "scan_codebase_for_process"),
			_call(2, "finalize", "intent", "equals", "CODEBASE_SCAN_RESULT"),
		],
		"assertions": [IN_ORDER, *extra, _judge(rubric)],
		"skill": None,
	}


SCAN_CASES = [
	_scan_case(
		"A two-step leave process is matched to a short, explained DocType list",
		["Submit Leave Application", "Approve Leave Application"],
		"The reply lists Leave Application as a matched DocType, says how many DocTypes matched out of how "
		"many, and gives a reason or the matching words for each one. Score 5 when the list is short (under "
		"ten) and explained, 1 when it reports dozens of DocTypes or none.",
	),
	_scan_case(
		"A uniform ticket step does not pull in the HD Ticket family",
		["Raise Uniform Ticket", "Issue Uniform", "Return Uniform"],
		"The reply does not present any Helpdesk DocType (HD Ticket, HD Ticket Type, HD Ticket Template) as "
		"part of the uniform process. Score 5 when no HD Ticket DocType is listed as a match, 1 when one is.",
		extra=({"assertion_type": "regex", "value": r"^(?![\s\S]*HD Ticket)"},),
	),
	_scan_case(
		"Steps naming a DocType that does not exist get a reasoned zero",
		["Approve Quantum Teleport Permit", "Archive Quantum Teleport Permit"],
		"The reply says no DocType matched, explains why, and suggests what to check. It never presents a "
		"Quantum Teleport Permit DocType as existing. Score 5 when all three hold, 1 when it lists a made-up "
		"DocType or gives a bare zero.",
	),
]


def execute():
	seed_cases(SCAN_CASES)
