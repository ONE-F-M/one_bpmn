"""WI-000463: ProsAlly's lane rules and IR schema move from its sub-prompts to two AI Skills.

move_domain_rules_into_skills.py and seed_logix_skills.py already moved Logix's and
Docu's repeated domain rules into skills the model loads on demand instead of
paying for on every turn. ProsAlly's process_generator and modifier sub-prompts
carry the same kind of thing twice over: the lane-assignment rules (which lanes
win, how automated steps are placed, the rework-loop convergence rule, added by
prosally_lane_fidelity.py) and the IR node/config schema (the six Service Types,
the userTask assignment block, added by prosally_configures_the_tasks_it_draws.py).
Both are reference material the model needs while building or editing a diagram,
not a fact about who ProsAlly is or what it is for.

This patch creates "BPMN Modelling Rules" (bpmn-modelling-rules) and "IR Schema"
(ir-schema) as AI Skills, tells the two sub-prompts to load_skill them before
building or editing the IR, and replaces the resident rule/schema text those two
earlier patches left in place with that short pointer. The replaced strings are
exactly what those patches are known to have left behind, so this only fires on
a sub-prompt that still carries them.

Idempotent: skills are matched by name and brought up to date; a sub-prompt
already carrying the load_skill pointer is left alone.
"""

import frappe

AGENT_ID = "prosally_agent"

MODELLING_SKILL = "bpmn-modelling-rules"
SCHEMA_SKILL = "ir-schema"

SKILLS = [
	{
		"skill_name": MODELLING_SKILL,
		"description": (
			"How ProsAlly assigns lanes and task types when generating or modifying a BPMN "
			"diagram: designer-named lanes are authoritative, where an automated step goes when "
			"no system lane was named, the minimum lane count, and converging rework/rejection "
			"paths on one re-entry point instead of a separate return line each. Use this skill "
			"before generating a new diagram or modifying lanes, roles or rework flow on an "
			"existing one. Do NOT use it for the IR's JSON shape; that is the ir-schema skill."
		),
		"body": """# BPMN lane and task-type rules

## Lanes the designer named win, always
If the request names the lanes \u2014 "3 lanes only: Recruiter, GRD Operator, GRD Manager", "lanes are Employee, Manager, HR" \u2014 the "lanes" array is EXACTLY that list, in that order.

- Do not add a lane. Do not rename one. Do not drop one.
- In particular do NOT add a "System (Automatic)" lane unless the designer named it.
- Automated steps still have to live somewhere: put each one in the lane of the role responsible for it \u2014 whoever triggers it, or whoever acts on its result. An email to the recruiter after the GRD Operator submits belongs to the GRD Operator; a validation that runs while the Recruiter fills the form belongs to the Recruiter.
- The count the designer states is the count you output. "3 lanes only" means three.

## When the designer names no lanes
Identify the actors from the description yourself. Any automated step (send email, validate, calculate, check, create record, notify) goes to a "System (Automatic)" lane you add. If only one human is mentioned, still add "System (Automatic)" as a second lane \u2014 the minimum is two.

## Task type: serviceTask vs scriptTask
- serviceTask is a PLATFORM OPERATION the system performs on a Frappe document: moving a document through its workflow, writing a field, sending a notification. This is the workhorse type. It carries a "config" object (see the ir-schema skill) and is preferred over scriptTask for any of the six Service Types.
- scriptTask is for the system COMPUTING something with no person involved and no document/workflow/notification side effect: checking validity, calculating a value, running a business rule. It is never the right type for changing workflow state, writing a field, or sending a message \u2014 use serviceTask for those, since only serviceTask carries the configuration they need.

## Rework loops \u2014 one re-entry point
Approval processes send work back: rejected, changes requested, resubmit, re-check. When several outcomes return the work to the SAME stage, route them all into ONE re-entry point \u2014 a single join gateway in front of that stage \u2014 instead of drawing a separate return from each rejection point.

One shared re-entry: `gw_pam_reject, gw_moi_reject, gw_mgr_reject -> gw_back_to_operator -> task_operator_revise`, not three separate flows from three rejection points back across the diagram. This is how a business reader expects to see rework, and it keeps the drawing legible: every separate return is a line running the full width of the diagram, crossing every flow that changes lane along the way.
""",
	},
	{
		"skill_name": SCHEMA_SKILL,
		"description": (
			"The IR (intermediate representation) JSON shape ProsAlly builds and edits: the node "
			"fields (id, type, name, lane, config), the lanes array, and the config schema for "
			"startEvent, each of the six serviceTask Service Types, and userTask assignment. Use "
			"this skill before emitting or editing IR JSON so every node the request describes is "
			"configured, not left for a human to finish. Do NOT use it for lane-assignment "
			"decisions; that is the bpmn-modelling-rules skill."
		),
		"body": """# The IR node and config schema

Every node carries: `"id"`, `"type"`, `"name"`, and `"lane"` (the lane id \u2014 REQUIRED on every node when lanes are present). A startEvent, serviceTask or userTask may also carry a `"config"` object: `"config": { "\u2026": "startEvent / serviceTask / userTask settings" }`.

Fill in "config" whenever the request names a DocType, a workflow state, an assignee or an action \u2014 a task generated without it has to be configured by hand afterwards. Only include a key when the request actually tells you its value; invent nothing.

## startEvent config
Set it whenever the request says what kicks the process off:
- `"triggerDoctype"` \u2014 the DocType whose creation starts this, e.g. `"Visa Request"`
- `"triggerType"` \u2014 `"After Insert"`

## serviceTask config
`"serviceType"` is required and is exactly one of:

- **apply_workflow** \u2014 move a document to a workflow state: `"serviceTargetDoctype"`, `"workflowState"`. Do NOT supply docStatus or onlyAllowEdit \u2014 they are read off the workflow automatically and anything you write is replaced.
- **send_email** \u2014 email notification: `"emailSubject"`, `"emailBody"`, `"emailTo"` (comma-separated), `"emailToRoles"`, `"emailToDocFields"`, `"emailCc"`, `"emailBcc"`, `"emailAccount"`, `"emailUseDoctype"` (true/false), `"emailDoctype"`.
- **update_field** \u2014 write a value onto a document: `"updateFieldDoctype"`, `"updateFieldRows"`.
- **google_chat** \u2014 Google Chat message: `"gchatType"` ("individual" or "space"), `"gchatEmail"` (individual), `"gchatSpaceId"` (space), `"gchatMessage"`.
- **push_notification** \u2014 mobile push: `"pushDoctype"`, `"pushTitle"`, `"pushMessage"`, `"pushToUsers"`, `"pushToRoles"`, `"pushToDocFields"`.
- **connector** \u2014 a configured external connector: `"connectorId"`, `"connectorParams"`.

## userTask config
- `"targetDoctype"` \u2014 the DocType the person works on, e.g. `"Visa Request"`
- `"assigneeMode"` \u2014 exactly one of: `"User"`, `"DocField"`, `"Round Robin"`, `"Load Balancing"`, `"Table Field"`
- then the field that matches the mode: `"User"` -> `"assigneeUser"` (a user id); `"DocField"` -> `"assigneeDocfield"` (a fieldname holding a user); `"Table Field"` -> `"assigneeTableField"` plus `"assigneeTableUserField"`
- `"taskActions"` \u2014 the buttons the person gets, as a list. Each entry is either a plain name or an object: `{"action": "Approve", "confirmTransition": true, "requireDigitalSignature": true}`. Use the confirm and signature flags on approvals, rejections, and anything else irreversible.

## Worked example
```json
{
  "id": "start", "type": "startEvent", "name": "Visa Request Raised",
  "lane": "recruiter",
  "config": { "triggerDoctype": "Visa Request", "triggerType": "After Insert" }
},
{
  "id": "task_grd_review", "type": "userTask", "name": "Review Visa Request",
  "lane": "grd_manager",
  "config": {
    "targetDoctype": "Visa Request",
    "assigneeMode": "DocField",
    "assigneeDocfield": "grd_manager",
    "taskActions": [
      {"action": "Approve", "confirmTransition": true, "requireDigitalSignature": true},
      {"action": "Reject", "confirmTransition": true}
    ]
  }
},
{
  "id": "task_send_grd", "type": "serviceTask", "name": "Send for GRD Approval",
  "lane": "grd_manager",
  "config": {
    "serviceType": "apply_workflow",
    "serviceTargetDoctype": "Visa Request",
    "workflowState": "Pending GRD Manager Approval"
  }
}
```

If a workflow state you used does not exist, use one of the states you are told the DocType really has \u2014 do not invent a near-match. No node type is `"task"`; every node is one of the specific types above.
""",
	},
]

# Present once a sub-prompt has been told to load the two skills.
PROMPT_MARKER = "load_skill"

LOAD_SKILLS_HEADER = (
	"\n\nBEFORE YOU BUILD OR EDIT THE IR: call load_skill with `bpmn-modelling-rules` for the "
	"lane and task-type rules, and `ir-schema` for the node/config JSON shape. Load both before "
	"you emit or change any IR node.\n"
)


def execute():
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name:
		return
	doc = frappe.get_doc("AI Agent Configuration", name)

	changed = False
	for row in doc.sub_prompts or []:
		if row.sub_agent_id in ("process_generator", "modifier") and PROMPT_MARKER not in (
			row.prompt_text or ""
		):
			row.prompt_text = (row.prompt_text or "").rstrip() + LOAD_SKILLS_HEADER
			changed = True

	enabled = {row.skill for row in doc.enabled_skills}
	for skill in SKILLS:
		if skill["skill_name"] not in enabled:
			doc.append("enabled_skills", {"skill": skill["skill_name"]})
			changed = True

	for skill in SKILLS:
		_upsert_skill(skill)

	if changed:
		doc.flags.ignore_validate_update_after_submit = True
		doc.save(ignore_permissions=True)


def _upsert_skill(skill: dict):
	if frappe.db.exists("AI Skill", skill["skill_name"]):
		existing = frappe.get_doc("AI Skill", skill["skill_name"])
		if (existing.description, existing.body, existing.status) == (
			skill["description"],
			skill["body"],
			"Active",
		):
			return
		existing.description = skill["description"]
		existing.body = skill["body"]
		existing.status = "Active"
		existing.save(ignore_permissions=True)
		return
	new = frappe.new_doc("AI Skill")
	new.skill_name = skill["skill_name"]
	new.tier = "Draft-Only"
	new.description = skill["description"]
	new.body = skill["body"]
	new.status = "Active"
	new.save(ignore_permissions=True)
