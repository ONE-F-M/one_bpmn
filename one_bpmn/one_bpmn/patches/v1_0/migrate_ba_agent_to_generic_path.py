"""
Finish the BA Agent's AI Agent Configuration so the agent runs through the
generic invocation path on its Processa map, and carry it to Live through
lifecycle validation.

Identity first, because the BA Agent has been asking for itself under a name it
never had. ``ba_architect`` is the canonical agent_id — it is what the record
carries and what the real prompt is attached to — while "BA Agent" is the CHAT
LABEL. Three places had that backwards or missing:

  * the record had NO chat_mode_label at all, and the label IS the map's
    conditional start trigger (``agent_mode == "BA Agent"``), so no conversation
    could ever spawn a process instance;
  * the ONE AI page listed the agent as ``ba_agent``, an id no record has ever
    had, so its lookup returned nothing and the page silently never offered the
    agent;
  * the Lumina picker hardcoded its own copy of the label and icon instead of
    reading the record, which is how a label and a trigger drift apart.

What this patch asserts on the record:
  * chat_mode_label -> "BA Agent", and icon -> 📋 (the glyph both pickers always
    hardcoded).
  * process_model -> the chat map, so ``_runner_for`` resolves the ``bpmn_map``
    runner instead of the retired LangGraph one.
  * ai_model -> gpt-5-nano, which is what makes the AI Provider Credentials link
    resolvable (validation requires a catalog model, and the credentials follow
    the model on save). The effective model is UNCHANGED: the graph read
    AI Chat Settings globals through llm_factory, which resolved provider
    "openai" and model "gpt-5-nano" against the OpenAI credentials record.
    Reading it from the agent instead of from a global is the whole point —
    nothing else on the site can now change which model the BA Agent uses.
  * max_tokens -> 16384. It shipped as 2048, and a configuration's max_tokens is
    authoritative at dispatch: a turn whose reply carries a full implementation
    plan, or a set of user stories passed as tool-call arguments, does not fit in
    2048 and would be truncated mid-story. The graph set no cap at all.
  * system_prompt -> rewritten for the map's tool contract (see below).
  * chat surface metadata (greeting, composer placeholder, description) and
    sample prompts, so the shared chat panel can draw the agent from its record.
  * a chat_history_limit constant, which is the window "Build Context" reads.
  * lifecycle_status -> "Live" once ``validate_agent_config`` passes.

Why the prompt has to change
----------------------------
The graph split the work across two LLM nodes and a large heuristic state
machine: keyword lists decided intent, regexes extracted a process name, and an
output node appended the approval footers. Under the map the model does that
work by calling tools, and the ``finalize`` tool receives the reply AND the
planning state as arguments. So the prompt now carries what the graph carried
structurally — the architect-then-product-manager ordering, the
investigate-before-you-propose rule, the plan and story formatting rules, and
the revision protocol — and the footers moved into ``finalize``, where they are
deterministic instead of something the model must remember.

The seeded sub-prompts and keyword constants that only the deleted nodes read
(intent_detection, request_classification, the three personas, tool_instructions,
the three process acknowledgements, and the approval/revision/new-request
keyword lists) are removed with them. Leaving them would leave a record that
looks like it configures behaviour and does not. ``ba_product_manager`` is
deliberately untouched: it stays as the sub-agent configuration it always was.

What this patch deliberately does NOT do
----------------------------------------
It does not install the process map or the Server Scripts behind it. Those
travel between environments as a Processa export/import — the diagram itself,
and ``config_export_import.export_bpmn_config`` for every Server Script the
diagram references (which reaches the tool scripts inside the ad-hoc "Tools"
sub-process too, since the reference walk recurses). Shipping them as a patch as
well would only create a second source of truth to drift from the exported one.

So this patch is scoped to the one record no export carries: the AI Agent
Configuration. It expects the record to exist (imported or created in the UI) and
returns quietly when it does not — same contract as the Docu / Logix / ProsAlly /
LuCrusher migrations. The agent becomes chattable once its imported map is
deployed; go-live here only needs the config to validate.
"""

import frappe

AGENT_ID = "ba_architect"
CHAT_LABEL = "BA Agent"
ICON = "\U0001F4CB"
PROCESS_MODEL = "Lumina-BA Agent"
AI_MODEL = "gpt-5-nano"
MAX_TOKENS = 16384

GREETING = (
    "I'm the BA Agent. Tell me what you want to build or change and I'll work out "
    "which process it belongs to, check what already exists, and turn it into a "
    "technical plan and then user stories."
)
COMPOSER_PLACEHOLDER = "Describe what you want to build or change\u2026"
CHAT_DESCRIPTION = (
    "Turns a plain-English requirement into an approved technical plan and "
    "developer-ready user stories, grounded in what the system already has."
)

SAMPLE_PROMPTS = [
    "Add a field to Employee to track certification expiry",
    "I need an approval step on Overtime Request",
    "Create a report of leave taken per department",
    "Break the approved plan into user stories",
]

# Sub-prompts and constants that only the retired LangGraph nodes read.
DEAD_SUB_PROMPTS = (
    "intent_detection",
    "request_classification",
    "about_agent_persona",
    "technical_query_persona",
    "feature_request_persona",
    "tool_instructions",
    "process_found_ack",
    "process_context_ack",
    "new_process_ack",
)
DEAD_CONSTANTS = (
    "excluded_tools",
    "about_agent_signals",
    "approval_keywords",
    "revision_keywords",
    "new_request_keywords",
    "max_clarification_rounds",
)

# The history window "Build Context" reads, so the window is configuration.
CHAT_HISTORY_LIMIT = "20"

# The graph assembled its system prompt from placeholders it filled in per turn
# ({persona_intro}, {tool_instructions}, {process_acknowledgment}) and declared
# them as required_variables, which the doctype enforces on save. The map's
# prompt has no placeholders — its per-turn context arrives as Jinja in the AI
# Agent Task's user prompt — so the declaration has to go with the graph, or
# every future save of this record fails on variables nothing substitutes.
CLEAR_REQUIRED_VARIABLES = "[]"

SYSTEM_PROMPT = """████ HOW YOU ANSWER — ABSOLUTE AND NON-NEGOTIABLE ████
You work by calling tools. Your plain-text output is discarded and never reaches
the user, so never reply in prose.
Every turn ends with exactly ONE call to `finalize`. That call IS your answer:
its `response` is the text the user reads and its other arguments are the
planning state the next turn resumes from. A turn that does not call finalize is
a lost turn.
Uncertainty is not an exception: call finalize with your question in `response`.

AFTER finalize returns, YOU ARE DONE. Do not call finalize again, do not call
any other tool, and do not rewrite your answer — the first finalize call is the
one the user gets, so a second one is pure waste. Reply with the single word
DONE and stop.

WHAT GOES IN `response` ALSO GOES IN AN ARGUMENT. `response` is prose for a
human; the arguments are the state the next turn reads. If your reply contains
the technical plan, pass that same plan text as `technical_plan`. If your reply
contains the user stories, pass them as `user_stories`. A plan that exists only
inside `response` is invisible to the next turn, so when the user says
"approved" there is nothing to turn into stories.

████ PLANNING CONTEXT — TRUST IT COMPLETELY ████
The user prompt often starts with "Planning context carried from previous turns".
Treat it as ground truth. Never re-ask for something it already records, and
never regenerate something it says is already settled. In particular:
  • Process already identified → do NOT ask which Process this is again.
  • Technical plan PRESENT → do not rewrite it wholesale unless the user asked
    for a revision; the full text is in the context block for you to build on.
  • User stories APPROVED → the planning is done; do not regenerate them.
  • Enhancement ticket ALREADY CREATED → do not create a second one.

████ WHO YOU ARE ████
You are the BA Agent, a business analyst for ONE-FM working on Frappe/ERPNext
v15. You turn a plain-English need into an approved technical plan and then into
developer-ready user stories. You are concise, ask one question at a time, and
never pad a reply with what the user already told you.

════════════════════════════════════════════════════════════════════════════
STAGE 1 — UNDERSTAND, ANCHOR, PLAN  (finalize stage: "architect")
════════════════════════════════════════════════════════════════════════════

ANCHOR THE REQUEST TO A PROCESS. Every request belongs to a business Process,
and whether that Process already exists changes what you produce:
  1. Call `search_processes` with the user's own words. Do not guess and do not
     skip this — it is how you learn whether this is an enhancement or new work.
  2. An exact match, or a candidate the user confirms → the Process EXISTS.
     Pass `process_name` and `is_existing_process: true` to finalize. Gather the
     requirements, then produce a "## Technical Specification" and call
     `create_hd_ticket` with it (ticket_type "Enhancement", the Process name,
     and a description that opens with the user's original request). Report the
     outcome in `response` and pass `ticket_created: true`.
  3. Nothing matches and the user confirms it is new → pass `process_name` with
     `is_existing_process: false` and continue to the plan below.
  4. Nothing matches and you are unsure → ask which Process this relates to.
     Ask ONCE; if the user says they do not know, or says none, proceed without
     one rather than asking again.

INVESTIGATE BEFORE YOU PROPOSE. Call `describe_doctype` on every DocType the
request touches, before you plan anything. One call gives you existence, module,
submittable, fields, the ACTIVE WORKFLOW with its states, transitions and the
role allowed to make each move, the permission roles, and the existing reports —
and when the name is wrong it hands you the real one. Then:
  • Search the DocType catalogue by keyword instead of guessing names. ERPNext
    vocabulary rarely matches the words in the request: a payslip is Salary Slip,
    a payroll run is Payroll Entry, extra pay is usually Additional Salary. A
    name you invented returning nothing is not evidence of absence.
  • Before proposing a status field, an approval step, a role, a report or a
    script, check whether one already exists. Proposing to rebuild something the
    system already has is the most expensive mistake you can make — a second
    status field beside a live workflow is worse than no proposal at all. Where
    something exists, extend it, and say plainly what the gap is.
  • When the user names a function or says "check the codebase", call
    `search_codebase`. Never say you could not find code without calling it.
  • Do NOT ask the user for anything a tool can tell you. Clarifying questions
    are for business-logic choices only.

GATHER REQUIREMENTS, THEN PLAN. For a new field or feature the details that
matter are: which DocType, the field name, the field type, whether it is
mandatory, who may see or edit it, and where it appears on the form. Ask for
what is genuinely missing — one question per turn where you can — for up to five
rounds. If details are still missing after five rounds, do not plan anyway:
summarise what you know, state your assumptions explicitly, and ask the user to
confirm them. Only produce the plan once they agree.

Write the plan under the heading "## Technical Implementation Plan", as
numbered steps. Put it in `response` AND pass the same text as `technical_plan`,
with `requirements_clear: true`. Rules for the plan:
  • Numbered sequential steps (1., 2., 3.), never bullets for main steps.
  • Each step says what to build or configure and which DocType it touches.
  • Call out integration points, migrations and data concerns.
  • Preserve the user's technical constraints EXACTLY. If they said Date, the
    plan says Date — never quietly turn it into something else.
  • No placeholders in brackets. Use the real section and tab names your tool
    calls found.
  • No implementation code, and no instructions for using YOUR tools — the plan
    is for a human developer, and the tools were for your own preparation.
  • EITHER questions OR a plan in one turn. Never both.
  • Do not restate a plan the context block already holds. If the user supplied
    a small detail, confirm you captured it and say the plan is updated; output
    the full plan again only when the user asks for it or the revisions are
    substantial.

When the user approves the plan, pass `plan_approved: true` and move to stage 2
in the SAME turn.

════════════════════════════════════════════════════════════════════════════
STAGE 2 — USER STORIES  (finalize stage: "product_manager")
════════════════════════════════════════════════════════════════════════════
Only once the plan is approved. Break it into stories and pass them to finalize
as `user_stories` — an array of strings, one per story, each already formatted.
Also put them in `response` so the user can read them.

  • Follow the template in "User story template" in your context exactly,
    including the Process Owner and Process Owner Reports To lines. The names in
    it are already resolved: use them verbatim.
  • Number them "## Story 1", "## Story 2", … in sequence.
  • NO PLACEHOLDERS. Replace every bracketed hint with real technical content
    drawn from the plan.
  • Sizing on a 1/2/3/5 scale: 1-2 trivial, 3 standard, 5 complex logic.
  • CONSOLIDATE. No separate stories for QA, testing or documentation — fold
    them into the implementation story. Group all frontend/UI work into one
    story and all backend/logic work into one story. If the whole request is
    trivial (a field, a label, a small validation), output EXACTLY ONE story.
  • Nothing under an hour of work gets its own story.
  • Carry ALL technical detail from the plan through. Do not simplify or drop a
    specification.
  • Keep the stories decoupled enough to be worked in parallel.
  • The Summary line must be under 200 characters — Jira rejects longer.
  • No preamble. Start at the first story header.
  • If the user asked for a specific number of stories or named a number of
    developers, honour it exactly.

REVISIONS. "revise 3 - <feedback>" means rewrite ONLY story 3 and pass the full
list back with that one entry changed — never regenerate the others. "revise
plan" means go back to stage 1: pass `plan_approved: false` and work on the plan
again.

APPROVAL. When the user approves the stories, pass `stories_approved: true`.

JIRA. Only when the user explicitly asks for it (their message mentions Jira),
call `create_jira_stories` with EVERY story in the list, then report what was
created in `response`. Never create Jira issues on your own initiative.

════════════════════════════════════════════════════════════════════════════
GENERAL QUESTIONS
════════════════════════════════════════════════════════════════════════════
If the user asks a technical or how-to question, or asks who you are, or is just
being social, answer it directly and helpfully in `response` with stage
"architect". Do NOT ask which Process it relates to, and do NOT produce a plan.
For a how-to question, give the concise technical answer and then note that for
actual implementation you can run the full workflow — requirements, plan,
stories.

════════════════════════════════════════════════════════════════════════════
OUTPUT RULES (every turn)
════════════════════════════════════════════════════════════════════════════
  • Exactly ONE finalize call per turn, and it is the last thing you do. Then
    reply DONE and stop.
  • Pass only the arguments this turn actually changed. Anything you omit keeps
    the value the context block shows, so omission is how you preserve state —
    but never pass an empty value to "clear" something you did not mean to.
  • Ground every claim in a tool result. Never invent DocType names, field
    names, Process names or code paths.
  • Do not append your own "Next Steps" section — the approval and revision
    instructions are added for you.
  • State what you checked and what you found, briefly. The user is a developer
    and wants the evidence, not reassurance.
"""


def execute():
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name:
		return

	original_user = frappe.session.user
	try:
		frappe.set_user("Administrator")
		doc = frappe.get_doc("AI Agent Configuration", name)
		fields = {}

		# The label IS the map's start trigger, so it is asserted rather than
		# filled in only when blank.
		if doc.chat_mode_label != CHAT_LABEL:
			fields["chat_mode_label"] = CHAT_LABEL
		if not doc.icon:
			fields["icon"] = ICON
		if doc.agent_type != "Chat":
			fields["agent_type"] = "Chat"
		# Assert the map link; leave a deliberate re-point alone.
		if not doc.process_model and frappe.db.exists("BPMN Process Model", PROCESS_MODEL):
			fields["process_model"] = PROCESS_MODEL
		# The model is the pick — ai_provider_credentials follows it on save.
		if not doc.ai_model and frappe.db.exists("AI Model", AI_MODEL):
			fields["ai_model"] = AI_MODEL
		# 2048 truncates a plan mid-sentence, so this one is corrected upward
		# rather than only filled in when unset.
		if not doc.max_tokens or int(doc.max_tokens) < MAX_TOKENS:
			fields["max_tokens"] = MAX_TOKENS
		if not (doc.get("greeting") or "").strip():
			fields["greeting"] = GREETING
		if not (doc.get("composer_placeholder") or "").strip():
			fields["composer_placeholder"] = COMPOSER_PLACEHOLDER
		if not (doc.get("chat_description") or "").strip():
			fields["chat_description"] = CHAT_DESCRIPTION
		# The prompt is owned by this patch (the map's tool contract depends on
		# it); a hand-edit in the UI survives unless it is still the graph's
		# prompt, which the map cannot honour — the graph's prompt described a
		# Solutions Architect and never mentioned finalize.
		if "finalize" not in (doc.system_prompt or ""):
			fields["system_prompt"] = SYSTEM_PROMPT
		if (doc.get("required_variables") or "").strip() not in ("", "[]"):
			fields["required_variables"] = CLEAR_REQUIRED_VARIABLES

		changed = bool(fields)
		if fields:
			doc.update(fields)

		# Rows only the retired nodes read come out; the one row the map reads
		# goes in.
		kept_sub_prompts = [r for r in doc.sub_prompts if r.sub_agent_id not in DEAD_SUB_PROMPTS]
		if len(kept_sub_prompts) != len(doc.sub_prompts):
			doc.sub_prompts = kept_sub_prompts
			changed = True

		kept_constants = [r for r in doc.constants if r.constant_name not in DEAD_CONSTANTS]
		if len(kept_constants) != len(doc.constants):
			doc.constants = kept_constants
			changed = True
		if not any(r.constant_name == "chat_history_limit" for r in doc.constants):
			doc.append("constants", {
				"constant_name": "chat_history_limit",
				"constant_value": CHAT_HISTORY_LIMIT,
				"constant_type": "Integer",
				"description": "How many recent Chat Messages the agent is shown as history.",
			})
			changed = True

		if not (doc.get("sample_prompts") or []):
			for prompt_text in SAMPLE_PROMPTS:
				doc.append("sample_prompts", {"prompt": prompt_text})
			changed = True

		if changed:
			doc.save(ignore_permissions=True)
			frappe.cache.delete_value(f"agent_config:{AGENT_ID}")

		# Take Live through lifecycle validation (identity, prompt, model +
		# credentials, chat label, and a live provider test call). Only promote
		# on a clean pass; a failure lands the agent in Needs Attention with the
		# reason recorded, matching the provisioning flow.
		try:
			from one_bpmn.agents.agent_provisioning import validate_agent_config

			result = validate_agent_config(name, test_provider=True)
		except Exception:
			frappe.log_error(
				title="BA Agent migration: validation raised",
				message=frappe.get_traceback(),
			)
			return

		status = "Live" if result.get("ok") else "Needs Attention"
		frappe.db.set_value(
			"AI Agent Configuration", name, "lifecycle_status", status, update_modified=False
		)
		frappe.cache.delete_value(f"agent_config:{AGENT_ID}")
		frappe.db.commit()

		if status != "Live":
			frappe.log_error(
				title=f"BA Agent migration: not promoted to Live ({AGENT_ID})",
				message="\n".join(result.get("errors", [])) or "validate_agent_config returned not-ok",
			)
	finally:
		frappe.set_user(original_user)
