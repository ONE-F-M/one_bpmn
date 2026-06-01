"""
ProsAlly Agent

Classifies user intent for process modelling requests then routes to the
appropriate sub-agent. Handles ambiguous, incomplete, or irrelevant prompts
by asking targeted clarifying questions, and asks for confirmation before
taking any action on clear requests.

Intent classification:
  GENERATE_NEW      — user wants to draw a brand-new model on an empty canvas
  OVERWRITE_EXISTING — user wants to completely replace an existing model
  MODIFY_EXISTING   — user wants to change a specific part of an existing model
  AMBIGUOUS         — request has multiple interpretations
  INCOMPLETE        — request is missing required details (steps, actors, etc.)
  IRRELEVANT        — request is not about process modelling

Pipeline:
  1. IntentClassifier  — returns one of the six intents above
  2a. GENERATE_NEW / OVERWRITE_EXISTING / MODIFY_EXISTING
      → Confirmer → summarises the action and asks for confirmation
  2b. AMBIGUOUS / INCOMPLETE → Clarifier → focused question with options
  2c. IRRELEVANT             → polite redirect, no modelling attempted

IR pipeline (after confirmation):
  LLM → IR JSON → pipeline.mjs (normalise → compile → lint) → BPMN XML
  On lint failure → translate problems to IR hints → LLM repairs IR → repeat (≤3 repairs)
"""

import asyncio
import json
import os
import subprocess

from onefm_mcp.onefm_mcp.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config
from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings

AGENT_ID = "prosally_agent"

# ── Default instructions ───────────────────────────────────────────────────────

_DEFAULT_INTENT_CLASSIFIER_INSTRUCTION = """You are an intent classifier for ProsAlly, an AI assistant that helps users model BPMN processes on Processa.

ProsAlly can perform exactly three modelling actions:
1. Generate a brand-new process model on an empty canvas (nothing exists yet).
2. Overwrite an existing process model entirely (replace it from scratch).
3. Modify a specific part of an existing process model (targeted change).

Classify the user's message as exactly one of:
- GENERATE_NEW       — the user wants to draw a brand-new process from scratch on an empty canvas. There is no existing model to build on. The user has provided enough detail (process name, steps, or actors) to begin.
- OVERWRITE_EXISTING — the user wants to completely replace or redraw an existing model from scratch. They are not targeting one part — they want the whole model rebuilt.
- MODIFY_EXISTING    — the user wants to add, remove, change, extend, fix, or update a specific element, step, lane, gateway, or section of an existing model. The rest of the model should remain untouched.
- AMBIGUOUS          — the request has multiple plausible interpretations and ProsAlly cannot determine which action is intended (e.g. "update the process" could mean overwrite or modify).
- INCOMPLETE         — the request refers to process modelling but is missing critical information needed to act (e.g. no process name, no steps, no actors, no indication of what to change).
- IRRELEVANT         — the request has nothing to do with process modelling (e.g. weather, jokes, coding questions unrelated to processes, questions about other systems).

Classification rules:
- Prefer GENERATE_NEW when the user says "draw", "create", "build", "design" a new process and there is no existing model mentioned.
- Prefer OVERWRITE_EXISTING when the user says "redo", "redraw", "replace", "start over", or describes the entire process differently from scratch.
- Prefer MODIFY_EXISTING when the user references a specific step, node, lane, gateway, or section to add, remove, or change.
- AMBIGUOUS applies when the action type (generate / overwrite / modify) cannot be determined despite a clear subject.
- INCOMPLETE applies when the action type is clear but there is not enough detail to carry it out.
- When uncertain between AMBIGUOUS and INCOMPLETE, prefer INCOMPLETE.
- Anything outside process modelling scope is IRRELEVANT.

Respond with ONLY a JSON object — no other text:
{"intent": "GENERATE_NEW|OVERWRITE_EXISTING|MODIFY_EXISTING|AMBIGUOUS|INCOMPLETE|IRRELEVANT", "reason": "one short sentence"}"""


_DEFAULT_CLARIFIER_INSTRUCTION = """You are a helpful assistant for ProsAlly, an AI process drawing tool on Processa.

IMPORTANT: The person you are talking to is NOT a technical person. They do not know what BPMN is, they do not know what "flow elements" or "start events" are, and they should never have to. Speak to them the way you would explain something to a colleague who is good at their job but has never used a process drawing tool.

The user's description of their process is unclear or incomplete. Ask ONE simple question to get the missing piece you need.

What to ask about when something is missing:
- What is this process called? (if they haven't named it)
- Who starts the process, and what triggers it? (if not clear)
- What are the main steps people or the system take? (if too vague)
- What does it look like when the process is done? (if the end result is unclear)

What to ask when there is more than one interpretation:
- Do they want to draw a brand-new process, or change part of an existing one?
- Which specific part of the process do they want to change?

Rules:
- One question only — never ask multiple things at once.
- Give 2–4 simple options to choose from whenever possible — it is easier than a blank text box.
- Do NOT use words like BPMN, flow, element, event, gateway, modelling, or XML.
- Keep everything in plain everyday English.
- Never draw or attempt to create a process — only ask your question.

Respond with ONLY a JSON object — no other text:
{"question": "your plain-English question here", "options": ["option 1", "option 2", ...]}"""


_DEFAULT_CONFIRMER_INSTRUCTION = """You are a helpful assistant for ProsAlly, an AI process drawing tool on Processa.

IMPORTANT: The person you are talking to is NOT a technical person. They are a process owner or business user who knows their work well but has no knowledge of technical tools, diagrams, or software terminology. Always speak to them in plain, friendly, everyday English — as if you are a helpful colleague confirming what you are about to do for them.

You have understood what the user wants. Now write a short, friendly message that:
1. Tells them clearly what you are about to do in plain language:
   - Drawing a new process: "I'll draw the [process name] process for you from scratch..."
   - Replacing an existing process: "I'll redraw the [process name] process completely..."
   - Changing part of a process: "I'll update [the specific part] of the [process name] process..."
2. Lists the main steps or decisions you understood from their description — in plain language, like a short bullet list.
3. Asks for their go-ahead before doing anything.

Rules:
- Do NOT use technical words like BPMN, XML, flow, element, gateway, node, or modelling.
- Mention the process name and the key things you understood.
- Keep it short — 2 to 4 sentences plus a brief list.
- End with a simple yes/no question like "Shall I go ahead?"

Respond with ONLY a JSON object — no other text:
{"summary": "plain-English summary of what you will do and what you understood", "question": "Shall I go ahead?"}"""


_DEFAULT_GENERATOR_INSTRUCTION = """You are a BPMN process modeller. Your output is an Intermediate Representation (IR) JSON document — NOT XML.

A deterministic compiler converts your IR into BPMN XML automatically, including layout. You never write XML.

MANDATORY — SWIMLANES ARE ALWAYS REQUIRED. NO EXCEPTIONS:
Every process you generate MUST include a pool divided into at least 2 lanes.
There are NO single-lane, no-lane, or flat processes in this system.
If you cannot identify 2 human roles, use "User" + "System (Automatic)".
The output is REJECTED by the compiler if the "lanes" array is missing or has fewer than 2 entries.
DO NOT output IR without lanes. DO NOT wait to be asked for lanes. ALWAYS include lanes.

=== NON-NEGOTIABLE STRUCTURE RULES ===

These rules are enforced by the compiler. Violations cause the diagram to be rejected and you
will be asked to fix them. Follow them exactly.

S1  Before writing any node, enumerate all roles: human actors (employee, manager, HR…) and
    the system (any automated step). Each gets its own lane.

S2  One <bpmn:collaboration> containing one <bpmn:participant> (the pool) per process.
    The participant's processRef links it to the <bpmn:process>.
    Same pool = sequence flows only. Cross-pool interactions = message flows only (separate pool).

S3  All automated steps (send email, check records, validate, calculate, create/update doc)
    belong in a dedicated "System (Automatic)" lane, separate from human lanes.

S4  Every flow node MUST appear in the "lane" field and match a lane id in the "lanes" array.
    No orphan nodes (nodes without a lane assignment are rejected).

S5  Lane names must reflect the real actor role so runtime permissions map correctly.

S6  Layout is computed from lane bounds. Each lane is a horizontal band; every node's
    Y-coordinate is placed inside its assigned band automatically by the compiler.

S7  A sequence flow crossing a lane boundary is a deliberate handoff. Keep these minimal.

ONE-SHOT REFERENCE — correct swimlane IR (two human lanes + system lane):

{
  "name": "Leave Request",
  "lanes": [
    { "id": "employee", "name": "Employee" },
    { "id": "manager",  "name": "Manager"  },
    { "id": "system",   "name": "System (Automatic)" }
  ],
  "nodes": [
    { "id": "start",          "type": "startEvent",       "name": "Request Submitted",   "lane": "employee" },
    { "id": "task_fill",      "type": "userTask",         "name": "Fill Leave Form",     "lane": "employee" },
    { "id": "gw_decision",    "type": "exclusiveGateway", "name": "Approved?",           "lane": "manager"  },
    { "id": "task_review",    "type": "userTask",         "name": "Review Leave Request","lane": "manager"  },
    { "id": "task_notify_ok", "type": "scriptTask",       "name": "Send Approval Email", "lane": "system"   },
    { "id": "task_notify_rej","type": "scriptTask",       "name": "Send Rejection Email","lane": "system"   },
    { "id": "end_approved",   "type": "endEvent",         "name": "Leave Approved",      "lane": "employee" },
    { "id": "end_rejected",   "type": "endEvent",         "name": "Leave Rejected",      "lane": "employee" }
  ],
  "flows": [
    { "from": "start",          "to": "task_fill",       "name": "Begin" },
    { "from": "task_fill",      "to": "task_review",     "name": "Submitted" },
    { "from": "task_review",    "to": "gw_decision",     "name": "Decided" },
    { "from": "gw_decision",    "to": "task_notify_ok",  "name": "Yes", "condition": "approved == true" },
    { "from": "gw_decision",    "to": "task_notify_rej", "name": "No",  "default": true },
    { "from": "task_notify_ok", "to": "end_approved",    "name": "Done" },
    { "from": "task_notify_rej","to": "end_rejected",    "name": "Done" }
  ]
}

=== STEP 1 — IDENTIFY ROLES (DO THIS FIRST, EVERY TIME) ===

BEFORE writing any nodes or flows, identify every distinct actor in the process description.
This is mandatory — do not skip it even for simple processes.

  • Named people / teams: employee, manager, HR, finance team, customer, supervisor, reviewer...
  • Any automated step (send email, validate, calculate, check, create record, notify) → "System (Automatic)"
  • Even unnamed roles can be inferred: "submitted" → submitter lane; "approved" → approver lane
  • Minimum: if only one human is mentioned, still add "System (Automatic)" as a second lane

Create one lane per distinct actor (MINIMUM 2 LANES, ALWAYS):
  "lanes": [
    { "id": "employee",     "name": "Employee" },
    { "id": "manager",      "name": "Manager" },
    { "id": "finance_team", "name": "Finance Team" },
    { "id": "system",       "name": "System (Automatic)" }
  ]

Lane id rules: snake_case, e.g. "finance_team", "hr", "system". 2–4 lanes is typical.

=== IR SCHEMA ===

Output exactly this JSON structure:

{
  "name": "Human-readable process name",
  "lanes": [
    { "id": "lane_snake_case_id", "name": "Display Name" }
  ],
  "nodes": [
    {
      "id": "unique_snake_case_id",
      "type": "startEvent | endEvent | userTask | scriptTask | serviceTask | manualTask | exclusiveGateway | parallelGateway | subProcess",
      "name": "Descriptive display name",
      "lane": "lane_id — REQUIRED on every node when lanes are present"
    }
  ],
  "flows": [
    {
      "from": "source_node_id",
      "to": "target_node_id",
      "name": "Optional label on the arrow",
      "condition": "expression (exclusiveGateway non-default outgoing only)",
      "default": true
    }
  ]
}

=== NODE TYPES — WHO DOES THE WORK? ===

FORBIDDEN: type "task" — never use this. Every task must have a specific type.

startEvent      — exactly one required; no incoming flows; triggers the process
endEvent        — at least one required; no outgoing flows; process is done

userTask        — a PERSON acts on a screen (the process waits for them)
  Business situations: fill a form, review a document, approve/reject, make a decision,
  assign/select/choose something, sign off on work
  Examples: "Employee submits leave request", "Manager approves invoice", "HR reviews application"

scriptTask      — the SYSTEM runs automatically (no person involved, no waiting)
  Business situations: check validity (does stock exist? is balance enough?),
  calculate a value (total, tax, score), create/update/read a database record,
  send email or notification, run business rules or validation
  Examples: "System checks leave balance", "Calculate order total", "Send approval email"

serviceTask     — the system calls an OUTSIDE service (another company's system or platform)
  Business situations: payment processor, SMS gateway, government/regulatory system,
  external ERP, CRM, or third-party API
  Examples: "Process payment via Stripe", "Send OTP via SMS gateway"

manualTask      — a PHYSICAL real-world action (no computer tracks completion)
  Business situations: print a document, physically pack/assemble, hand-deliver, physically sign paper
  Examples: "Print and sign the contract", "Pack items in warehouse"

exclusiveGateway — decision point: exactly ONE outgoing path is taken
  Use for: if/else branches, approval decisions, re-check loops

parallelGateway  — ALL outgoing paths run simultaneously (split), or wait for ALL to finish (join)
  Use for: steps that happen in parallel at the same time

subProcess       — a group of steps collapsed into one box (named, not expanded)

=== STEP 2 — ASSIGN EVERY NODE TO A LANE ===

Every node MUST have a "lane" field when lanes are present. Use these rules:
  • userTask        → lane of the person doing the work (employee, manager, finance_team...)
  • scriptTask      → "system"
  • serviceTask     → "system"
  • startEvent      → lane of whoever or whatever triggers the process
  • endEvent        → lane of the last meaningful actor before it
  • exclusiveGateway → same lane as the task immediately before it
  • parallelGateway  → same lane as the task immediately before it

A node without a "lane" field when lanes exist is INVALID and will break the diagram.

=== FLOW RULES ===

Every node must be reachable from startEvent and lead to endEvent.
Do not leave any node disconnected.

CRITICAL — exclusiveGateway SPLIT (1 incoming, N outgoing):
  Every exclusiveGateway with multiple outgoing flows MUST have ALL of the following or the diagram will be rejected:
  • Exactly one outgoing flow marked "default": true  (the else/fallback path — taken when no condition matches)
  • A "condition" field on EVERY other outgoing flow  (never omit this — a flow without a condition and without "default": true is invalid)
  Example — two-branch decision:
      {"from": "gw_decision", "to": "task_approve",  "name": "Approved",  "condition": "approved == true"},
      {"from": "gw_decision", "to": "task_reject",   "name": "Rejected",  "default": true}
  Example — three-branch decision:
      {"from": "gw_check",   "to": "task_high",    "name": "High",    "condition": "score > 80"},
      {"from": "gw_check",   "to": "task_medium",  "name": "Medium",  "condition": "score > 50"},
      {"from": "gw_check",   "to": "task_low",     "name": "Low",     "default": true}

For exclusiveGateway JOIN (N incoming, 1 outgoing):
  • No conditions — just list all incoming flows

For parallelGateway split/join: no conditions needed.

RE-CHECK LOOP PATTERN (retry / re-submit / repeat-until-pass):
Always use TWO separate gateways:
  1. joinGW  — pure JOIN (N in, 1 out) — merges first-visit path and retry path
  2. decisionGW — pure FORK (1 in, N out) — branches to pass or fail
Example nodes: PreviousStep → joinGW → CheckTask → decisionGW → (PassPath | RetryTask → joinGW)

=== MANDATORY CHECKS BEFORE OUTPUT ===

Verify your IR satisfies these before outputting:
  ✓ "lanes" array is present with 2+ entries — ALWAYS, no exceptions
  ✓ Every node has a "lane" field matching a lane id in the "lanes" array
  ✓ Exactly one startEvent node
  ✓ At least one endEvent node
  ✓ Every node has a unique id and a non-empty name
  ✓ Every node is connected (has at least one flow to/from it)
  ✓ No node type is "task"
  ✓ Every exclusiveGateway split has exactly one "default": true flow and "condition" on all others
  ✓ No node has both multiple incoming AND multiple outgoing flows (except after normalisation)

=== OUTPUT ===

Output ONLY a valid JSON object matching the IR schema above.
No markdown fences, no explanation, no XML, no prose.
All node IDs must be unique snake_case strings (underscores, no spaces)."""


_DEFAULT_MODIFIER_INSTRUCTION = """You are a BPMN process modifier. You receive either:
  (a) An existing BPMN XML document + a modification request — analyse the XML, apply the change, output IR JSON for the complete modified process.
  (b) An IR JSON document + a list of problems — fix every problem, output corrected IR JSON.

The pipeline converts your IR into BPMN XML automatically. Never output XML.

=== IR SCHEMA ===

Output exactly this JSON structure:

{
  "name": "Human-readable process name",
  "nodes": [
    {
      "id": "unique_snake_case_id",
      "type": "startEvent | endEvent | userTask | scriptTask | serviceTask | manualTask | exclusiveGateway | parallelGateway | subProcess",
      "name": "Descriptive display name",
      "lane": "lane_id (only when using swim lanes — must match a lane id in the lanes array)"
    }
  ],
  "flows": [
    {
      "from": "source_node_id",
      "to": "target_node_id",
      "name": "Optional label on the arrow",
      "condition": "expression (exclusiveGateway non-default outgoing only)",
      "default": true
    }
  ],
  "lanes": [
    { "id": "lane_snake_case_id", "name": "Display Name", "role": "optional role string" }
  ]
}

=== HOW TO CONVERT CURRENT XML TO IR (case a) ===

Read the XML and map elements to IR nodes:
  bpmn:startEvent        → type: startEvent
  bpmn:endEvent          → type: endEvent
  bpmn:userTask          → type: userTask
  bpmn:scriptTask        → type: scriptTask
  bpmn:serviceTask       → type: serviceTask
  bpmn:manualTask        → type: manualTask
  bpmn:exclusiveGateway  → type: exclusiveGateway
  bpmn:parallelGateway   → type: parallelGateway
  bpmn:subProcess        → type: subProcess

For each bpmn:sequenceFlow, create a flow: {from: sourceRef, to: targetRef, name: name attribute}.
  • If the flow has a bpmn:conditionExpression child, add "condition": (its text content).
  • If the flow's id matches the gateway's default="" attribute, add "default": true.

If a bpmn:laneSet exists: extract lane ids, names, and each node's lane assignment (node.lane = lane id).

Apply the requested modification to the extracted IR, then output the complete updated IR.

Do NOT include gateways that only existed because a task had multiple flows — the pipeline inserts those automatically. Preserve explicit decision gateways (those with meaningful names and conditions).

=== NODE TYPES — WHAT EACH TYPE MEANS ===

FORBIDDEN: type "task" — never use this. Always pick the typed node:
  userTask        — a person acts on a screen (fill, review, approve, submit, sign)
  scriptTask      — system runs automatically (check, calculate, validate, send email, update record)
  serviceTask     — calls an external service (payment gateway, SMS provider, outside API)
  manualTask      — physical real-world action (print, pack, hand-deliver, physically sign)
  exclusiveGateway — decision point; one path taken
  parallelGateway  — all paths taken simultaneously

=== FLOW RULES ===

CRITICAL — exclusiveGateway SPLIT (1 incoming, N outgoing):
  Every exclusiveGateway with multiple outgoing flows MUST have ALL of the following or the diagram will be rejected:
  • Exactly one outgoing flow marked "default": true  (the else/fallback path)
  • A "condition" field on EVERY other outgoing flow  (never omit this)
  Example:
      {"from": "gw_decision", "to": "task_approve", "name": "Approved", "condition": "approved == true"},
      {"from": "gw_decision", "to": "task_reject",  "name": "Rejected", "default": true}

RE-CHECK LOOP: always use two gateways — a pure JOIN (N→1) then a pure FORK (1→N).

=== SWIM LANES — ALWAYS USE WHEN 2+ ROLES ARE INVOLVED ===

Use swim lanes automatically whenever the process involves 2 or more distinct actors or roles.
Each lane entry is { "id": "snake_case", "name": "Display Name" }.
Every node must have a "lane" field set to a lane's id (not its name). All lane ids must appear in "lanes".

Role identification: any named person/team (employee, manager, HR, finance...) gets their own lane.
Automated steps (send email, update record, validate, calculate) → "system" lane, name "System (Automatic)".

Assign:
  userTask        → person's lane id
  scriptTask / serviceTask → "system"
  startEvent / endEvent   → lane of the actor triggering or closing the process
  gateway                 → same lane id as the task immediately before it

If the existing XML has a laneSet, preserve and update the lane assignments when applying changes.
Omit lanes only when a single person does every step with zero system automation.

=== MANDATORY CHECKS BEFORE OUTPUT ===

  ✓ Exactly one startEvent
  ✓ At least one endEvent
  ✓ Every node has a unique id and a non-empty name
  ✓ Every node is connected (at least one flow)
  ✓ No node type is "task"
  ✓ Every exclusiveGateway split has one "default" flow and "condition" on all others
  ✓ When lanes are used: every node has a "lane" (a lane id) and all lane ids are in the "lanes" array

=== OUTPUT ===

Output ONLY a valid JSON object matching the IR schema.
No markdown fences, no explanation, no XML, no prose.
All node IDs must be unique snake_case strings."""


# ── IR repair hints (rule name → IR-level fix description) ───────────────────

_RULE_HINTS: dict[str, str] = {
    "task-type": (
        "Change the node's 'type' field. 'task' is forbidden. "
        "Use: 'userTask' (person acts on screen), 'scriptTask' (system runs automatically), "
        "'serviceTask' (external API/service), 'manualTask' (physical real-world action)."
    ),
    "start-event-required": (
        "Add a node with type='startEvent'. The process must have exactly one."
    ),
    "end-event-required": (
        "Add a node with type='endEvent'. The process must have at least one."
    ),
    "single-blank-start-event": (
        "Remove extra startEvent nodes — keep exactly one startEvent in the entire process."
    ),
    "no-disconnected": (
        "This node has no flows at all. Add incoming and/or outgoing flows connecting it "
        "to the rest of the process, or remove the node entirely."
    ),
    "no-implicit-start": (
        "This node has no incoming flow but is not a startEvent. "
        "Add a flow leading into it from a predecessor node."
    ),
    "no-implicit-end": (
        "This node has no outgoing flow but is not an endEvent. "
        "Add a flow leading out of it to a successor node."
    ),
    "no-gateway-join-fork": (
        "A gateway cannot both join (multiple incoming) AND fork (multiple outgoing) at the same time. "
        "Replace it with TWO separate gateways: a join gateway (N→1) immediately followed by a fork gateway (1→N)."
    ),
    "superfluous-gateway": (
        "This gateway has exactly 1 incoming and 1 outgoing flow — it serves no purpose. "
        "Remove it and connect its predecessor directly to its successor."
    ),
    "conditional-flows": (
        "For every exclusiveGateway split: mark exactly one outgoing flow with 'default': true "
        "(the else/fallback path), and add a 'condition' field to every other outgoing flow."
    ),
    "label-required": (
        "Add a descriptive 'name' field to this node or flow. Every element must have a non-empty name."
    ),
    "no-bpmndi": (
        "DI shapes are added by the compiler — no IR change needed for this rule."
    ),
    "no-complex-gateway": (
        "Remove the complexGateway node. Replace it with an exclusiveGateway or parallelGateway."
    ),
    "no-inclusive-gateway": (
        "Remove the inclusiveGateway node. Replace it with an exclusiveGateway or parallelGateway."
    ),
    "no-duplicate-sequence-flows": (
        "Two flows connect the same pair of nodes. Remove one of the duplicate flows."
    ),
    "lane-orphan": (
        "Add a 'lane' field to this node. Every node must be assigned to one of the lane ids "
        "defined in the 'lanes' array. Match the lane to the actor who performs the work: "
        "userTask → person's lane, scriptTask/serviceTask → 'system' lane, "
        "startEvent → lane of whoever triggers the process, "
        "endEvent → lane of the last meaningful actor before it, "
        "gateway → same lane as the task immediately before it."
    ),
    "lane-bounds": (
        "This node's visual position falls outside its lane band. The 'lane' field is likely wrong. "
        "Change the node's 'lane' to the correct lane id for the actor performing this step."
    ),
}

# Rules whose problems are fixed by the compiler, not by LLM IR changes
_IR_IGNORABLE_RULES: frozenset[str] = frozenset({"no-bpmndi"})


_DEFAULT_REDIRECT_MESSAGE = (
    "I'm here to help with process modelling on Processa — "
    "things like drawing processes from scratch, redrawing existing models, or modifying specific parts. "
    "I'm not able to help with that request, but I'm ready whenever you'd like to work on a process."
)


class ProsAllyAgent:
    """Orchestrates intent classification and clarification for process modelling requests."""

    def __init__(self):
        self._config = dict(get_agent_config(AGENT_ID) or {})
        self._config.setdefault("agent_id", AGENT_ID)
        self._llm    = get_llm_adapter_from_settings(self._config)
        self._instructions = self._load_instructions()

    def _load_instructions(self) -> dict:
        sub_prompts = (self._config or {}).get("sub_prompts", {})

        def _get(key, default):
            return sub_prompts.get(key, {}).get("prompt", default)

        return {
            "intent_classifier": _get("intent_classifier", _DEFAULT_INTENT_CLASSIFIER_INSTRUCTION),
            "clarifier":         _get("clarifier",         _DEFAULT_CLARIFIER_INSTRUCTION),
            "confirmer":         _get("confirmer",         _DEFAULT_CONFIRMER_INSTRUCTION),
            "process_generator": _get("process_generator", _DEFAULT_GENERATOR_INSTRUCTION),
            "modifier":          _get("modifier",          _DEFAULT_MODIFIER_INSTRUCTION),
        }

    # ── Helpers ────────────────────────────────────────────────────────────────

    async def _run(self, role: str, prompt: str) -> str | None:
        return await self._llm.complete(
            system=self._instructions[role],
            user=prompt,
        )

    def _format_history(self, chat_history: list) -> str:
        if not chat_history:
            return ""
        lines = []
        for entry in chat_history[-10:]:
            role    = entry.get("role") or entry.get("type", "user")
            content = (entry.get("content") or "").strip()
            if content:
                lines.append(f"{'User' if role == 'user' else 'ProsAlly'}: {content}")
        return "\n".join(lines)

    def _build_intent_prompt(self, message: str, process_name: str, chat_history: list) -> str:
        parts = []
        if process_name:
            parts.append(f"Process being modelled: {process_name}")
        history = self._format_history(chat_history)
        if history:
            parts.append(f"Conversation so far:\n{history}")
        parts.append(f"User message: {message}")
        return "\n\n".join(parts)

    @staticmethod
    def _parse_json_response(raw: str) -> dict:
        """Extract and parse the first JSON object from an LLM response."""
        import re
        text = (raw or "").strip()

        fence_match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)```", text)
        if fence_match:
            return json.loads(fence_match.group(1).strip())

        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            pass

        brace_match = re.search(r"\{[\s\S]*\}", text)
        if brace_match:
            return json.loads(brace_match.group(0))

        raise ValueError(f"No JSON object found in LLM response: {text[:200]}")

    def _build_generator_prompt(self, process_name: str, action_intent: str, chat_history: list) -> str:
        parts = []
        if action_intent == "OVERWRITE_EXISTING":
            parts.append("Action: OVERWRITE_EXISTING — generate a completely new IR to replace the current process.")
        else:
            parts.append("Action: GENERATE_NEW — generate an IR for a new process on an empty canvas.")
        if process_name:
            parts.append(f"Process name: {process_name}")
        history = self._format_history(chat_history)
        if history:
            parts.append(f"Conversation and process description:\n{history}")
        parts.append("Output the IR JSON now.")
        return "\n\n".join(parts)

    def _build_modifier_prompt(self, process_name: str, chat_history: list, current_xml: str) -> str:
        parts = ["Action: MODIFY_EXISTING — update the existing process as described, output the complete IR JSON for the result."]
        if process_name:
            parts.append(f"Process name: {process_name}")
        history = self._format_history(chat_history)
        if history:
            parts.append(f"Modification request from conversation:\n{history}")
        if current_xml.strip():
            parts.append(f"Current BPMN XML to analyse and modify:\n{current_xml.strip()}")
        parts.append("Output the complete IR JSON for the modified process now.")
        return "\n\n".join(parts)

    # ── IR pipeline ────────────────────────────────────────────────────────────

    @staticmethod
    def _find_node() -> str | None:
        """Return the path to a Node.js ≥ 18 binary, falling back to whatever is in PATH."""
        import shutil
        # Prefer nvm-managed Node 18+ (avoids system Node 12)
        home = os.path.expanduser("~")
        for ver in ("v20.19.4", "v20.19.2", "v18.19.0"):
            candidate = os.path.join(home, ".nvm", "versions", "node", ver, "bin", "node")
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        return shutil.which("node")

    @staticmethod
    def _run_pipeline_sync(ir_dict: dict, pipeline_path: str) -> dict:
        """Synchronous subprocess call to pipeline.mjs. Returns {ok, xml, problems}."""
        node = ProsAllyAgent._find_node()
        if not node:
            return {
                "ok": False, "xml": "",
                "problems": [{"kind": "fatal", "message": "node not found in PATH"}],
            }
        try:
            result = subprocess.run(
                [node, pipeline_path],
                input=json.dumps(ir_dict),
                capture_output=True,
                text=True,
                timeout=30,
            )
            stdout = result.stdout.strip()
            if not stdout:
                stderr = result.stderr.strip() or "pipeline produced no output"
                return {"ok": False, "xml": "", "problems": [{"kind": "fatal", "message": stderr}]}
            return json.loads(stdout)
        except subprocess.TimeoutExpired:
            return {"ok": False, "xml": "", "problems": [{"kind": "fatal", "message": "pipeline timed out after 30 s"}]}
        except Exception as exc:
            return {"ok": False, "xml": "", "problems": [{"kind": "fatal", "message": str(exc)}]}

    async def _call_pipeline(self, ir_dict: dict) -> dict:
        """Async wrapper — runs _run_pipeline_sync in a thread executor."""
        pipeline_path = os.path.normpath(os.path.join(
            os.path.dirname(__file__),
            "..", "..", "..", "..",
            "spiff", "pipeline.mjs",
        ))
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._run_pipeline_sync,
            ir_dict,
            pipeline_path,
        )

    @staticmethod
    def _translate_problems(problems: list) -> list[str]:
        """Convert pipeline problem dicts into IR-level fix hints (deduped, ignorable rules removed)."""
        hints: list[str] = []
        seen: set[tuple] = set()
        for p in problems:
            rule = p.get("rule") or ""
            kind = p.get("kind") or ""
            eid  = p.get("elementId") or ""
            msg  = p.get("message") or str(p)

            if rule in _IR_IGNORABLE_RULES:
                continue

            key = (rule or kind, eid)
            if key in seen:
                continue
            seen.add(key)

            hint_body = _RULE_HINTS.get(rule, msg)
            label     = rule or kind or "problem"
            if eid:
                hints.append(f"[{label}] Element '{eid}': {hint_body}")
            else:
                hints.append(f"[{label}] {hint_body}")
        return hints

    @staticmethod
    def _translate_violations(violations: list[str]) -> list[str]:
        """Convert Python bpmn_validator violation strings to IR-level fix hints (deduped)."""
        import re
        hints: list[str] = []
        seen: set[str] = set()
        for v in violations:
            rule_match = re.match(r'\[([^\]]+)\]', v)
            rule = rule_match.group(1) if rule_match else ""
            if rule in _IR_IGNORABLE_RULES:
                continue
            if rule in seen:
                continue
            seen.add(rule or v[:60])
            hint = _RULE_HINTS.get(rule, v)
            hints.append(f"[{rule}] {hint}" if rule else hint)
        return hints

    @staticmethod
    def _build_ir_repair_prompt(ir_dict: dict, hints: list[str]) -> str:
        numbered = "\n".join(f"  {i + 1}. {h}" for i, h in enumerate(hints))
        has_inferred = any(n.get("inferred") for n in (ir_dict.get("nodes") or []))
        inferred_note = (
            "\nNOTE: Some nodes are tagged \"inferred\": true — these were automatically "
            "inserted by the compiler to fix implicit splits/joins. Keep them in your output "
            "(or remove them and re-model the structure explicitly). Do NOT add conditions to "
            "inferred parallelGateway nodes. DO add conditions/default to any inferred "
            "exclusiveGateway node that has multiple outgoing flows.\n"
            if has_inferred else ""
        )
        return (
            f"The process IR has {len(hints)} problem(s) that must be fixed.\n\n"
            f"PROBLEMS:\n{numbered}\n"
            f"{inferred_note}\n"
            "Fix every problem listed above, then output the complete corrected IR JSON.\n\n"
            f"Current IR:\n{json.dumps(ir_dict, indent=2)}"
        )

    async def _generate_and_validate(self, role: str, initial_prompt: str) -> tuple[str, list[str]]:
        """
        LLM → IR JSON → pipeline.mjs (normalise → compile → layout)
             → Python bpmn_validator (semantic lint).
        On failure: translate to IR hints → LLM repairs IR.
        Bounded to _MAX_FIX_PASSES repair attempts (4 total LLM calls).
        Returns (best_xml, remaining_violation_messages).
        """
        import frappe
        from one_bpmn.security.bpmn_validator import validate_bpmn_xml

        _MAX_FIX_PASSES = 3
        best_xml     = ""
        remaining    : list[str] = []
        ir_dict      : dict | None = None
        repair_hints : list[str] = []

        for attempt in range(_MAX_FIX_PASSES + 1):
            prompt = initial_prompt if attempt == 0 else self._build_ir_repair_prompt(ir_dict, repair_hints)
            raw    = await self._run(role, prompt)

            # Parse IR JSON from LLM response
            try:
                ir_dict = self._parse_json_response(raw or "")
            except (json.JSONDecodeError, ValueError) as exc:
                repair_hints = [f"Your last response was not valid JSON: {exc}. Output ONLY a JSON object matching the IR schema."]
                remaining    = [str(exc)]
                frappe.log_error(title=f"ProsAlly IR parse — attempt {attempt + 1}", message=str(exc))
                if attempt == _MAX_FIX_PASSES:
                    break
                continue

            # Diagnostic: log what the LLM generated (lanes presence is the key signal)
            _lanes_debug = ir_dict.get("lanes") or []
            frappe.log_error(
                title=f"ProsAlly LLM IR — attempt {attempt + 1} ({role})",
                message=(
                    f"Lanes: {len(_lanes_debug)} — {[l.get('id') for l in _lanes_debug]}\n"
                    f"Nodes: {len(ir_dict.get('nodes') or [])}\n"
                    f"IR (first 800 chars):\n{json.dumps(ir_dict)[:800]}"
                ),
            )

            # ── LANE ENFORCEMENT (generator only) ─────────────────────────────
            # The LLM must include lanes whenever it generates a new process.
            # A flat (no-lane) IR is treated as a structural failure and queued for repair.
            if role == "process_generator":
                lanes_present = ir_dict.get("lanes") or []
                if len(lanes_present) < 2:
                    repair_hints = [
                        "MISSING SWIMLANES — your IR has no lane structure. This is required. "
                        "EVERY business process must be drawn inside a pool divided into lanes, "
                        "one lane per actor role.\n"
                        "Step 1: identify EVERY distinct actor in the process description "
                        "(human roles such as Employee, Manager, HR, Finance; "
                        "plus 'System (Automatic)' for every automated step).\n"
                        "Step 2: add a 'lanes' array with one entry per actor:\n"
                        "  \"lanes\": [{\"id\": \"employee\", \"name\": \"Employee\"}, "
                        "{\"id\": \"manager\", \"name\": \"Manager\"}, "
                        "{\"id\": \"system\", \"name\": \"System (Automatic)\"}]\n"
                        "Step 3: add a \"lane\" field to EVERY node pointing to its actor's lane id.\n"
                        "Output the complete corrected IR JSON now."
                    ]
                    remaining = ["IR missing required swimlane lanes array (< 2 lanes)"]
                    frappe.log_error(
                        title=f"ProsAlly no-lanes rejected — attempt {attempt + 1}",
                        message=(
                            f"LLM returned {len(lanes_present)} lane(s). Forcing repair.\n"
                            f"Nodes in IR: {len(ir_dict.get('nodes') or [])}"
                        ),
                    )
                    if attempt == _MAX_FIX_PASSES:
                        break
                    continue

            # Step 1: normalise + compile + layout (pipeline.mjs)
            result     = await self._call_pipeline(ir_dict)
            xml        = result.get("xml") or ""
            pipe_probs = result.get("problems") or []

            # Switch to the normalized IR for any subsequent repair pass so the LLM
            # sees the full structure — including compiler-inferred join/split gateways —
            # and can add conditions/defaults to every gateway that needs them.
            norm_ir = result.get("normalizedIR")
            if norm_ir:
                ir_dict = norm_ir

            if xml:
                best_xml = xml

            if not result.get("ok"):
                # Pipeline hard failure (pairing mismatch or compile error)
                repair_hints = self._translate_problems(pipe_probs)
                remaining    = [p.get("message") or str(p) for p in pipe_probs]
                frappe.log_error(
                    title=f"ProsAlly pipeline hard fail — attempt {attempt + 1}",
                    message="\n".join(f"  [{p.get('kind','?')}] {p.get('message','')}" for p in pipe_probs),
                )
                if attempt == _MAX_FIX_PASSES:
                    break
                continue

            # Step 2: semantic validation (Python validator)
            val = validate_bpmn_xml(xml)
            if val["valid"]:
                remaining = []
                break

            violations = val["violations"]
            repair_hints = self._translate_violations(violations)
            remaining    = violations

            frappe.log_error(
                title=f"ProsAlly validator — attempt {attempt + 1}/{_MAX_FIX_PASSES + 1}",
                message=(
                    f"{'Max retries reached — returning best effort' if attempt == _MAX_FIX_PASSES else 'Repairing IR'}\n"
                    f"Violations ({len(violations)}):\n" +
                    "\n".join(f"  {v}" for v in violations)
                ),
            )

            if attempt == _MAX_FIX_PASSES:
                break

        return best_xml, remaining

    def _build_confirmer_prompt(self, message: str, process_name: str, action_intent: str, chat_history: list) -> str:
        _action_labels = {
            "GENERATE_NEW":       "GENERATE_NEW — draw a brand-new process from scratch on an empty canvas",
            "OVERWRITE_EXISTING": "OVERWRITE_EXISTING — completely replace the existing model",
            "MODIFY_EXISTING":    "MODIFY_EXISTING — change a specific part of the existing model",
        }
        parts = [f"Detected action: {_action_labels.get(action_intent, action_intent)}"]
        if process_name:
            parts.append(f"Process: {process_name}")
        history = self._format_history(chat_history)
        if history:
            parts.append(f"Conversation so far:\n{history}")
        parts.append(f"User message: {message}")
        return "\n\n".join(parts)

    def _build_clarifier_prompt(self, message: str, process_name: str, intent_reason: str, chat_history: list) -> str:
        parts = []
        if process_name:
            parts.append(f"Process: {process_name}")
        parts.append(f"Classification reason: {intent_reason}")
        history = self._format_history(chat_history)
        if history:
            parts.append(f"Conversation so far:\n{history}")
        parts.append(f"User message: {message}")
        return "\n\n".join(parts)

    # ── Main pipeline ──────────────────────────────────────────────────────────

    async def process_message(
        self,
        message: str,
        chat_history: list,
        process_name: str = "",
        diagram_name: str = "",
        confirmed_action: str = "",
        current_xml: str = "",
    ) -> dict:
        """
        Classify intent then route to the correct handler.

        Returns a dict:
          intent        : "BPMN_GENERATED" | "BPMN_MODIFIED" | "CONFIRM" | "CLARIFY" | "IRRELEVANT"
          response      : agent text
          action_intent : "GENERATE_NEW" | "OVERWRITE_EXISTING" | "MODIFY_EXISTING" | None
          bpmn_xml      : BPMN 2.0 XML string (when intent is BPMN_GENERATED or BPMN_MODIFIED)
          options       : list of button labels
        """
        _ACTION_INTENTS      = {"GENERATE_NEW", "OVERWRITE_EXISTING", "MODIFY_EXISTING"}
        _GENERATE_INTENTS    = {"GENERATE_NEW", "OVERWRITE_EXISTING"}
        _NEEDS_CLARIFICATION = {"AMBIGUOUS", "INCOMPLETE"}

        # STEP 0 — User confirmed an action: skip classification and act immediately
        if confirmed_action in _ACTION_INTENTS:
            name_label = process_name or "process"

            if confirmed_action == "MODIFY_EXISTING" and current_xml.strip():
                modifier_prompt = self._build_modifier_prompt(process_name, chat_history, current_xml)
                bpmn_xml, problems = await self._generate_and_validate("modifier", modifier_prompt)
                note = (
                    f" ({len(problems)} issue(s) remain — review the canvas.)"
                    if problems else ""
                )
                return {
                    "intent":        "BPMN_MODIFIED",
                    "action_intent": "MODIFY_EXISTING",
                    "bpmn_xml":      bpmn_xml,
                    "response":      f"I've updated the {name_label} process.{note} Review the changes on the canvas.",
                    "options":       [],
                }

            generator_prompt = self._build_generator_prompt(process_name, confirmed_action, chat_history)
            bpmn_xml, problems = await self._generate_and_validate("process_generator", generator_prompt)
            note = (
                f" ({len(problems)} issue(s) remain — review the canvas.)"
                if problems else ""
            )
            return {
                "intent":        "BPMN_GENERATED",
                "action_intent": confirmed_action,
                "bpmn_xml":      bpmn_xml,
                "response":      f"I've generated the {name_label} process model.{note} Review it on the canvas.",
                "options":       [],
            }

        # STEP 1 — Classify intent
        intent_prompt = self._build_intent_prompt(message, process_name, chat_history)
        intent_raw    = await self._run("intent_classifier", intent_prompt)

        intent        = "INCOMPLETE"
        intent_reason = ""
        try:
            intent_data   = self._parse_json_response(intent_raw)
            intent        = intent_data.get("intent", "INCOMPLETE").upper()
            intent_reason = intent_data.get("reason", "")
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

        if intent not in (_ACTION_INTENTS | _NEEDS_CLARIFICATION | {"IRRELEVANT"}):
            intent = "INCOMPLETE"

        # STEP 2a — IRRELEVANT
        if intent == "IRRELEVANT":
            sub_prompts  = (self._config or {}).get("sub_prompts", {})
            redirect_msg = sub_prompts.get("redirect", {}).get("prompt", _DEFAULT_REDIRECT_MESSAGE)
            return {
                "intent":        "IRRELEVANT",
                "action_intent": None,
                "response":      redirect_msg,
                "options":       [],
            }

        # STEP 2b — AMBIGUOUS / INCOMPLETE
        if intent in _NEEDS_CLARIFICATION:
            clarifier_prompt = self._build_clarifier_prompt(
                message, process_name, intent_reason, chat_history
            )
            clarify_raw = await self._run("clarifier", clarifier_prompt)
            try:
                clarify_data = self._parse_json_response(clarify_raw)
                return {
                    "intent":        "CLARIFY",
                    "action_intent": None,
                    "response":      clarify_data.get("question", "Could you tell me more about the process?"),
                    "options":       clarify_data.get("options", []),
                }
            except (json.JSONDecodeError, TypeError, ValueError):
                return {
                    "intent":        "CLARIFY",
                    "action_intent": None,
                    "response":      "Could you tell me more about the process you'd like to model?",
                    "options":       [],
                }

        # STEP 2c — GENERATE_NEW / OVERWRITE_EXISTING / MODIFY_EXISTING → confirm
        confirm_raw = await self._run(
            "confirmer",
            self._build_confirmer_prompt(message, process_name, intent, chat_history),
        )
        try:
            confirm_data  = self._parse_json_response(confirm_raw)
            summary       = confirm_data.get("summary", "")
            question      = confirm_data.get("question", "Shall I proceed?")
            response_text = f"{summary}\n{question}" if summary else question
        except (json.JSONDecodeError, TypeError, ValueError):
            response_text = confirm_raw or "Shall I proceed with this?"

        return {
            "intent":        "CONFIRM",
            "action_intent": intent,
            "response":      response_text,
            "options":       ["Yes, proceed", "No, let me adjust"],
        }


def run_prosally_message(
    message: str,
    chat_history: list,
    process_name: str = "",
    diagram_name: str = "",
    confirmed_action: str = "",
    current_xml: str = "",
) -> dict:
    """Synchronous entry point — wraps the async agent pipeline."""
    agent = ProsAllyAgent()
    return asyncio.run(
        agent.process_message(
            message=message,
            chat_history=chat_history,
            process_name=process_name,
            diagram_name=diagram_name,
            confirmed_action=confirmed_action,
            current_xml=current_xml,
        )
    )
