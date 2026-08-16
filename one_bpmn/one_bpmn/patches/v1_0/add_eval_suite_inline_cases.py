"""
WI-001751 follow-up: let create_eval_suite write its cases in the same call.

Symptom: asked to add evals for an agent, the assistant called list_eval_suites,
called create_eval_suite — which committed a real suite — and then replied "Now
I'll add three test cases:" without calling create_eval_case at all. Asked
again, it repeated the announcement, then created a SECOND suite. Both suites
survived with zero cases. Every run reported Success; nothing errored.

Cause: authoring a suite was a multi-step tool sequence — list, create suite,
then one create_eval_case per case, each depending on the returned suite name.
The assistant runs a small model (claude-haiku-4-5), and it reliably performs
the first write and then narrates the remainder as prose instead of continuing
to call tools. fix_assistant_response_contract removed the schema crash that
used to kill these turns, but the early stop is behaviour, not an error, so
nothing catches it: the turn ends "successfully" with the work half done.

Prompt rules do not hold here. The section already tells the model to create the
cases after the suite, and it does not.

Fix: collapse the common path into ONE call. create_eval_suite gains an optional
``cases`` array — each entry the same shape create_eval_case takes — and writes
the suite and every case before returning. A single tool call now produces a
complete, usable suite, so the model has nothing left to forget. create_eval_case
is untouched and still the way to add cases to an EXISTING suite.

Cases are written after the suite exists, and a failure on one case is reported
per-case rather than lost: a suite with 2 of 3 cases plus a named failure is
recoverable, a silent partial write is not.

Diagrams are data, never code (WI-001540), so the shape and the prompt are
repaired on the site's own copy. Idempotent: the script body and the shape
element are compared before writing, and the prompt section is replaced in place.
"""

import re

import frappe

MODEL_NAME = "AI Agent Assistant — Chat"
AGENT_ID = "ai_agent_assistant"
SHAPE_ID = "create_eval_suite"
CREATE_SUITE_SCRIPT_NAME = "Assistant Tool – Create Eval Suite"


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Server Script — suite + cases in one pass
# ═══════════════════════════════════════════════════════════════════════════════

CREATE_EVAL_SUITE_SCRIPT = '''# Tool: create an eval suite bound to an AI Agent Configuration, optionally
# writing its cases in the same call.
# agent_configuration is mandatory on AI Eval Suite and the link exists only on
# the suite, so the agent must be supplied explicitly - it cannot be inferred.
_agent = (task_data.get("agent") or "").strip()
_title = (task_data.get("title") or "").strip()
_description = (task_data.get("description") or "").strip()
_eval_type = (task_data.get("eval_type") or "Direct").strip()
_process_model = (task_data.get("process_model") or "").strip()
_cases = task_data.get("cases") or []

_VALID_ASSERTIONS = ("contains", "regex", "equals", "schema_valid", "llm_judge")

if not _agent:
    result["error"] = "No agent given - pass the exact AI Agent Configuration record name."
elif not frappe.db.exists("AI Agent Configuration", _agent):
    result["error"] = "Unknown AI Agent Configuration: " + _agent
elif not _title:
    result["error"] = "No title given - a suite needs a title."
elif _eval_type not in ("Direct", "Agent"):
    result["error"] = "eval_type must be 'Direct' or 'Agent', got: " + _eval_type
elif not isinstance(_cases, list):
    result["error"] = "cases must be a list of case objects."
else:
    from one_bpmn.api.eval_api import create_eval_case, create_suite

    try:
        _name = create_suite(
            title=_title,
            process_model=_process_model or None,
            agent_configuration=_agent,
            eval_type=_eval_type,
            description=_description,
        )
        # Only keys that are NOT argument names survive execute_shape, which
        # strips the arguments it injected — so echoing title/eval_type here
        # would be dropped. The suite name is what any follow-up call needs.
        result["suite"] = _name
    except Exception as _exc:
        result["error"] = "Could not create the suite: " + str(_exc)
        _cases = []
        _name = None

    # Cases are written only once the suite exists. Each is reported
    # individually: a partial write the model can see and repair beats a
    # silent one it cannot.
    _made = []
    _failed = []
    _no_assertions = []
    for _c in _cases if _name else []:
        if not isinstance(_c, dict):
            _failed.append("(case was not an object)")
            continue
        _ctitle = (_c.get("title") or "").strip()
        _cprompt = (_c.get("input_user_prompt") or "").strip()
        if not _ctitle or not _cprompt:
            _failed.append((_ctitle or "(untitled)") + ": needs a title and an input_user_prompt")
            continue

        _clean = []
        for _a in _c.get("assertions") or []:
            if not isinstance(_a, dict):
                continue
            _type = (_a.get("assertion_type") or "").strip()
            if _type not in _VALID_ASSERTIONS:
                continue
            _row = {"assertion_type": _type, "value": _a.get("value") or ""}
            for _k in ("judge_provider", "judge_model", "pass_threshold"):
                if _a.get(_k) not in (None, ""):
                    _row[_k] = _a[_k]
            _clean.append(_row)
        if not _clean:
            _no_assertions.append(_ctitle)

        try:
            create_eval_case(
                suite=_name,
                title=_ctitle,
                input_user_prompt=_cprompt,
                expected_output=(_c.get("expected_output") or "").strip(),
                assertions=_clean,
            )
            _made.append(_ctitle)
        except Exception as _exc:
            _failed.append(_ctitle + ": " + str(_exc))

    if _name:
        result["cases_created"] = len(_made)
        if _made:
            result["case_titles"] = _made
        if _failed:
            result["cases_failed"] = _failed
        if _no_assertions:
            result["cases_without_assertions"] = _no_assertions
            result["warning"] = (
                "These cases have no assertions and will pass trivially: "
                + ", ".join(_no_assertions)
            )
'''


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Diagram: the shape's argument schema
# ═══════════════════════════════════════════════════════════════════════════════

_CASE_ITEM_SCHEMA = {
	"type": "object",
	"properties": {
		"title": {"type": "string", "description": "Short title naming what this case checks."},
		"input_user_prompt": {
			"type": "string",
			"description": "The prompt sent to the agent for this case.",
		},
		"expected_output": {
			"type": "string",
			"description": "Optional. What a correct reply looks like.",
		},
		"assertions": {
			"type": "array",
			"description": (
				"What decides pass or fail. Give at least one — a case with none passes "
				"trivially. Use contains / regex / equals / schema_valid for exact checks and "
				"llm_judge (with judge_provider, judge_model and pass_threshold) when "
				"correctness is a matter of judgement."
			),
			"items": {
				"type": "object",
				"properties": {
					"assertion_type": {
						"type": "string",
						"enum": ["contains", "regex", "equals", "schema_valid", "llm_judge"],
					},
					"value": {"type": "string"},
					"judge_provider": {"type": "string"},
					"judge_model": {"type": "string"},
					"pass_threshold": {"type": "number"},
				},
				"required": ["assertion_type"],
			},
		},
	},
	"required": ["title", "input_user_prompt"],
}

_TOOL_SHAPE = {
	"id": SHAPE_ID,
	"name": "Create Eval Suite",
	"script": CREATE_SUITE_SCRIPT_NAME,
	"documentation": (
		"Create a new eval suite bound to an AI Agent Configuration, and write its cases in "
		"the same call by passing 'cases'. Call only after list_eval_suites shows no existing "
		"suite covering the use case. This is the ONE call that produces a complete suite — "
		"do not create an empty suite and describe the cases you would add. Returns the suite "
		"name and how many cases were created."
	),
	"params": {
		"properties": {
			"agent": {
				"type": "string",
				"description": "Exact AI Agent Configuration record name the suite tests.",
			},
			"title": {"type": "string", "description": "Short title naming what the suite covers."},
			"description": {
				"type": "string",
				"description": "What this suite covers, so it can be told apart from the agent's other suites.",
			},
			"eval_type": {
				"type": "string",
				"enum": ["Direct", "Agent"],
				"description": (
					"Direct evaluates the agent's prompt and credentials with a simple LLM "
					"call; Agent invokes the agent's full execution path including its tools "
					"and process map. Default Direct."
				),
			},
			"process_model": {
				"type": "string",
				"description": "Optional BPMN Process Model to scope the suite to; omit for a Direct suite.",
			},
			"cases": {
				"type": "array",
				"description": (
					"The suite's cases, written in this same call. Pass every case you have "
					"agreed with the designer — this is how a suite is populated."
				),
				"items": _CASE_ITEM_SCHEMA,
			},
		},
		"required": ["agent", "title"],
	},
}


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Prompt: the ordering rules that assumed a multi-step sequence
# ═══════════════════════════════════════════════════════════════════════════════
# Only the lines describing HOW the tools are sequenced are rewritten. The rules
# about recognising an eval request, proposing cases, and building on what the
# designer said are unchanged and are matched verbatim so they stay put.
_STALE_LINES = {
	(
		"  - Only when no suite fits, call create_eval_suite (the agent's record name and a "
		"title are required), then create_eval_case for each case using the returned suite name."
	): (
		"  - Only when no suite fits, call create_eval_suite ONCE, passing the agent's record "
		"name, a title, and every agreed case in its 'cases' argument. One call creates the "
		"suite and all of its cases. Never create a suite and then describe the cases you "
		"would add — a suite with no cases is useless."
	),
	(
		"  - Once the cases are agreed, build them with the tools in this order."
	): (
		"  - Once the cases are agreed, build them with the tools in this order, in the SAME "
		"turn — do not announce what you are about to do and stop."
	),
}


def _escape_attr(value: str) -> str:
	return (
		value.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
		.replace('"', "&#34;")
	)


def _shape_element(shape: dict) -> str:
	params = _escape_attr(frappe.as_json(shape["params"], indent=None))
	return (
		f'<bpmn:scriptTask id="{shape["id"]}" name="{shape["name"]}" '
		f'spiffworkflow:serverScript="{shape["script"]}" '
		f'spiffworkflow:scriptType="Server Script" '
		f'spiffworkflow:scriptName="{shape["script"]}" '
		f'spiffworkflow:aiToolParams="{params}">\n'
		f'        <bpmn:documentation>{_escape_attr(shape["documentation"])}</bpmn:documentation>\n'
		f'        <bpmn:script>{shape["script"]}</bpmn:script>\n'
		f"      </bpmn:scriptTask>"
	)


def _ensure_script() -> None:
	"""Refresh the tool's Server Script body in place."""
	if not frappe.db.exists("Server Script", CREATE_SUITE_SCRIPT_NAME):
		frappe.log_error(
			title="add_eval_suite_inline_cases: create-suite script missing",
			message=f"No Server Script '{CREATE_SUITE_SCRIPT_NAME}'; run "
			"add_assistant_eval_authoring_tools first.",
		)
		return
	doc = frappe.get_doc("Server Script", CREATE_SUITE_SCRIPT_NAME)
	if (doc.script or "").strip() != CREATE_EVAL_SUITE_SCRIPT.strip():
		doc.script = CREATE_EVAL_SUITE_SCRIPT
		doc.save(ignore_permissions=True)


def _update_process_model() -> None:
	"""Swap the shape element so the LLM sees the 'cases' argument."""
	if not frappe.db.exists("BPMN Process Model", MODEL_NAME):
		frappe.log_error(
			title="add_eval_suite_inline_cases: assistant map missing",
			message=f"No BPMN Process Model '{MODEL_NAME}' on this site; the script was "
			"refreshed but the shape's argument schema was not.",
		)
		return

	xml = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "bpmn_xml") or ""
	found = re.search(rf'<bpmn:scriptTask id="{SHAPE_ID}".*?</bpmn:scriptTask>', xml, re.S)
	if not found:
		frappe.log_error(
			title="add_eval_suite_inline_cases: shape not found",
			message=f"'{MODEL_NAME}' has no '{SHAPE_ID}' script task; run "
			"add_assistant_eval_authoring_tools first.",
		)
		return

	element = _shape_element(_TOOL_SHAPE)
	if found.group(0) == element:
		return  # already current

	xml = xml[: found.start()] + element + xml[found.end() :]
	# db_set skips the editability gate — a trusted content migration, the same
	# rationale as compile_process_model's skip_editability_check.
	frappe.db.set_value("BPMN Process Model", MODEL_NAME, "bpmn_xml", xml)

	from one_bpmn.api.compilation import compile_process_model

	try:
		compile_process_model(MODEL_NAME)
	except Exception:
		frappe.log_error(
			title="add_eval_suite_inline_cases: recompile failed",
			message=frappe.get_traceback(),
		)


def _steer_prompt() -> None:
	"""Rewrite the sequencing lines that described the old multi-step path."""
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name:
		return
	prompt = frappe.db.get_value("AI Agent Configuration", name, "system_prompt") or ""
	updated = prompt
	for stale, fixed in _STALE_LINES.items():
		updated = updated.replace(stale, fixed)
	if updated == prompt:
		return
	frappe.db.set_value(
		"AI Agent Configuration", name, "system_prompt", updated, update_modified=False
	)
	frappe.cache.delete_value(f"agent_config:{AGENT_ID}")


def execute():
	_ensure_script()
	_update_process_model()
	_steer_prompt()
	frappe.db.commit()
