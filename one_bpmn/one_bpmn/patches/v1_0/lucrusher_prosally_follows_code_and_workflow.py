# Copyright (c) 2026, one-fm and contributors
"""LuCrusher drafts ProsAlly prompt blocks from the code and the Workflow, within a size limit.

Edits the ProsAlly skill, the finalize schema on the LuCrusher map, and the Finalize, Save
Response and Build Context scripts. A target that already carries its marker is left as it
is, and a target whose anchor moved is reported and not written.
"""

import html
import json
import re

import frappe

from one_bpmn.one_bpmn.patches.v1_0.seed_lucrusher_skills import PROSALLY_SKILL

DASH = chr(0x2013)
MODEL_NAME = f"LuCrusher {DASH} Migration Agent"
FINALIZE = f"LuCrusher {DASH} Tool Finalize"
SAVE_RESPONSE = f"LuCrusher {DASH} Save Response"
BUILD_CONTEXT = f"LuCrusher {DASH} Build Context"

SKILL_MARKER = "## Grounding"
FINALIZE_MARKER = "_lucrusher_element_count"
SAVE_MARKER = "_lucrusher_merge_prompts"
CONTEXT_MARKER = "_pp_left"

MAX_ELEMENTS = 25
MAX_PROCESSES = 2

LANES_OLD = "Use the Lucidchart swimlanes as named and in their order."
LANES_NEW = (
	"When the DocType has an active Workflow, the lanes are the distinct roles in the allowed field of "
	"its transitions (from read_doctype_logic), in transition order; a Lucidchart lane with no matching "
	"role is not drawn and goes into conflicts. With no Workflow, use the Lucidchart swimlanes as named "
	"and in their order."
)
RULE_OLD = "- The processes array has exactly one entry per topology process. Never combine processes."
RULE_NEW = "- The processes array has one entry per drafted process. Never combine processes."
GENERATED_OLD = (
	'- Generated: intent "PROSALLY_PROMPT_DRAFT", response at most 300 characters, '
	"prosally_prompts={processes:[{process_name, process_id, lane_count, element_count, prompt_block, source}]}."
)
GENERATED_NEW = (
	'- Generated: intent "PROSALLY_PROMPT_DRAFT", response at most 1500 characters with the coverage table, '
	"the gaps and the conflicts, prosally_prompts={processes:[{process_name, process_id, lane_count, "
	"element_count, prompt_block, source}], coverage:[{behaviour, citation, element, status}], "
	"conflicts:[{topic, lucid, code, citation}], remaining:[process names not yet drafted]}."
)
SKILL_SECTIONS = f"""{SKILL_MARKER}
Before drafting a process, call read_doctype_logic for its DocTypes (at most 5 per call, call again for more). Draft from its output and the Lucidchart document, nothing else.
- Every element's config carries src=<file>:<method> for the behaviour it covers. Behaviour that is in neither the code nor the Lucidchart document is not drawn.
- A wait on another document's state, a delete or cleanup path and a rejection raised in code are each an element.
- A loop over a child table or a checklist in code is a per-item loop in the block, not one straight line.
- A limit read from a Single DocType cites every field the code reads.
- A method that fills a link chain lists the whole chain.
- Code paths that differ (reactive and preventive, on submit and on update after submit) are separate steps.

## Size
A prompt_block has at most {MAX_ELEMENTS} elements and one finalize carries at most {MAX_PROCESSES} processes. A process that needs more elements is split into a parent block and a child block joined by a CallActivity; each counts toward the {MAX_PROCESSES}. When processes are left, list their names in remaining, say so in the reply and wait for the user to say continue. finalize rejects a block over {MAX_ELEMENTS} elements and a third process.

## Conflicts
Where the Lucidchart document and the code, or two code paths, disagree on a rule, a value or an order, do not choose. Add {{topic, lucid, code, citation}} to conflicts and ask the user which is right in the reply.

## Check before finalize
Before calling finalize, build coverage: one row {{behaviour, citation, element, status}} for every behaviour found in the code, with status Covered (and the element number) or Gap. Show the user the coverage table, the gaps and the conflicts in the reply, then call finalize with coverage and conflicts.
"""

FINALIZE_EDITS = [
	(
		'    prosally_prompts = _arg("prosally_prompts")\n',
		'''    prosally_prompts = _arg("prosally_prompts")

    def _lucrusher_element_count(block):
        import re

        in_c, count = False, 0
        for line in str(block or "").splitlines():
            if re.match(r"^\\W*C\\s*[:.)-]", line):
                in_c = True
            elif re.match(r"^\\W*D\\s*[:.)-]", line):
                break
            elif in_c and re.match(r"^\\s*\\d+[.)]\\s", line):
                count += 1
        return count

    if isinstance(prosally_prompts, dict):
        for proc in prosally_prompts.get("processes") or []:
            if not isinstance(proc, dict):
                continue
            proc["element_count"] = _lucrusher_element_count(proc.get("prompt_block"))
            if proc["element_count"] > '''
		+ str(MAX_ELEMENTS)
		+ """:
                raise ValueError(
                    "Process '" + str(proc.get("process_name")) + "' has " + str(proc["element_count"])
                    + " elements in section C; the limit is """
		+ str(MAX_ELEMENTS)
		+ """. Split it into a parent "
                    "block and a child block joined by a CallActivity."
                )
""",
	),
]

SAVE_EDITS = [
	(
		'msg = frappe.new_doc("Chat Message")\n',
		'''def _lucrusher_merge_prompts(new, old):
    # A later call adds its processes to the drafts already held, by process_id.
    if not (isinstance(new, dict) and new.get("processes") and isinstance(old, dict)):
        return new
    held = {}
    for _p in (old.get("processes") or []) + new["processes"]:
        if isinstance(_p, dict):
            held[str(_p.get("process_id") or _p.get("process_name"))] = _p
    merged = dict(new)
    merged["processes"] = list(held.values())
    return merged


if agent_result.get("prosally_prompts"):
    agent_result["prosally_prompts"] = _lucrusher_merge_prompts(
        agent_result["prosally_prompts"], _prev.get("prosally_prompts")
    )

msg = frappe.new_doc("Chat Message")
''',
	),
]

CONTEXT_EDITS = [
	(
		'        lines.append("  ProsAlly prompts : generated for " + str(n_pp) + " process(es)")\n',
		"""        _pp_left = pp.get("remaining") or []
        _pp_tail = ""
        if isinstance(_pp_left, list) and _pp_left:
            _pp_tail = ", " + str(len(_pp_left)) + " remaining: " + ", ".join(str(x) for x in _pp_left)
        lines.append("  ProsAlly prompts : generated for " + str(n_pp) + " process(es)" + _pp_tail)
""",
	),
]

PROSALLY_SCHEMA = {
	"processes": {
		"type": "array",
		"maxItems": MAX_PROCESSES,
		"items": {
			"type": "object",
			"properties": {
				"process_name": {"type": "string"},
				"process_id": {"type": "string", "minLength": 1},
				"element_count": {"type": "integer", "maximum": MAX_ELEMENTS},
				"prompt_block": {"type": "string", "minLength": 1},
				"source": {
					"type": "string",
					"minLength": 1,
					"description": "The Lucidchart page title, or the code file path from the codebase scan, this comes from.",
				},
			},
			"required": ["source", "process_id", "element_count", "prompt_block"],
		},
	},
	"coverage": {
		"type": "array",
		"description": "One row per code behaviour found: where it is cited and which element covers it.",
		"items": {
			"type": "object",
			"properties": {
				"behaviour": {"type": "string", "minLength": 1},
				"citation": {"type": "string", "minLength": 1},
				"element": {"type": ["string", "integer"]},
				"status": {"enum": ["Covered", "Gap"]},
			},
			"required": ["behaviour", "citation", "status"],
			"if": {"properties": {"status": {"const": "Covered"}}},
			"then": {"required": ["element"]},
		},
	},
	"conflicts": {
		"type": "array",
		"description": "Where Lucidchart and the code disagree: {topic, lucid, code, citation}.",
		"items": {
			"type": "object",
			"properties": {
				"topic": {"type": "string", "minLength": 1},
				"citation": {"type": "string", "minLength": 1},
			},
			"required": ["topic", "citation"],
		},
	},
	"remaining": {"type": "array", "items": {"type": "string"}},
}

FINALIZE_PARAMS = re.compile(r'<bpmn:scriptTask id="finalize"[^>]*?spiffworkflow:aiToolParams="([^"]*)"')


def apply_edits(code, edits, marker):
	"""The code with every edit applied, or the input when it is marked or an anchor moved."""
	if marker in code or any(code.count(anchor) != 1 for anchor, _ in edits):
		return code
	for anchor, replacement in edits:
		code = code.replace(anchor, replacement)
	return code


def with_grounding(body):
	"""The skill body with the grounding rules, or the input when it is marked or an anchor moved."""
	if SKILL_MARKER in body or any(body.count(old) != 1 for old in (LANES_OLD, RULE_OLD, GENERATED_OLD)):
		return body
	body = body.replace(LANES_OLD, LANES_NEW).replace(RULE_OLD, RULE_NEW).replace(GENERATED_OLD, GENERATED_NEW)
	return f"{body.rstrip(chr(10))}\n\n{SKILL_SECTIONS}"


def with_prosally_schema(xml):
	"""The map XML with the prosally_prompts limits on the finalize shape, or the input when not possible."""
	match = FINALIZE_PARAMS.search(xml)
	if not match:
		return xml
	schema = json.loads(html.unescape(match.group(1)))
	prompts = schema.get("properties", {}).get("prosally_prompts")
	if prompts is None or "coverage" in prompts.get("properties", {}):
		return xml
	prompts["properties"] = PROSALLY_SCHEMA
	prompts["required"] = ["processes", "coverage"]
	escaped = html.escape(json.dumps(schema), quote=True)
	return xml[: match.start(1)] + escaped + xml[match.end(1) :]


def _log_anchor_missing(what, hint):
	frappe.log_error(
		title=f"lucrusher_prosally_follows_code: {what} not found",
		message=f"{hint} no longer matches the text this patch edits; apply the change by hand.",
	)


def _patch_skill():
	name = frappe.db.get_value("AI Skill", {"skill_name": PROSALLY_SKILL}, "name")
	if not name:
		return
	body = frappe.db.get_value("AI Skill", name, "body") or ""
	patched = with_grounding(body)
	if patched != body:
		frappe.db.set_value("AI Skill", name, "body", patched)
	elif SKILL_MARKER not in body:
		_log_anchor_missing("skill anchor", f"Skill {PROSALLY_SKILL}")


def _patch_map():
	if not frappe.db.exists("BPMN Process Model", MODEL_NAME):
		return
	xml = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "bpmn_xml") or ""
	patched = with_prosally_schema(xml)
	if patched != xml:
		frappe.db.set_value("BPMN Process Model", MODEL_NAME, "bpmn_xml", patched)
		from one_bpmn.api.compilation import compile_process_model

		compile_process_model(MODEL_NAME)
	elif "coverage" not in html.unescape(xml):
		_log_anchor_missing("finalize shape", f"'{MODEL_NAME}'")


def _patch_scripts():
	for name, marker, edits in (
		(FINALIZE, FINALIZE_MARKER, FINALIZE_EDITS),
		(SAVE_RESPONSE, SAVE_MARKER, SAVE_EDITS),
		(BUILD_CONTEXT, CONTEXT_MARKER, CONTEXT_EDITS),
	):
		if not frappe.db.exists("Server Script", name):
			continue
		code = frappe.db.get_value("Server Script", name, "script") or ""
		patched = apply_edits(code, edits, marker)
		if patched != code:
			frappe.db.set_value("Server Script", name, "script", patched, update_modified=False)
		elif marker not in code:
			_log_anchor_missing("script anchor", name)


def execute():
	_patch_skill()
	_patch_map()
	_patch_scripts()
