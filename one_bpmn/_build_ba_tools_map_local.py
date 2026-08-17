# Throwaway (LOCAL BENCH ONLY): builds a BA Agent map in the standard
# agent shape — one AI Agent Task plus an ad-hoc toolbox — derived from
# "Lumina Chat – General Agent", so it can be compared side by side with the
# existing LangGraph-bridge map. Nothing here runs on any other site.
#
# The new map is created INACTIVE on purpose: both maps start on
# agent_mode == "BA Agent", and two active maps would spawn two instances per
# conversation. Use switch_to("tools") / switch_to("langgraph") to flip.

import json
import re

import frappe

SOURCE_MAP = "Lumina Chat – General Agent"
NEW_MAP = "BA – Planning Agent"
NEW_PROCESS_ID = "ba_planning_agent"
LANGGRAPH_MAP = "Lumina Chat – BA Agent"
AGENT_ID = "ba_agent"

# Lumina's scaffolding, copied under BA names. The two that name an agent
# hardcode lumina_general_chat, so they are rewritten as well.
SCRIPT_SUFFIXES = (
	"Build Context", "Cleanup", "Load Agent Config", "Save Response",
	"Save User Message", "Tool MCP Dispatch", "Update Conversation",
)

# The architect-then-product-manager discipline the LangGraph flow enforced
# structurally has to live in the prompt once the model owns the ordering.
BA_SYSTEM_PROMPT = (
	"You are the BA Agent — a business analyst for ONE-FM.\n\n"
	"Work in two stages, in this order, and never skip the first:\n"
	"1. UNDERSTAND AND PLAN. Clarify what the user actually needs, asking a question "
	"when the requirement is ambiguous, then state a short technical plan and ask the "
	"user to approve it. Do not write user stories yet.\n"
	"2. ONLY once the user approves the plan, break it into user stories — each with a "
	"clear title, the user-facing value, and acceptance criteria. Revise them when the "
	"user pushes back.\n\n"
	"INVESTIGATE BEFORE YOU PROPOSE. Call describe_doctype on every DocType the "
	"request touches, before you plan anything. One call gives you existence, module, "
	"submittable, fields, the ACTIVE WORKFLOW with its states, transitions and the "
	"role allowed to make each move, the permission roles, and the existing reports — "
	"and when the name is wrong it hands you the real one. Then:\n"
	"- Search the DocType catalogue by keyword instead of guessing names. ERPNext "
	"vocabulary rarely matches the words in the request: a payslip is Salary Slip, a "
	"payroll run is Payroll Entry, and extra pay is usually Additional Salary. A name "
	"you invented returning nothing is not evidence of absence.\n"
	"- A DocType's schema is not the whole story. Before proposing a status field, an "
	"approval step, a role, a report or a script, check whether one already exists: "
	"query Workflow for that DocType, check whether the DocType is submittable, and "
	"look for the roles and reports already in place.\n"
	"- Proposing to rebuild something the system already has is the most expensive "
	"mistake you can make — a second status field beside a live workflow is worse than "
	"no proposal at all. Where something exists, extend it, and say plainly what the "
	"gap is.\n\n"
	"Ground every claim in a tool result, and state what you checked and what you "
	"found. Never invent DocType names, fields or code paths. Create Jira stories only "
	"when the user explicitly asks for it."
)


# ── describe_doctype ─────────────────────────────────────────────────────────
# One call that answers "what already exists", because prompting the agent to
# look in three places kept revealing a fourth it had not looked in: it read
# the schema but not the Workflow, then checked existence but not the states.
# Thoroughness belongs in the tool, not in a sentence the model must remember.

DESCRIBE_TOOL_ID = "describe_doctype"
DESCRIBE_SCRIPT = "BA – Tool Describe DocType"
DESCRIBE_SLOT = (1220, 810)  # free cell in the toolbox grid

DESCRIBE_PARAMS = {
	"properties": {
		"doctype": {
			"type": "string",
			"description": "Exact DocType name, e.g. 'Overtime Request'. Case-insensitive.",
		}
	},
	"required": ["doctype"],
}

DESCRIBE_DOC = (
	"Everything that already exists for one DocType, in a single call: whether it "
	"exists at all (with near-name suggestions when it does not), its module and "
	"whether it is submittable, its fields, its ACTIVE WORKFLOW including every state "
	"and transition and which role may make each move, the roles that hold "
	"permissions, and the reports already built on it. Call this before proposing to "
	"add a status field, an approval step, a role or a report — if the workflow "
	"already has the state you were about to invent, extend it instead."
)

# Runs under the AI Agent shape-tool executor's SPLIT globals/locals: the whole
# implementation lives in one outer function, every import is made inside it,
# and nothing reads a script-level name.
DESCRIBE_SCRIPT_BODY = '''# BA – Tool Describe DocType  (bpmn_id: describe_doctype)
def _ba_describe_doctype(frappe, doctype):
    name = (doctype or "").strip()
    if not name:
        return {"exists": False, "error": "No DocType name was given."}

    real = frappe.db.get_value("DocType", name, "name")
    if not real:
        # Absence is only real once the near misses are ruled out — and the
        # near miss is usually a vocabulary gap, not a typo: "Payslip" shares
        # no substring with "Salary Slip" as a whole, but does share "slip".
        # So widen from the whole phrase to its words to its fragments, and
        # stop at the first widening that finds anything.
        seen, suggestions = set(), []
        probes = [name] + [w for w in name.split() if len(w) > 3]
        squashed = name.replace(" ", "")
        for size in (6, 5, 4):
            for start in range(0, max(len(squashed) - size + 1, 0)):
                probes.append(squashed[start : start + size])
        for probe in probes:
            for hit in frappe.get_all(
                "DocType", filters=[["name", "like", "%" + probe + "%"]], pluck="name", limit=10
            ):
                if hit not in seen:
                    seen.add(hit)
                    suggestions.append(hit)
            if suggestions and probe != name:
                break  # a narrower probe already answered; do not flood
        return {
            "exists": False,
            "searched_for": name,
            "similar_doctypes": suggestions[:10],
            "note": "Not found under this exact name. Check similar_doctypes before "
            "concluding the capability is missing — the system may name it differently.",
        }

    meta = frappe.get_meta(real)
    out = {
        "exists": True,
        "doctype": real,
        "module": frappe.db.get_value("DocType", real, "module"),
        "is_submittable": bool(meta.is_submittable),
        "is_child_table": bool(meta.istable),
        "is_single": bool(meta.issingle),
        "fields": [
            {
                "fieldname": f.fieldname,
                "label": f.label,
                "fieldtype": f.fieldtype,
                "options": f.options,
                "reqd": bool(f.reqd),
            }
            for f in meta.fields
            if f.fieldtype not in ("Section Break", "Column Break", "Tab Break", "HTML")
        ],
    }

    # The workflow is the part a schema read misses — and the part that decides
    # whether an "approval step" is new work or an existing state.
    workflows = frappe.get_all(
        "Workflow",
        filters={"document_type": real},
        fields=["name", "is_active", "workflow_state_field"],
    )
    out["workflows"] = []
    for wf in workflows:
        doc = frappe.get_doc("Workflow", wf["name"])
        out["workflows"].append({
            "name": wf["name"],
            "is_active": bool(wf["is_active"]),
            "state_field": wf["workflow_state_field"],
            "states": [
                {"state": s.state, "doc_status": s.doc_status, "allow_edit": s.allow_edit}
                for s in doc.states
            ],
            "transitions": [
                {
                    "from": t.state,
                    "action": t.action,
                    "to": t.next_state,
                    "allowed_role": t.allowed,
                }
                for t in doc.transitions
            ],
        })
    out["has_active_workflow"] = any(w["is_active"] for w in out["workflows"])

    out["permissions"] = [
        {
            "role": p.role,
            "read": bool(p.read),
            "write": bool(p.write),
            "create": bool(p.create),
            "submit": bool(p.submit),
        }
        for p in meta.permissions
    ]
    out["reports"] = frappe.get_all(
        "Report", filters={"ref_doctype": real}, fields=["name", "report_type"], limit=25
    )
    return out


_ba_out = _ba_describe_doctype(frappe, task_data.get("doctype") or "")
for _key, _value in _ba_out.items():
    result[_key] = _value
'''


def _rewrite(text: str) -> str:
	"""Lumina → BA, for script bodies and api methods."""
	return (
		text.replace("Lumina – ", "BA – ")
		.replace("lumina_general_chat", AGENT_ID)
		.replace("lumina___", "ba___")
		.replace("# Lumina", "# BA")
	)


def copy_scripts():
	for suffix in SCRIPT_SUFFIXES:
		source_name, new_name = f"Lumina – {suffix}", f"BA – {suffix}"
		if not frappe.db.exists("Server Script", source_name):
			print(f"  source missing, skipped: {source_name}")
			continue
		source = frappe.get_doc("Server Script", source_name)
		values = {
			"script_type": source.script_type,
			"api_method": _rewrite(source.api_method or ""),
			"allow_guest": source.allow_guest,
			"disabled": 0,
			"script": _rewrite(source.script or ""),
			"module": source.module,
		}
		if frappe.db.exists("Server Script", new_name):
			doc = frappe.get_doc("Server Script", new_name)
			doc.update(values)
			doc.save(ignore_permissions=True)
			print(f"  script updated: {new_name}")
		else:
			frappe.get_doc({"doctype": "Server Script", "name": new_name, **values}).insert(
				ignore_permissions=True
			)
			print(f"  script created: {new_name}")


def describe_script():
	"""The Server Script behind describe_doctype (own script, not MCP dispatch)."""
	values = {
		"script_type": "API",
		"api_method": "ba_tool_describe_doctype",
		"allow_guest": 0,
		"disabled": 0,
		"script": DESCRIBE_SCRIPT_BODY,
		"module": "ONE BPMN",
	}
	if frappe.db.exists("Server Script", DESCRIBE_SCRIPT):
		doc = frappe.get_doc("Server Script", DESCRIBE_SCRIPT)
		doc.update(values)
		doc.save(ignore_permissions=True)
		print(f"  script updated: {DESCRIBE_SCRIPT}")
	else:
		frappe.get_doc({"doctype": "Server Script", "name": DESCRIBE_SCRIPT, **values}).insert(
			ignore_permissions=True
		)
		print(f"  script created: {DESCRIBE_SCRIPT}")


def build_xml() -> str:
	xml = frappe.db.get_value("BPMN Process Model", SOURCE_MAP, "bpmn_xml") or ""
	if not xml:
		frappe.throw(f"{SOURCE_MAP} has no XML on this site")

	# Ids are replaced as whole tokens so the diagram interchange (DI) keeps
	# pointing at the same shapes — a dangling DI reference breaks the editor.
	xml = xml.replace("lumina_chat_general_agent", NEW_PROCESS_ID)
	xml = xml.replace("general_chat_tools", "ba_planning_tools")
	xml = xml.replace("run_general_chat_agent", "run_ba_agent")
	xml = xml.replace("Lumina – ", "BA – ")
	xml = xml.replace('name="Lumina Chat General Agent"', f'name="{NEW_MAP}"')
	xml = xml.replace('name="Run General Chat Agent"', 'name="Run BA Agent"')

	# Start gate: the label IS the trigger, in both the condition and the
	# (invisible, and therefore sneakier) trigger field filter.
	xml = xml.replace('triggerFieldValue="General Chat"', 'triggerFieldValue="BA Agent"')
	xml = re.sub(
		r"(<bpmn:condition>)\s*agent_mode\s*==\s*\"General Chat\"\s*(</bpmn:condition>)",
		r'\1agent_mode == "BA Agent"\2',
		xml,
	)
	# Dispatch reads agent-level settings from the configuration named here.
	xml = re.sub(r'aiAgentConfig="[^"]*"', 'aiAgentConfig="BA Agent"', xml)
	xml = re.sub(
		r'aiSystemPrompt="[^"]*"',
		'aiSystemPrompt="' + frappe.utils.escape_html(BA_SYSTEM_PROMPT).replace("\n", "&#10;") + '"',
		xml,
		count=1,
	)
	return _add_describe_tool(xml)


def _add_describe_tool(xml: str) -> str:
	"""Add the describe_doctype shape to the toolbox, with its diagram bounds.

	A tool shape the editor cannot draw is a tool nobody can maintain, so the
	BPMNShape goes in alongside it — the ad-hoc sub-process is laid out on a
	150x90 grid and this takes the next free cell.
	"""
	if f'id="{DESCRIBE_TOOL_ID}"' in xml:
		return xml

	params = frappe.utils.escape_html(json.dumps(DESCRIBE_PARAMS, separators=(",", ":")))
	shape = (
		f'    <bpmn:scriptTask id="{DESCRIBE_TOOL_ID}" name="{DESCRIBE_TOOL_ID}"'
		f' spiffworkflow:serverScript="{DESCRIBE_SCRIPT}"'
		f' spiffworkflow:scriptType="Server Script"'
		f' spiffworkflow:scriptName="{DESCRIBE_SCRIPT}"'
		f' spiffworkflow:aiToolParams="{params}">\n'
		f"      <bpmn:documentation>{frappe.utils.escape_html(DESCRIBE_DOC)}</bpmn:documentation>\n"
		f"    </bpmn:scriptTask>\n"
	)
	xml = xml.replace("</bpmn:adHocSubProcess>", shape + "  </bpmn:adHocSubProcess>", 1)

	x, y = DESCRIBE_SLOT
	di = (
		f'      <bpmndi:BPMNShape id="{DESCRIBE_TOOL_ID}_di" bpmnElement="{DESCRIBE_TOOL_ID}">\n'
		f'        <dc:Bounds x="{x}" y="{y}" width="130" height="70" />\n'
		f"      </bpmndi:BPMNShape>\n"
	)
	return xml.replace("</bpmndi:BPMNPlane>", di + "    </bpmndi:BPMNPlane>", 1)


def build_map():
	xml = build_xml()
	if frappe.db.exists("BPMN Process Model", NEW_MAP):
		doc = frappe.get_doc("BPMN Process Model", NEW_MAP)
		doc.bpmn_xml = xml
		doc.flags.skip_editability_check = True
		doc.save(ignore_permissions=True)
		print(f"  map updated: {doc.name}")
	else:
		source = frappe.get_doc("BPMN Process Model", SOURCE_MAP)
		doc = frappe.get_doc({
			"doctype": "BPMN Process Model",
			"title": NEW_MAP,
			"process_id": NEW_PROCESS_ID,
			"version": 1,
			"bpmn_xml": xml,
			"trigger_type": source.trigger_type,
			"trigger_event": source.trigger_event,
			"is_active": 0,  # deliberately parked — see module docstring
			"start_events": [
				{
					"event_type": row.event_type,
					"bpmn_element_id": row.bpmn_element_id,
					"trigger_type": row.trigger_type,
					"trigger_doctype": row.trigger_doctype,
					"trigger_event": row.trigger_event,
					"workflow_state_condition": row.workflow_state_condition,
					"cron_expression": row.cron_expression,
				}
				for row in source.start_events
			],
		})
		doc.flags.skip_editability_check = True
		doc.insert(ignore_permissions=True)
		print(f"  map created: {doc.name} (inactive)")

	from one_bpmn.api.compilation import compile_process_model

	compile_process_model(NEW_MAP)
	spec = frappe.db.get_value("BPMN Process Model", NEW_MAP, "serialized_spec")
	print(f"  compiled: {len(spec or '')} bytes")


def switch_to(shape: str):
	"""Point BA Agent at one shape and park the other. 'tools' | 'langgraph'."""
	target = NEW_MAP if shape == "tools" else LANGGRAPH_MAP
	other = LANGGRAPH_MAP if shape == "tools" else NEW_MAP
	frappe.db.set_value("BPMN Process Model", other, "is_active", 0, update_modified=False)
	frappe.db.set_value("BPMN Process Model", target, "is_active", 1, update_modified=False)
	config = frappe.db.exists("AI Agent Configuration", {"agent_id": AGENT_ID})
	frappe.db.set_value("AI Agent Configuration", config, "process_model", target, update_modified=False)
	frappe.cache.delete_value(f"agent_config:{AGENT_ID}")
	frappe.db.commit()
	print(f"BA Agent now runs: {target}  (parked: {other})")


def run():
	print("scripts:")
	copy_scripts()
	describe_script()
	print("map:")
	build_map()
	frappe.db.commit()
	print("\nBuilt. Flip with switch_to('tools') / switch_to('langgraph').")
