"""
WI-001751: give the AI Assistant tools that author eval suites and cases.

The assistant could already call ``add_agent_evals``, but that tool appends rows
to AI Agent Configuration.sample_prompts and regenerates the agent's single
"<agent> — Baseline" suite. It can therefore never target a named,
purpose-specific suite, and it keeps a second copy of the tests on the
configuration — while the real suite -> agent link lives on
AI Eval Suite.agent_configuration (WI-001743).

This patch adds three tools that work the other way round, straight against the
eval doctypes:

    list_eval_suites  -> the suites already pointing at an agent (a reverse
                         query on AI Eval Suite.agent_configuration; the
                         configuration itself holds no suite link), with enough
                         detail to judge whether one already covers the use case
    create_eval_suite -> a new suite bound to that agent
    create_eval_case  -> a case (with assertions) inside a chosen suite

Read first, create only when nothing matches. The prompt section added below
states that order so the assistant stops at the lookup when a suite already fits.

Diagrams are data, never code (WI-001540) — so the shapes are spliced into the
site's own copy of the assistant's map rather than shipped as a .bpmn fixture,
the same way add_logix_agent_tool_authoring does it. Idempotent throughout.
"""

import re

import frappe

MODEL_NAME = "AI Agent Assistant — Chat"
AGENT_ID = "ai_agent_assistant"
ADHOC_ID = "lumina_tools"

LIST_SCRIPT_NAME = "Assistant Tool – List Eval Suites"
CREATE_SUITE_SCRIPT_NAME = "Assistant Tool – Create Eval Suite"
CREATE_CASE_SCRIPT_NAME = "Assistant Tool – Create Eval Case"


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Server Scripts — the tool bodies
# ═══════════════════════════════════════════════════════════════════════════════
# Each runs with the CALLING USER's permissions: get_list applies the AI Eval
# Suite permission query (process owner / suite owner, per agents/eval_permissions
# .py) and the eval_api creators call check_permission themselves. No
# ignore_permissions anywhere — the assistant can only touch what the designer
# driving it could touch by hand.

LIST_EVAL_SUITES_SCRIPT = '''# Tool: the eval suites already attached to an AI Agent Configuration.
# The link lives on AI Eval Suite.agent_configuration (WI-001743), so this is a
# reverse query — the configuration carries no suite field to read.
_agent = (task_data.get("agent") or "").strip()
if not _agent:
    result["error"] = "No agent given - pass the exact AI Agent Configuration record name."
elif not frappe.db.exists("AI Agent Configuration", _agent):
    result["error"] = "Unknown AI Agent Configuration: " + _agent
else:
    _suites = frappe.get_list(
        "AI Eval Suite",
        filters={"agent_configuration": _agent},
        fields=["name", "title", "description", "eval_type", "process_model"],
        order_by="modified desc",
        limit_page_length=0,
    )
    _names = [_s["name"] for _s in _suites]
    _by_suite = {}
    if _names:
        for _c in frappe.get_list(
            "AI Eval Case",
            filters={"suite": ["in", _names]},
            fields=["suite", "title"],
            limit_page_length=0,
        ):
            _by_suite.setdefault(_c["suite"], []).append(_c["title"])
    for _s in _suites:
        _titles = _by_suite.get(_s["name"], [])
        _s["case_titles"] = _titles
        _s["case_count"] = len(_titles)
    result["suites"] = _suites
    result["count"] = len(_suites)
'''

CREATE_EVAL_SUITE_SCRIPT = '''# Tool: create an eval suite bound to an AI Agent Configuration.
# agent_configuration is mandatory on AI Eval Suite and the link exists only on
# the suite, so the agent must be supplied explicitly - it cannot be inferred.
_agent = (task_data.get("agent") or "").strip()
_title = (task_data.get("title") or "").strip()
_description = (task_data.get("description") or "").strip()
_eval_type = (task_data.get("eval_type") or "Direct").strip()
_process_model = (task_data.get("process_model") or "").strip()

if not _agent:
    result["error"] = "No agent given - pass the exact AI Agent Configuration record name."
elif not frappe.db.exists("AI Agent Configuration", _agent):
    result["error"] = "Unknown AI Agent Configuration: " + _agent
elif not _title:
    result["error"] = "No title given - a suite needs a title."
elif _eval_type not in ("Direct", "Agent"):
    result["error"] = "eval_type must be 'Direct' or 'Agent', got: " + _eval_type
else:
    from one_bpmn.api.eval_api import create_suite

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
        # would be dropped. The suite name is what the next tool call needs.
        result["suite"] = _name
    except Exception as _exc:
        result["error"] = "Could not create the suite: " + str(_exc)
'''

CREATE_EVAL_CASE_SCRIPT = '''# Tool: create an eval case (optionally with assertions) inside a suite.
_suite = (task_data.get("suite") or "").strip()
_title = (task_data.get("title") or "").strip()
_prompt = (task_data.get("input_user_prompt") or "").strip()
_expected = (task_data.get("expected_output") or "").strip()
_assertions = task_data.get("assertions") or []

if not _suite:
    result["error"] = "No suite given - create or pick a suite first."
elif not frappe.db.exists("AI Eval Suite", _suite):
    result["error"] = "Unknown AI Eval Suite: " + _suite
elif not _title:
    result["error"] = "No title given - a case needs a title."
elif not _prompt:
    result["error"] = "No input_user_prompt given - a case needs the prompt to send the agent."
else:
    _clean = []
    for _a in _assertions:
        if not isinstance(_a, dict):
            continue
        _type = (_a.get("assertion_type") or "").strip()
        if _type not in ("contains", "regex", "equals", "schema_valid", "llm_judge"):
            continue
        _row = {"assertion_type": _type, "value": _a.get("value") or ""}
        for _k in ("judge_provider", "judge_model", "pass_threshold"):
            if _a.get(_k) not in (None, ""):
                _row[_k] = _a[_k]
        _clean.append(_row)

    from one_bpmn.api.eval_api import create_eval_case

    try:
        _name = create_eval_case(
            suite=_suite,
            title=_title,
            input_user_prompt=_prompt,
            expected_output=_expected,
            assertions=_clean,
        )
        result["eval_case"] = _name
        result["assertions_added"] = len(_clean)
        if not _clean:
            result["warning"] = "Case has no assertions - it will pass trivially until one is added."
    except Exception as _exc:
        result["error"] = "Could not create the case: " + str(_exc)
'''


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Diagram: the tool shapes
# ═══════════════════════════════════════════════════════════════════════════════
# Insertion point is the ad-hoc sub-process's completionCondition, which closes
# lumina_tools — the same anchor add_logix_agent_tool_authoring uses.
_XML_TOOL_ANCHOR = "<bpmn:completionCondition"

# aiToolParams is a JSON Schema ({properties, required}) read by
# api/compilation.py::_extract_tool_shapes. Without it the LLM sees a zero-arg
# function and cannot pass anything. It is not authorable from the properties
# panel, which is why it is written here as escaped XML.
_TOOL_SHAPES = [
	{
		"id": "list_eval_suites",
		"name": "List Eval Suites",
		"script": LIST_SCRIPT_NAME,
		"documentation": (
			"List the eval suites already attached to an AI Agent Configuration, each with its "
			"description, eval type and existing case titles. ALWAYS call this before creating a "
			"suite, so an existing suite that already covers the use case is reused instead of "
			"duplicated."
		),
		"params": {
			"properties": {
				"agent": {
					"type": "string",
					"description": "Exact AI Agent Configuration record name.",
				}
			},
			"required": ["agent"],
		},
		"bounds": (750, 730),
	},
	{
		"id": "create_eval_suite",
		"name": "Create Eval Suite",
		"script": CREATE_SUITE_SCRIPT_NAME,
		"documentation": (
			"Create a new eval suite bound to an AI Agent Configuration. Call only after "
			"list_eval_suites shows no existing suite covering the use case. Returns the suite "
			"name to pass to create_eval_case."
		),
		"params": {
			"properties": {
				"agent": {
					"type": "string",
					"description": "Exact AI Agent Configuration record name the suite tests.",
				},
				"title": {
					"type": "string",
					"description": "Short title naming what the suite covers.",
				},
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
			},
			"required": ["agent", "title"],
		},
		"bounds": (910, 730),
	},
	{
		"id": "create_eval_case",
		"name": "Create Eval Case",
		"script": CREATE_CASE_SCRIPT_NAME,
		"documentation": (
			"Add one eval case to an existing suite: the prompt to send the agent, the expected "
			"output, and the assertions that decide pass or fail. A case with no assertions "
			"passes trivially, so include at least one."
		),
		"params": {
			"properties": {
				"suite": {
					"type": "string",
					"description": "AI Eval Suite record name (from list_eval_suites or create_eval_suite).",
				},
				"title": {"type": "string", "description": "Short title naming what this case checks."},
				"input_user_prompt": {
					"type": "string",
					"description": "The user prompt sent to the agent when the case runs.",
				},
				"expected_output": {
					"type": "string",
					"description": "What a correct reply looks like. Used by llm_judge assertions.",
				},
				"assertions": {
					"type": "array",
					"description": "Assertions deciding pass/fail.",
					"items": {
						"type": "object",
						"properties": {
							"assertion_type": {
								"type": "string",
								"enum": ["contains", "regex", "equals", "schema_valid", "llm_judge"],
							},
							"value": {
								"type": "string",
								"description": (
									"Expected substring / pattern / exact text / JSON Schema, or "
									"for llm_judge the behaviour the reply is scored against."
								),
							},
							"judge_provider": {
								"type": "string",
								"description": "llm_judge only: AI Provider Credentials record name.",
							},
							"judge_model": {
								"type": "string",
								"description": "llm_judge only: AI Model record name.",
							},
							"pass_threshold": {
								"type": "integer",
								"description": "llm_judge only: minimum score 1-5 to pass (default 4).",
							},
						},
						"required": ["assertion_type", "value"],
					},
				},
			},
			"required": ["suite", "title", "input_user_prompt"],
		},
		"bounds": (1070, 730),
	},
]

# add_agent_evals was applied straight to the site by WI-001623 and never got a
# BPMNShape, so it compiles as a tool but is invisible on the canvas. Give it one
# while we are here — a tool a designer cannot see is a tool nobody maintains.
_ORPHAN_DI = {"id": "add_agent_evals", "bounds": (750, 630)}


def _escape_attr(value: str) -> str:
	"""Escape a string for use inside a double-quoted XML attribute."""
	return (
		value.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
		.replace('"', "&#34;")
	)


def _shape_xml(shape: dict) -> str:
	params = _escape_attr(frappe.as_json(shape["params"], indent=None))
	return (
		f'<bpmn:scriptTask id="{shape["id"]}" name="{shape["name"]}" '
		f'spiffworkflow:serverScript="{shape["script"]}" '
		f'spiffworkflow:scriptType="Server Script" '
		f'spiffworkflow:scriptName="{shape["script"]}" '
		f'spiffworkflow:aiToolParams="{params}">\n'
		f'        <bpmn:documentation>{_escape_attr(shape["documentation"])}</bpmn:documentation>\n'
		f'        <bpmn:script>{shape["script"]}</bpmn:script>\n'
		f"      </bpmn:scriptTask>\n      "
	)


def _di_xml(shape_id: str, x: int, y: int) -> str:
	return (
		f'\n      <bpmndi:BPMNShape id="{shape_id}_di" bpmnElement="{shape_id}">\n'
		f'        <dc:Bounds x="{x}" y="{y}" width="100" height="80" />\n'
		f"      </bpmndi:BPMNShape>"
	)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Prompt steering
# ═══════════════════════════════════════════════════════════════════════════════
# Appended to the assistant configuration's system_prompt rather than added to
# api/ai_assistant.py::_build_system_prompt, deliberately: the live prompt on a
# site is richer than that builder (the YOUR TOOLBOX / CREATING AGENTS sections
# come from WI-001623, still unmerged), so regenerating from the builder would
# lose text. Appending is additive and survives whichever builder seeded it.
_PROMPT_MARKER = "AUTHORING EVAL SUITES AND CASES:"
_PROMPT_SECTION = """

AUTHORING EVAL SUITES AND CASES:
  - You can build evals for an AI Agent Configuration directly with three tools, in this order.
  - FIRST call list_eval_suites for the agent. It returns each suite's title, description, eval type and existing case titles.
  - If one of those suites already covers what the designer asked for, ADD cases to it with create_eval_case. Do not create a second suite for the same purpose.
  - Only when no suite fits, call create_eval_suite (the agent's record name and a title are required), then create_eval_case for each case using the returned suite name.
  - Give every case at least one assertion — a case with none passes trivially. Use contains / regex / equals / schema_valid for exact checks, and llm_judge (with a judge provider, judge model and pass threshold) when correctness is a matter of judgement.
  - Prefer these tools over add_agent_evals when the designer wants a named or purpose-specific suite: add_agent_evals only ever refreshes the agent's single baseline suite.
  - The suite's link to the agent lives on the suite, not on the AI Agent Configuration, so always pass the agent's exact record name when creating one."""


# ═══════════════════════════════════════════════════════════════════════════════
# Patch steps
# ═══════════════════════════════════════════════════════════════════════════════

def _ensure_script(name: str, api_method: str, body: str) -> None:
	"""Create the tool's Server Script, or refresh a stale body in place."""
	if frappe.db.exists("Server Script", name):
		doc = frappe.get_doc("Server Script", name)
		if (doc.script or "").strip() != body.strip():
			doc.script = body
			doc.save(ignore_permissions=True)
		return
	frappe.get_doc({
		"doctype": "Server Script",
		"name": name,
		"script_type": "API",
		"api_method": api_method,
		"script": body,
		"disabled": 0,
	}).insert(ignore_permissions=True)


def _ensure_scripts() -> None:
	_ensure_script(LIST_SCRIPT_NAME, "assistant_tool_list_eval_suites", LIST_EVAL_SUITES_SCRIPT)
	_ensure_script(CREATE_SUITE_SCRIPT_NAME, "assistant_tool_create_eval_suite", CREATE_EVAL_SUITE_SCRIPT)
	_ensure_script(CREATE_CASE_SCRIPT_NAME, "assistant_tool_create_eval_case", CREATE_EVAL_CASE_SCRIPT)


def _update_process_model() -> None:
	"""Splice the three tool shapes into lumina_tools, then recompile."""
	if not frappe.db.exists("BPMN Process Model", MODEL_NAME):
		frappe.log_error(
			title="add_assistant_eval_authoring_tools: assistant map missing",
			message=f"No BPMN Process Model '{MODEL_NAME}' on this site; tool scripts were "
					"created but no shapes were added. Import the assistant map and re-run.",
		)
		return

	xml = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "bpmn_xml") or ""
	pending = [s for s in _TOOL_SHAPES if f'id="{s["id"]}"' not in xml]
	needs_orphan_di = (
		f'id="{_ORPHAN_DI["id"]}"' in xml
		and f'bpmnElement="{_ORPHAN_DI["id"]}"' not in xml
	)
	if not pending and not needs_orphan_di:
		return

	# The anchor must be the one closing lumina_tools, not some other ad-hoc
	# sub-process, or the tools would land in the wrong toolbox.
	adhoc = re.search(
		rf'<bpmn:adHocSubProcess id="{ADHOC_ID}".*?</bpmn:adHocSubProcess>', xml, re.S
	)
	if not adhoc or _XML_TOOL_ANCHOR not in adhoc.group(0):
		frappe.log_error(
			title="add_assistant_eval_authoring_tools: diagram anchors not found",
			message=f"'{MODEL_NAME}' has no '{ADHOC_ID}' ad-hoc sub-process with a "
					"completionCondition; add the eval tool shapes manually.",
		)
		return

	if pending:
		block = "".join(_shape_xml(s) for s in pending)
		patched_adhoc = adhoc.group(0).replace(_XML_TOOL_ANCHOR, block + _XML_TOOL_ANCHOR, 1)
		xml = xml[: adhoc.start()] + patched_adhoc + xml[adhoc.end():]

	di_additions = [_di_xml(s["id"], *s["bounds"]) for s in pending]
	if needs_orphan_di:
		di_additions.append(_di_xml(_ORPHAN_DI["id"], *_ORPHAN_DI["bounds"]))
	if di_additions:
		plane_close = xml.rfind("</bpmndi:BPMNPlane>")
		if plane_close == -1:
			frappe.log_error(
				title="add_assistant_eval_authoring_tools: no BPMNPlane to extend",
				message=f"'{MODEL_NAME}' has no </bpmndi:BPMNPlane>; shapes added without "
						"diagram bounds and will not render on the canvas.",
			)
		else:
			xml = xml[:plane_close] + "".join(di_additions) + "\n      " + xml[plane_close:]

	# db_set skips the editability gate — a trusted content migration, same
	# rationale as compile_process_model's skip_editability_check.
	frappe.db.set_value("BPMN Process Model", MODEL_NAME, "bpmn_xml", xml)

	# Recompile so serialized_spec embeds the new tools in aiToolShapes. New
	# conversations pick them up; running instances keep their old spec.
	from one_bpmn.api.compilation import compile_process_model

	try:
		compile_process_model(MODEL_NAME)
	except Exception:
		frappe.log_error(
			title="add_assistant_eval_authoring_tools: recompile failed",
			message=frappe.get_traceback(),
		)


def _steer_prompt() -> None:
	"""Tell the assistant the tools exist and in what order to call them."""
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name:
		return
	prompt = frappe.db.get_value("AI Agent Configuration", name, "system_prompt") or ""
	if _PROMPT_MARKER in prompt:
		return
	frappe.db.set_value(
		"AI Agent Configuration",
		name,
		"system_prompt",
		prompt.rstrip() + _PROMPT_SECTION,
		update_modified=False,
	)
	frappe.cache.delete_value(f"agent_config:{AGENT_ID}")


def execute():
	_ensure_scripts()
	_update_process_model()
	_steer_prompt()
	frappe.db.commit()
