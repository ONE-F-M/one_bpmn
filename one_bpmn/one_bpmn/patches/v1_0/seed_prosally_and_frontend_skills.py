"""WI-000462: the last two domain-rule blocks leave their prompts for skills.

Two earlier patches (move_domain_rules_into_skills, seed_logix_skills,
seed_docu_skills) already did this for Logix's Frappe Server Script safety
rules and Docu's form design rules. Two blocks were left:

* ProsAlly's lane-fidelity rule ("a designer-named lane set is authoritative"),
  its automated-step lane assignment rule, its rework-loop convergence rule,
  and the IR/element schema the generator and modifier read and write, all
  sat inline in the process_generator and modifier sub-prompts and were paid
  for on every turn regardless of whether the request touched lanes at all.
* The Frontend Agent's "HOW THE FRONT END HERE IS WRITTEN" block (frappe-ui
  components, Vue script-setup conventions, Tailwind tokens, frappeRequest,
  desk-script conventions, file-size discipline) sat inline in its system
  prompt on every delegated work order, including ones that never touch a
  Vue file.

Each becomes an AI Skill. ProsAlly's generator and modifier sub-prompts keep
the lane rule of thumb as a one-line pointer to load the skill before
build_diagram; the Frontend Agent's system prompt keeps role, goals and
rules of thumb and points at the skill before any Vue or desk-script edit.

Idempotent: skills are matched by name and brought up to date without
lowering status; a sub-prompt or system prompt is edited only while it still
carries the block that moved, matched best-effort block by block the way
prosally_lane_fidelity.py already does; a skill is enabled on a configuration
only once. A site without ProsAlly or the Frontend Agent is left alone.
"""

import frappe

PROSALLY_CONFIG_NAME = "prosally"
FRONTEND_AGENT_NAME = "Frontend Agent"

BPMN_SKILL = "bpmn-modelling-rules-and-ir-schema"
FRONTEND_SKILL = "frontend-house-style"

SKILLS = [
	{
		"skill_name": BPMN_SKILL,
		"description": (
			"BPMN lane-modelling rules and the IR/element JSON schema ProsAlly draws diagrams "
			"from: lane fidelity (a designer-named lane set is authoritative, no invented "
			"'System (Automatic)' lane), where an automated step's lane comes from, converging "
			"rework onto one re-entry point, and the attribute families each shape type carries "
			"(assignment, service task, trigger). Use this skill before generating or modifying a "
			"diagram, before calling build_diagram. Do NOT use it for a request that is not about "
			"the diagram's shape or lanes."
		),
		"body": """# BPMN lanes, rework and the IR schema

## Lane fidelity
If the request names the lanes — "3 lanes only: Recruiter, GRD Operator, GRD Manager", "lanes are Employee, Manager, HR" — the `lanes` array is EXACTLY that list, in that order. Do not add, rename or drop a lane, and in particular do not add a "System (Automatic)" lane unless the designer named it. The count they state is the count you output.

Only when the request does NOT name the lanes do you identify the actors yourself: read the description for who does what, and if only one human is mentioned add "System (Automatic)" as a second lane so there are always at least two.

## Where an automated step's lane comes from
- When the designer named the lanes: an automated step (scriptTask, serviceTask) lives in the lane of the role responsible for it — whoever triggers it, or whoever acts on its result. An email sent after the GRD Operator submits belongs to the GRD Operator; a validation that runs while the Recruiter fills the form belongs to the Recruiter. There is no system lane unless they asked for one.
- When the designer named no lanes: every automated step goes in the "System (Automatic)" lane, separate from the human lanes you identified.

## Rework loops converge on one re-entry point
Approval processes send work back: rejected, changes requested, resubmit, re-check, awaiting quota. When several outcomes return the work to the SAME stage, route them all into ONE re-entry point — a single join gateway in front of that stage — instead of drawing a separate return line from each rejection.

One shared re-entry: `gw_pam_reject, gw_moi_reject, gw_mgr_reject → gw_back_to_operator → task_operator_revise`, not three separate flows crossing the whole diagram. This is both how a business reader expects rework drawn and the largest lever on diagram readability: every separate return is a line running the full width of the diagram, crossing every flow that changes lane along the way.

## The IR / element schema
The generator and modifier output an IR: a `lanes` array (id + name, in the order above) and the shapes that sit in them, plus the flows between them. Each shape carries `id`, `name`, `type` (userTask, scriptTask, serviceTask, gateway, startEvent, endEvent, ...) and a `lane` it belongs to. Beyond that, a shape's own configuration follows its type:

- **User Task assignment** — `assignmentMode`, `assigneeDocField`, `roundRobinRole`, `loadBalancingRole`, `leaveRelieverEnabled`: these are the attribute names the properties panel reads: fill them, do not invent alternatives.
- **Service Task** — one of the platform's six Service Types, set via `serviceType` plus the fields that type needs: `serviceTargetDoctype` and `updateFieldDoctype`/`updateFieldName`/`updateFieldValue` for a record update, `emailSubject`/`emailTo`/`emailBody`/`emailAccount` for an email, `gchatMessage`/`gchatSpaceId` for Google Chat, `pushTitle`/`pushMessage` for a push notification, `calledDecisionId` for a decision table, `notificationName` for a stored Notification. A serviceTask is a platform action on a DocType, not an outside third-party call; a call to something outside Frappe is a scriptTask instead.
- **Trigger (start event)** — `triggerType` and `triggerDoctype` for a document-driven start; a timer-started process carries no cycle definition of its own — the scheduler alone decides when it begins.
- **Workflow gate** — `workflowState`, `docStatus` when a gateway or task depends on the context document's own state.

Keep every attribute name exactly as listed; the compiler and the properties panel both read these names verbatim.
""",
	},
	{
		"skill_name": FRONTEND_SKILL,
		"description": (
			"The house style this front end is written in: frappe-ui components over raw markup, "
			"Vue script-setup conventions, Tailwind tokens for colour, frappeRequest for data, "
			"frappe.ui.form.on for desk scripts, and the file-size discipline that keeps a component "
			"from growing without bound. Use this skill before writing or editing any Vue component "
			"or Frappe desk JavaScript file. Do NOT use it for a change that touches no front-end "
			"file."
		),
		"body": """# How the front end here is written

- frappe-ui components rather than raw markup: Button, FormControl with type select, Dialog. A hand-rolled control re-implements focus, keyboard handling and dark mode, worse.
- Vue uses script setup. Prefer computed over methods, clean up listeners in onBeforeUnmount, never put v-if and v-for on one element, never write v-for without a key.
- Colours come from Tailwind tokens, never hex literals.
- Fetch data with frappeRequest. Do not introduce fetch or axios.
- Desk scripts use frappe.ui.form.on and match the siblings in their folder.
- Components here are already large. Leave a file the same size or smaller; past about three hundred lines of script, extract something instead.
""",
	},
]


def _upsert_skill(skill):
	name = frappe.db.get_value("AI Skill", {"skill_name": skill["skill_name"]}, "name")
	if name:
		doc = frappe.get_doc("AI Skill", name)
		changed = False
		if doc.description != skill["description"]:
			doc.description = skill["description"]
			changed = True
		if doc.body != skill["body"]:
			doc.body = skill["body"]
			changed = True
		if doc.status == "Draft":
			doc.status = "Active"
			changed = True
		if changed:
			doc.save(ignore_permissions=True)
		return
	doc = frappe.get_doc({
		"doctype": "AI Skill",
		"skill_name": skill["skill_name"],
		"status": "Active",
		"description": skill["description"],
		"body": skill["body"],
	})
	doc.insert(ignore_permissions=True)


def _enable_skill(config_name, skill_name):
	existing = frappe.db.get_value(
		"AI Agent Enabled Skill",
		{"parenttype": "AI Agent Configuration", "parent": config_name, "skill": skill_name},
		"name",
	)
	if existing:
		return
	last_idx = frappe.db.count(
		"AI Agent Enabled Skill", {"parenttype": "AI Agent Configuration", "parent": config_name}
	)
	row = frappe.get_doc({
		"doctype": "AI Agent Enabled Skill",
		"parent": config_name,
		"parentfield": "enabled_skills",
		"parenttype": "AI Agent Configuration",
		"skill": skill_name,
		"idx": last_idx + 1,
	})
	row.insert(ignore_permissions=True)


# ── ProsAlly: the exact text prosally_lane_fidelity.py left behind ──

GEN_STEP0_OLD = """=== STEP 0 — LANES THE DESIGNER NAMED WIN, ALWAYS ===

If the request names the lanes — "3 lanes only: Recruiter, GRD Operator, GRD
Manager", "lanes are Employee, Manager, HR", "swimlanes: Customer and Support" —
then the "lanes" array is EXACTLY that list, in that order.

  • Do not add a lane. Do not rename one. Do not drop one.
  • In particular do NOT add a "System (Automatic)" lane. If the designer did not
    name it, it does not exist.
  • Automated steps still have to live somewhere: put each one in the lane of the
    role responsible for it — whoever triggers it, or whoever acts on its result.
    An email to the recruiter after the GRD Operator submits belongs to the GRD
    Operator; a validation that runs while the Recruiter fills the form belongs
    to the Recruiter.
  • The count the designer states is the count you output. "3 lanes only" means
    three.

Only when the request does NOT name the lanes do you identify the actors
yourself — that is STEP 1 below.

"""
GEN_STEP0_NEW = """=== STEP 0 — LOAD THE SKILL FIRST ===

Call load_skill with `bpmn-modelling-rules-and-ir-schema` before you build or rebuild any diagram.
It holds the lane-fidelity rule (a designer-named lane set is authoritative), where an automated
step's lane comes from, the rework-loop convergence rule and the IR/element schema this tool must
output. Apply what it says, then call build_diagram.

"""

GEN_S3_OLD = (
	'S3  When the designer has NOT named the lanes, all automated steps (send email,\n'
	'    check records, validate, calculate, create/update doc) belong in a dedicated\n'
	'    "System (Automatic)" lane, separate from human lanes. When the designer HAS\n'
	'    named the lanes, there is no such lane unless they named it — each automated\n'
	'    step goes in the lane of the role responsible for it.\n'
)
GEN_S3_NEW = 'S3  Automated-step lane assignment: see the bpmn-modelling-rules-and-ir-schema skill.\n'

GEN_FALLBACK_OLD = (
	'If you cannot identify 2 human roles, use "User" + "System (Automatic)" —\n'
	'but only when the designer has NOT named the lanes. A named lane set is used\n'
	'exactly as given, whatever its size.\n'
)
GEN_FALLBACK_NEW = (
	'If you cannot identify 2 human roles, use "User" + "System (Automatic)" (see the\n'
	'bpmn-modelling-rules-and-ir-schema skill for when this applies).\n'
)

GEN_STEP1_BULLET_OLD = (
	'  • Any automated step (send email, validate, calculate, check, create record,\n'
	'    notify) → "System (Automatic)" — this step applies only when the designer\n'
	'    named no lanes, so the system lane is yours to add here\n'
)
GEN_STEP1_BULLET_NEW = (
	'  • Automated-step lane assignment: see the bpmn-modelling-rules-and-ir-schema skill\n'
)

GEN_MIN_OLD = (
	'  • Minimum: when only one human is mentioned, add a second lane for the\n'
	'    automated steps — again, only where the designer named no lanes\n'
)
GEN_MIN_NEW = '  • Minimum-lane fallback: see the bpmn-modelling-rules-and-ir-schema skill\n'

REWORK_RULE_OLD = """

=== REWORK LOOPS — ONE RE-ENTRY POINT ===

Approval processes send work back: rejected, changes requested, resubmit,
re-check, awaiting quota. When several outcomes return the work to the SAME
stage, route them all into ONE re-entry point — a single join gateway in front of
that stage — instead of drawing a separate return from each rejection.

One shared re-entry:
  gw_pam_reject, gw_moi_reject, gw_mgr_reject  →  gw_back_to_operator  →  task_operator_revise

not three separate flows from three rejection points back across the diagram.

This is how a business reader expects to see rework, and it is also what keeps
the drawing legible: every separate return is a line running the full width of
the diagram, crossing every flow that changes lane along the way.
"""
REWORK_RULE_NEW = (
	"\n\nSKILLS: the bpmn-modelling-rules-and-ir-schema skill also has the rework-loop "
	"convergence rule — load it before drawing a rejection or resubmit path.\n"
)

MOD_OLD = (
	'  LANES THE DESIGNER NAMED WIN: if the request names the lanes, the "lanes"\n'
	'  array is exactly that list — nothing added, renamed or dropped, and no\n'
	'  "System (Automatic)" lane unless they asked for one.\n'
	'  Otherwise keep the lanes the current XML already has.\n'
	'  Role identification: any named person/team gets their own lane.\n'
	'  Automated steps → the "system" lane when one exists; when there is none,\n'
	'  the lane of the role responsible for the step.\n'
	'  Assign: userTask → person\'s lane id; scriptTask/serviceTask → the system\n'
	'  lane if there is one, else the responsible role\'s lane;\n'
)
MOD_NEW = (
	'  LANE AND REWORK RULES: load the bpmn-modelling-rules-and-ir-schema skill before\n'
	'  touching lanes — a designer-named lane set is authoritative, and it has the\n'
	'  automated-step and rework-loop rules too.\n'
	'  Assign: userTask → person\'s lane id; scriptTask/serviceTask → the system\n'
	'  lane if there is one, else the responsible role\'s lane;\n'
)


def _reduce_prosally():
	if not frappe.db.exists("AI Agent Configuration", PROSALLY_CONFIG_NAME):
		return

	doc = frappe.get_doc("AI Agent Configuration", PROSALLY_CONFIG_NAME)
	by_id = {sp.sub_agent_id: sp for sp in (doc.sub_prompts or [])}
	generator = by_id.get("process_generator")
	modifier = by_id.get("modifier")

	if generator:
		gen = generator.prompt_text or ""
		if BPMN_SKILL not in gen:
			gen_edits = [
				(GEN_STEP0_OLD, GEN_STEP0_NEW),
				(GEN_S3_OLD, GEN_S3_NEW),
				(GEN_FALLBACK_OLD, GEN_FALLBACK_NEW),
				(GEN_STEP1_BULLET_OLD, GEN_STEP1_BULLET_NEW),
				(GEN_MIN_OLD, GEN_MIN_NEW),
				(REWORK_RULE_OLD, REWORK_RULE_NEW),
			]
			applied = 0
			for old, new in gen_edits:
				if old in gen:
					gen = gen.replace(old, new, 1)
					applied += 1
			if applied:
				generator.db_set("prompt_text", gen, update_modified=False)
			else:
				frappe.log_error(
					title="seed_prosally_and_frontend_skills: process_generator anchors not found",
					message="None of the expected lane/rework passages matched; prompt left as-is.",
				)

	if modifier:
		mod = modifier.prompt_text or ""
		if BPMN_SKILL not in mod:
			mod_edits = [
				(MOD_OLD, MOD_NEW),
				(REWORK_RULE_OLD, REWORK_RULE_NEW),
			]
			applied = 0
			for old, new in mod_edits:
				if old in mod:
					mod = mod.replace(old, new, 1)
					applied += 1
			if applied:
				modifier.db_set("prompt_text", mod, update_modified=False)
			else:
				frappe.log_error(
					title="seed_prosally_and_frontend_skills: modifier anchors not found",
					message="None of the expected lane/rework passages matched; prompt left as-is.",
				)

	_enable_skill(doc.name, BPMN_SKILL)


# ── Frontend Agent: the exact block from seed_frontend_agent_config.py ──

FRONTEND_BLOCK_OLD = """HOW THE FRONT END HERE IS WRITTEN
- frappe-ui components rather than raw markup: Button, FormControl with type select, Dialog. A hand-rolled control re-implements focus, keyboard handling and dark mode, worse.
- Vue uses script setup. Prefer computed over methods, clean up listeners in onBeforeUnmount, never put v-if and v-for on one element, never write v-for without a key.
- Colours come from Tailwind tokens, never hex literals.
- Fetch data with frappeRequest. Do not introduce fetch or axios.
- Desk scripts use frappe.ui.form.on and match the siblings in their folder.
- Components here are already large. Leave a file the same size or smaller; past about three hundred lines of script, extract something instead."""

FRONTEND_BLOCK_NEW = """SKILLS: the index the platform shows lists what you can load with the load_skill tool. Load `frontend-house-style` before you write or edit any Vue component or Frappe desk JavaScript file; it holds the component, styling and sizing conventions this front end follows."""


def _reduce_frontend_agent():
	if not frappe.db.exists("AI Agent Configuration", FRONTEND_AGENT_NAME):
		return

	doc = frappe.get_doc("AI Agent Configuration", FRONTEND_AGENT_NAME)
	prompt = doc.system_prompt or ""
	if FRONTEND_SKILL not in prompt and FRONTEND_BLOCK_OLD in prompt:
		prompt = prompt.replace(FRONTEND_BLOCK_OLD, FRONTEND_BLOCK_NEW, 1)
		doc.db_set("system_prompt", prompt, update_modified=False)
	elif FRONTEND_SKILL not in prompt:
		frappe.log_error(
			title="seed_prosally_and_frontend_skills: Frontend Agent house-style block not found",
			message="The 'HOW THE FRONT END HERE IS WRITTEN' block no longer matches; prompt left as-is.",
		)

	_enable_skill(doc.name, FRONTEND_SKILL)


def execute():
	for skill in SKILLS:
		_upsert_skill(skill)

	_reduce_prosally()
	_reduce_frontend_agent()
