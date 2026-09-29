"""ProsAlly's generate and modify stages read their shared modelling rules from skills.

Both stages call the model with no tools, so they cannot load_skill. Each script appends the Active
skills named in its own ProsAlly constant, and the node type and flow rules the two sub-prompts each
carried become one skill. The orchestrator gets its three-call procedure and no enabled skills, since
its skills index would advertise rules it never uses. Idempotent: each edit applies only once.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.seed_prosally_and_frontend_skills import (
	BPMN_SKILL,
	GEN_STEP0_NEW,
	MOD_NEW,
	REWORK_RULE_NEW,
	_upsert_skill,
)

AGENT_ID = "prosally_agent"
NODE_FLOW_SKILL = "prosally-node-types-and-flow-rules"

# Stage sub-prompt id -> Server Script name pattern, matched with like to avoid the dash in the name.
STAGES = {
	"process_generator": "ProsAlly%Tool Generate Process",
	"modifier": "ProsAlly%Tool Modify Process",
}
MOVED_SECTIONS = ("NODE TYPES", "FLOW RULES")
MOD_LANE_POINTER_OLD = MOD_NEW[: MOD_NEW.index("  Assign:")]
MOD_LANE_POINTER_NEW = (
	"  LANE AND REWORK RULES: the bpmn-modelling-rules-and-ir-schema skill below is authoritative.\n"
)

# Stage sub-prompt id -> the ProsAlly constant listing, comma separated, the skills that stage appends.
STAGE_CONSTANTS = {
	"process_generator": "generate_skills",
	"modifier": "modify_skills",
}
STAGE_SKILLS = f"{BPMN_SKILL}, {NODE_FLOW_SKILL}"


def skill_line(constant: str) -> str:
	"""The script line that appends the Active skills named in *constant* to the stage's system prompt."""
	return (
		r'_system = "\n\n".join([_system] + ["## Skill: " + _sk.name + "\n\n" + _sk.body for _sk in '
		r'frappe.get_all("AI Skill", filters={"name": ["in", [_n.strip() for _n in ((_cfg.get("constants") '
		f'or {{}}).get("{constant}") or "").split(",") if _n.strip()]], "status": "Active"}}, '
		r'fields=["name", "body"], order_by="name asc")])'
	)

ORCHESTRATOR_PROMPT = (
	"You run ONE turn of the ProsAlly process-modelling assistant by calling tools, one at a time. "
	"Exactly THREE tool calls per turn, in this order. Step 1: call classify_intent; its result includes "
	"a 'next' field naming exactly which tool to call next (one of redirect, clarify, confirm, "
	"generate_process, modify_process). Step 2: call the tool named in 'next', once. Step 3: call "
	"finalize. Obey the 'next' field exactly, never skip it, never substitute another tool, and never "
	"draw BPMN yourself. The stage tools carry the modelling rules, so never call load_skill.\n\n"
	"When the Step 2 tool returns, go STRAIGHT to finalize. Never call a second stage tool in the same "
	"turn, and never call confirm after generate_process or modify_process: those tools have already "
	"written the turn's reply, so confirming again re-asks a question the designer has already answered "
	"AND discards the diagram they asked for. A Step 2 result reporting that nothing was modified, that a "
	"change awaits confirmation, or that removals need approval is a COMPLETED step, not a failure: that "
	"result IS the reply. Never retry it and never follow it with another tool.\n"
)

NODE_FLOW_BODY = """# ProsAlly node types and flow rules

## Node types: who does the work?
Never use type "task". Every task has a specific type.

- startEvent: exactly one; no incoming flows; triggers the process.
- endEvent: at least one; no outgoing flows; the process is done.
- userTask: a PERSON acts on a screen and the process waits for them. Fill a form, review a document, approve or reject, decide, assign or choose something, sign off. Examples: "Employee submits leave request", "Manager approves invoice".
- scriptTask: the SYSTEM computes something, with no person and no waiting. Check validity (does stock exist, is the balance enough), calculate a value (total, tax, score), run business rules or validation. Examples: "System checks leave balance", "Calculate order total". Not for changing workflow state, writing a field or sending a message: those are serviceTask.
- serviceTask: a PLATFORM OPERATION on a Frappe document, and the workhorse type. Use it whenever the step moves a document through its workflow, writes a field or sends a notification: workflow state change, field update, email, Google Chat, push notification, or a configured connector. Examples: "Set the Visa Request to Pending GRD Manager Approval", "Email the recruiter". Prefer serviceTask over scriptTask for any of those operations; scriptTask is only for logic none of them covers.
- manualTask: a PHYSICAL action no computer tracks. Print a document, pack or assemble, hand-deliver, sign paper.
- exclusiveGateway: a decision point where exactly ONE outgoing path is taken. If/else branches, approval decisions, re-check loops.
- parallelGateway: ALL outgoing paths run at once (split), or wait for ALL to finish (join).
- subProcess: a group of steps collapsed into one named box.

## Flow rules
Every node is reachable from the startEvent and leads to an endEvent. No node is left disconnected.

exclusiveGateway SPLIT (1 incoming, N outgoing): the diagram is rejected unless
- exactly one outgoing flow is marked "default": true (the fallback path, taken when no condition matches), and
- every other outgoing flow has a "condition".

Two branches:
    {"from": "gw_decision", "to": "task_approve", "name": "Approved", "condition": "approved == true"},
    {"from": "gw_decision", "to": "task_reject", "name": "Rejected", "default": true}
Three branches:
    {"from": "gw_check", "to": "task_high", "name": "High", "condition": "score > 80"},
    {"from": "gw_check", "to": "task_medium", "name": "Medium", "condition": "score > 50"},
    {"from": "gw_check", "to": "task_low", "name": "Low", "default": true}

exclusiveGateway JOIN (N incoming, 1 outgoing): no conditions, just the incoming flows.
parallelGateway split or join: no conditions.

Re-check loop (retry, re-submit, repeat until pass): always two gateways, a pure JOIN (N in, 1 out) that merges the first visit and the retry, then a pure FORK (1 in, N out) that branches to pass or fail:
    PreviousStep -> joinGW -> CheckTask -> decisionGW -> (PassPath | RetryTask -> joinGW)
"""

SKILLS = [
	{
		"skill_name": NODE_FLOW_SKILL,
		"description": (
			"ProsAlly node types (which task type does the work) and flow rules (gateway defaults, "
			"conditions, joins, re-check loops). Appended by the generate and modify stages. Do NOT "
			"use it outside ProsAlly's diagram stages."
		),
		"body": NODE_FLOW_BODY,
	},
]


def execute():
	for skill in SKILLS:
		_upsert_skill(skill)

	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name:
		return

	_set_stage_constants(name)
	for sub_agent_id, script_pattern in STAGES.items():
		if _append_skills_to_script(script_pattern, sub_agent_id):
			_trim_sub_prompt(name, sub_agent_id)

	prompt = frappe.db.get_value("AI Agent Configuration", name, "system_prompt") or ""
	if "classify_intent" not in prompt:
		frappe.db.set_value("AI Agent Configuration", name, "system_prompt", ORCHESTRATOR_PROMPT)
	frappe.db.delete(
		"AI Agent Enabled Skill",
		{"parenttype": "AI Agent Configuration", "parent": name, "skill": BPMN_SKILL},
	)


def _set_stage_constants(config_name: str):
	"""Add each stage's skill-list constant to the ProsAlly configuration unless it is already set."""
	for constant in STAGE_CONSTANTS.values():
		if frappe.db.exists("AI Agent Constant", {"parent": config_name, "constant_name": constant}):
			continue
		frappe.get_doc({
			"doctype": "AI Agent Constant",
			"parent": config_name,
			"parentfield": "constants",
			"parenttype": "AI Agent Configuration",
			"constant_name": constant,
			"constant_value": STAGE_SKILLS,
			"constant_type": "String",
			"idx": frappe.db.count("AI Agent Constant", {"parent": config_name}) + 1,
		}).insert(ignore_permissions=True)


def _append_skills_to_script(script_pattern: str, sub_agent_id: str) -> bool:
	"""Insert the skill line after the stage's system prompt line; True once the script carries it."""
	script_name = frappe.db.get_value("Server Script", {"name": ["like", script_pattern]}, "name")
	if not script_name:
		return False
	doc = frappe.get_doc("Server Script", script_name)
	line = skill_line(STAGE_CONSTANTS[sub_agent_id])
	if line in doc.script:
		return True
	anchor = f'_system = (_subs.get("{sub_agent_id}") or {{}}).get("prompt") or ""'
	if doc.script.count(anchor) != 1:
		frappe.log_error(
			title="prosally_stage_skills: system prompt line not found",
			message=f"{script_name} has no single '{anchor}' line; the script and its sub-prompt are left as-is.",
		)
		return False
	doc.script = doc.script.replace(anchor, f"{anchor}\n{line}", 1)
	doc.save(ignore_permissions=True)
	return True


def _trim_sub_prompt(config_name: str, sub_agent_id: str):
	row = frappe.db.get_value(
		"AI Agent Sub Prompt", {"parent": config_name, "sub_agent_id": sub_agent_id}, ["name", "prompt_text"]
	)
	if not row:
		return
	text = trimmed_prompt(row[1] or "")
	if text != row[1]:
		frappe.db.set_value("AI Agent Sub Prompt", row[0], "prompt_text", text, update_modified=False)


def trimmed_prompt(text: str) -> str:
	"""The stage prompt without what the appended skills now carry."""
	text = text.replace(GEN_STEP0_NEW, "", 1).replace(REWORK_RULE_NEW, "\n", 1)
	text = text.replace(MOD_LANE_POINTER_OLD, MOD_LANE_POINTER_NEW, 1)
	for title in MOVED_SECTIONS:
		start = text.find(f"\n=== {title}")
		if start < 0:
			continue
		end = text.find("\n=== ", start + 1)
		text = text[:start] + (text[end:] if end >= 0 else "\n")
	return text
