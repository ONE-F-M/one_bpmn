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
"""

import asyncio
import json
import os

import frappe
from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from onefm_mcp.onefm_mcp.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config

APP_NAME = "prosally_agent"
USER_ID  = "prosally_agent"
AGENT_ID = "prosally_agent"

# ── Default instructions ───────────────────────────────────────────────────

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


_DEFAULT_CLARIFIER_INSTRUCTION = """You are a clarification assistant for ProsAlly, an AI process modelling assistant on Processa.

The user's process modelling request is unclear or missing critical details. Your job is to ask ONE precise clarifying question that will give ProsAlly enough information to proceed.

The process being worked on: {process_name}

What to ask about when INCOMPLETE:
- What is the process called? (if not named)
- Who are the actors/participants? (if not mentioned)
- What are the main steps or decision points? (if too vague)
- What triggers the process (start event)? (if not clear)
- What is the outcome/end state? (if not described)

What to ask about when AMBIGUOUS:
- Does the user want to draw a new process, or modify the existing one?
- Which specific part of the process should be changed?
- Which of the plausible interpretations is correct?

Rules:
- Ask exactly ONE question.
- Prefer a multiple-choice question (2–4 options) when specific alternatives exist.
- Use a Yes/No question only when there are exactly two clear choices.
- Keep the question short, direct, and framed around process modelling.
- Never write BPMN XML or attempt to model anything — only ask a question.

Respond with ONLY a JSON object — no other text:
{"question": "your clarifying question here", "options": ["option 1", "option 2", ...]}"""


_DEFAULT_CONFIRMER_INSTRUCTION = """You are a confirmation assistant for ProsAlly, an AI process modelling assistant on Processa.

The user's request has been classified into one of three actions. You will be told which action was detected.

Your job is to write a short confirmation message that:
1. States clearly which action ProsAlly is about to take:
   - GENERATE_NEW: "I'll draw a new [process name] process from scratch..."
   - OVERWRITE_EXISTING: "I'll completely replace the existing [process name] model..."
   - MODIFY_EXISTING: "I'll modify [the specific part] of the [process name] process..."
2. Lists the key details understood from the user's description (steps, actors, decisions if mentioned).
3. Asks for confirmation before any changes are made.

Rules:
- Be specific — name the process, the action type, and the key steps or parts mentioned.
- Do NOT begin modelling or write BPMN — only confirm intent.
- Keep the message concise (2–4 sentences max).
- End with a clear confirmation question.

Respond with ONLY a JSON object — no other text:
{"summary": "one or two sentence summary of what ProsAlly will do", "question": "confirmation question e.g. Shall I proceed?"}"""


_DEFAULT_GENERATOR_INSTRUCTION = """You are a BPMN 2.0 process modeller. Generate a complete, valid BPMN 2.0 XML document from the user's process description that can be loaded directly by bpmn-js.

A layout algorithm will automatically reposition all shapes after generation — you do NOT need to calculate precise coordinates. Use the placeholder values specified below.

=== REQUIRED XML STRUCTURE ===

<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions
  xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
  xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
  xmlns:di="http://www.omg.org/spec/DD/20100524/DI"
  id="Definitions_1"
  targetNamespace="http://bpmn.io/schema/bpmn">

  <bpmn:process id="Process_[7randchars]" isExecutable="true">
    <!-- semantic elements here -->
  </bpmn:process>

  <bpmndi:BPMNDiagram id="BPMNDiagram_1">
    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="[process id]">
      <!-- one BPMNShape per semantic element; one BPMNEdge per sequenceFlow -->
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>

</bpmn:definitions>

=== SEMANTIC ELEMENT RULES ===

Always include exactly one startEvent and one endEvent.

- Start event:       <bpmn:startEvent id="StartEvent_1" name="Start" />
- End event:         <bpmn:endEvent id="EndEvent_1" name="End" />
- User task:         <bpmn:userTask id="Task_[7rc]" name="[descriptive label]" />
- Exclusive gateway: <bpmn:exclusiveGateway id="Gateway_[7rc]" name="[decision label]" />
- Sequence flow:     <bpmn:sequenceFlow id="Flow_[7rc]" sourceRef="[id]" targetRef="[id]" />
  - Flows from an exclusiveGateway to a branch must include: name="[condition label]"

Generate between 3 and 12 elements (excluding sequence flows). All elements must be connected — no disconnected nodes.

=== DI PLACEHOLDER RULES ===

Every semantic element MUST have a corresponding BPMNShape.
Every sequenceFlow MUST have a corresponding BPMNEdge.

Use these EXACT placeholder values for ALL shapes and edges — the layout algorithm replaces them:

Shape placeholder (use for every element regardless of type):
  <bpmndi:BPMNShape id="Shape_[element-id]" bpmnElement="[element-id]">
    <dc:Bounds x="150" y="260" width="100" height="80" />
  </bpmndi:BPMNShape>

Edge placeholder (use for every sequenceFlow):
  <bpmndi:BPMNEdge id="Edge_[flow-id]" bpmnElement="[flow-id]">
    <di:waypoint x="0" y="0" />
    <di:waypoint x="0" y="0" />
  </bpmndi:BPMNEdge>

=== OUTPUT RULES ===
- Output ONLY the raw XML — no markdown fences, no explanation, no comments outside XML comments.
- All IDs must be unique within the document.
- Every element must have a descriptive name attribute derived from the user's description."""


_DEFAULT_MODIFIER_INSTRUCTION = """You are a BPMN 2.0 process modifier. You receive an existing BPMN 2.0 XML document and a modification instruction. Your job is to add, remove, or update specific elements in the diagram while leaving everything else exactly as-is.

A layout algorithm will automatically reposition all shapes after modification — use placeholder coordinates for ALL shapes and edges (new or touched).

=== MODIFICATION PATTERNS ===

Pattern A — INSERT ELEMENT BETWEEN two existing nodes (A → C becomes A → B → C):
1. Find <bpmn:sequenceFlow ... sourceRef="A" targetRef="C" />, change its targetRef to the new element id.
2. Add <bpmn:sequenceFlow id="Flow_[7rc]" sourceRef="[new-id]" targetRef="C" />.
3. Add the new element's semantic tag.
4. Add a BPMNShape placeholder for the new element.
5. Add a BPMNEdge placeholder for the new flow.
6. Reset the modified edge's waypoints to placeholders.

Pattern B — INSERT BEFORE END EVENT (default when target location is not explicit):
1. Find the sequenceFlow whose targetRef is the end event id.
2. Apply Pattern A: redirect it through the new element then on to the end event.

Pattern C — ADD A DECISION BRANCH (exclusive gateway + alternative path):
1. Insert an exclusiveGateway using Pattern A or B.
2. The existing onward flow becomes the "yes/main" branch — add name="[yes label]" to it.
3. Add a new task on the alternative path with its own flow from the gateway.
4. Add name="[no label]" to the alternative flow.
5. Connect the alternative task back to a downstream join point or to the end event.
All flows from exclusiveGateway MUST have a name attribute.

Pattern D — REMOVE ELEMENT and bridge its predecessors to its successors:

Step-by-step for removing element B (example: A → B → C becomes A → C):
1. Locate element B by matching its name attribute to the user's instruction.
2. Collect INCOMING flows: every <bpmn:sequenceFlow targetRef="[B_id]" />.
   Record the sourceRef of each incoming flow (predecessors).
3. Collect OUTGOING flows: every <bpmn:sequenceFlow sourceRef="[B_id]" />.
   Record the targetRef of each outgoing flow (successors).
4. For every (predecessor X, successor Y) pair, add a new bridging flow:
   <bpmn:sequenceFlow id="Flow_[7rc]" sourceRef="X" targetRef="Y" />
   Also add a BPMNEdge placeholder for each new bridging flow.
5. Delete from bpmn:process:
   - The semantic tag for B (e.g. <bpmn:userTask id="B_id" .../>)
   - All incoming sequenceFlow tags (targetRef = B_id)
   - All outgoing sequenceFlow tags (sourceRef = B_id)
6. Delete from bpmndi:BPMNPlane:
   - The BPMNShape whose bpmnElement = B_id
   - The BPMNEdge for every deleted incoming flow
   - The BPMNEdge for every deleted outgoing flow

REMOVAL GUARDS — never apply Pattern D to:
- startEvent elements (required by start-event-required linting rule)
- endEvent elements (required by end-event-required linting rule)
If the user requests removal of a startEvent or endEvent, output the XML unchanged and append this XML comment before </bpmn:definitions>:
<!-- ProsAlly: cannot remove [element type] — required by BPMN linting rules -->

MULTI-PREDECESSOR / MULTI-SUCCESSOR: create all (predecessor, successor) combinations as bridging flows.

=== STRICT RULES ===
- Generate globally unique IDs for all new elements (append 7 random alphanumeric chars).
- Do NOT rename, change the id of, or alter any existing element not mentioned in the instruction.
- Do NOT re-sequence or renumber existing IDs.
- All new elements need descriptive name attributes.
- Preserve all existing XML attributes (isExecutable, targetNamespace, etc.).
- Output the COMPLETE updated document.

=== DI PLACEHOLDER VALUES ===

Use for every new BPMNShape:
  <bpmndi:BPMNShape id="Shape_[element-id]" bpmnElement="[element-id]">
    <dc:Bounds x="150" y="260" width="100" height="80" />
  </bpmndi:BPMNShape>

Use for every new BPMNEdge and reset any modified existing BPMNEdge:
  <bpmndi:BPMNEdge id="Edge_[flow-id]" bpmnElement="[flow-id]">
    <di:waypoint x="0" y="0" />
    <di:waypoint x="0" y="0" />
  </bpmndi:BPMNEdge>

=== OUTPUT ===
Output the COMPLETE modified BPMN 2.0 XML only — no markdown fences, no explanation, no commentary."""


_DEFAULT_REDIRECT_MESSAGE = (
    "I'm here to help with process modelling on Processa — "
    "things like drawing processes from scratch, redrawing existing models, or modifying specific parts. "
    "I'm not able to help with that request, but I'm ready whenever you'd like to work on a process."
)


class ProsAllyAgent:
    """Orchestrates intent classification and clarification for process modelling requests."""

    def __init__(self):
        self.gemini_model = None
        self.setup_credentials()
        self._config = get_agent_config(AGENT_ID)
        self.setup_agents()

    def setup_credentials(self):
        os.environ.pop("GOOGLE_GENAI_USE_VERTEXAI", None)
        try:
            settings_doc = frappe.get_doc("AI Chat Settings")
            api_key = settings_doc.get_password("google_vertex_ai_api_key")
            if api_key and api_key.strip():
                os.environ["GOOGLE_API_KEY"] = api_key.strip()
            else:
                frappe.log_error(
                    title="ProsAlly Agent - Missing API Key",
                    message="google_vertex_ai_api_key not found in AI Chat Settings",
                )
            self.gemini_model = settings_doc.gemini_model or "gemini-2.0-flash"
        except Exception:
            frappe.log_error(title="ProsAlly Agent - Credential Setup", message=frappe.get_traceback())
            self.gemini_model = "gemini-2.0-flash"

    def setup_agents(self):
        sub_prompts = (self._config or {}).get("sub_prompts", {})

        def _instruction(key, default):
            return sub_prompts.get(key, {}).get("prompt", default)

        self.intent_classifier = LlmAgent(
            name="IntentClassifier",
            model=self.gemini_model,
            instruction=_instruction("intent_classifier", _DEFAULT_INTENT_CLASSIFIER_INSTRUCTION),
            output_key="intent",
        )
        self.clarifier = LlmAgent(
            name="Clarifier",
            model=self.gemini_model,
            instruction=_instruction("clarifier", _DEFAULT_CLARIFIER_INSTRUCTION),
            output_key="clarification",
        )
        self.confirmer = LlmAgent(
            name="Confirmer",
            model=self.gemini_model,
            instruction=_instruction("confirmer", _DEFAULT_CONFIRMER_INSTRUCTION),
            output_key="confirmation",
        )
        self.process_generator = LlmAgent(
            name="ProcessGenerator",
            model=self.gemini_model,
            instruction=_instruction("process_generator", _DEFAULT_GENERATOR_INSTRUCTION),
            output_key="bpmn_xml",
        )
        self.modifier = LlmAgent(
            name="ProcessModifier",
            model=self.gemini_model,
            instruction=_instruction("modifier", _DEFAULT_MODIFIER_INSTRUCTION),
            output_key="bpmn_xml",
        )

    # ── Helpers ────────────────────────────────────────────────────────────

    async def _run_agent(self, agent: LlmAgent, prompt: str, session_service, session_id: str) -> str | None:
        """Run a single LlmAgent and return its final text response."""
        runner = Runner(agent=agent, app_name=APP_NAME, session_service=session_service)
        content = types.Content(role="user", parts=[types.Part(text=prompt)])
        async for event in runner.run_async(user_id=USER_ID, session_id=session_id, new_message=content):
            if event.is_final_response() and event.content:
                return event.content.parts[0].text
        return None

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
    def _extract_bpmn_xml(raw: str) -> str:
        """Strip markdown fences and return clean BPMN XML."""
        import re
        # Remove ```xml ... ``` or ``` ... ``` wrappers
        match = re.search(r"```(?:xml)?\s*\n?([\s\S]*?)```", raw or "")
        if match:
            return match.group(1).strip()
        # If the output starts with <?xml or <bpmn: treat it as raw XML
        stripped = (raw or "").strip()
        if stripped.startswith("<?xml") or stripped.startswith("<bpmn:"):
            return stripped
        return raw or ""

    def _build_generator_prompt(self, process_name: str, action_intent: str, chat_history: list) -> str:
        parts = []
        if action_intent == "OVERWRITE_EXISTING":
            parts.append("Action: OVERWRITE_EXISTING — generate a completely new model to replace the current one.")
        else:
            parts.append("Action: GENERATE_NEW — generate a new process model on an empty canvas.")
        if process_name:
            parts.append(f"Process name: {process_name}")
        history = self._format_history(chat_history)
        if history:
            parts.append(f"Conversation and process description:\n{history}")
        parts.append("Generate the complete BPMN 2.0 XML now.")
        return "\n\n".join(parts)

    def _build_modifier_prompt(self, process_name: str, chat_history: list, current_xml: str) -> str:
        parts = ["Action: MODIFY_EXISTING — update the existing process model as described (add, remove, or change specific elements)."]
        if process_name:
            parts.append(f"Process name: {process_name}")
        history = self._format_history(chat_history)
        if history:
            parts.append(f"Modification request from conversation:\n{history}")
        if current_xml.strip():
            parts.append(f"Current BPMN XML to modify:\n{current_xml.strip()}")
        parts.append("Generate the complete modified BPMN 2.0 XML now.")
        return "\n\n".join(parts)

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

    # ── Main pipeline ──────────────────────────────────────────────────────

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

        session_service = InMemorySessionService()
        session_id = f"prosally_{frappe.utils.now_datetime().strftime('%Y%m%d%H%M%S%f')}"
        await session_service.create_session(
            app_name=APP_NAME, user_id=USER_ID, session_id=session_id, state={}
        )

        try:
            # STEP 0 — User confirmed an action: skip classification and act immediately
            if confirmed_action in _ACTION_INTENTS:
                name_label = process_name or "process"

                # MODIFY_EXISTING: patch the current canvas XML
                if confirmed_action == "MODIFY_EXISTING" and current_xml.strip():
                    modifier_prompt = self._build_modifier_prompt(process_name, chat_history, current_xml)
                    xml_raw = await self._run_agent(
                        self.modifier, modifier_prompt, session_service, session_id
                    )
                    bpmn_xml = self._extract_bpmn_xml(xml_raw or "")
                    return {
                        "intent":        "BPMN_MODIFIED",
                        "action_intent": "MODIFY_EXISTING",
                        "bpmn_xml":      bpmn_xml,
                        "response":      f"I've updated the {name_label} process. Review the changes on the canvas.",
                        "options":       [],
                    }

                # GENERATE_NEW / OVERWRITE_EXISTING (or MODIFY_EXISTING with no canvas XML):
                # generate a fresh model from scratch
                generator_prompt = self._build_generator_prompt(process_name, confirmed_action, chat_history)
                xml_raw = await self._run_agent(
                    self.process_generator, generator_prompt, session_service, session_id
                )
                bpmn_xml = self._extract_bpmn_xml(xml_raw or "")
                return {
                    "intent":        "BPMN_GENERATED",
                    "action_intent": confirmed_action,
                    "bpmn_xml":      bpmn_xml,
                    "response":      f"I've generated the {name_label} process model. Review it on the canvas.",
                    "options":       [],
                }

            # STEP 1 — Classify intent
            intent_prompt = self._build_intent_prompt(message, process_name, chat_history)
            intent_raw    = await self._run_agent(
                self.intent_classifier, intent_prompt, session_service, session_id
            )

            intent        = "INCOMPLETE"
            intent_reason = ""
            try:
                intent_data   = json.loads((intent_raw or "").strip())
                intent        = intent_data.get("intent", "INCOMPLETE").upper()
                intent_reason = intent_data.get("reason", "")
            except (json.JSONDecodeError, TypeError):
                pass

            if intent not in (_ACTION_INTENTS | _NEEDS_CLARIFICATION | {"IRRELEVANT"}):
                intent = "INCOMPLETE"

            # STEP 2a — IRRELEVANT: polite redirect, no further processing
            if intent == "IRRELEVANT":
                sub_prompts  = (self._config or {}).get("sub_prompts", {})
                redirect_msg = sub_prompts.get("redirect", {}).get("prompt", _DEFAULT_REDIRECT_MESSAGE)
                return {
                    "intent":        "IRRELEVANT",
                    "action_intent": None,
                    "response":      redirect_msg,
                    "options":       [],
                }

            # STEP 2b — AMBIGUOUS / INCOMPLETE: run Clarifier
            if intent in _NEEDS_CLARIFICATION:
                clarifier_prompt = self._build_clarifier_prompt(
                    message, process_name, intent_reason, chat_history
                )
                clarify_raw = await self._run_agent(
                    self.clarifier, clarifier_prompt, session_service, session_id
                )
                try:
                    clarify_data = json.loads((clarify_raw or "").strip())
                    return {
                        "intent":        "CLARIFY",
                        "action_intent": None,
                        "response":      clarify_data.get("question", clarify_raw or "Could you tell me more about the process?"),
                        "options":       clarify_data.get("options", []),
                    }
                except (json.JSONDecodeError, TypeError):
                    return {
                        "intent":        "CLARIFY",
                        "action_intent": None,
                        "response":      clarify_raw or "Could you tell me more about the process you'd like to model?",
                        "options":       [],
                    }

            # STEP 2c — GENERATE_NEW / OVERWRITE_EXISTING / MODIFY_EXISTING:
            #           run Confirmer to summarise the specific action and ask for confirmation
            confirm_raw = await self._run_agent(
                self.confirmer,
                self._build_confirmer_prompt(message, process_name, intent, chat_history),
                session_service,
                session_id,
            )
            try:
                confirm_data  = json.loads((confirm_raw or "").strip())
                summary       = confirm_data.get("summary", "")
                question      = confirm_data.get("question", "Shall I proceed?")
                response_text = f"{summary}\n{question}" if summary else question
            except (json.JSONDecodeError, TypeError):
                response_text = confirm_raw or "Shall I proceed with this?"

            return {
                "intent":        "CONFIRM",
                "action_intent": intent,
                "response":      response_text,
                "options":       ["Yes, proceed", "No, let me adjust"],
            }

        finally:
            try:
                await session_service.delete_session(
                    app_name=APP_NAME, user_id=USER_ID, session_id=session_id
                )
            except Exception:
                pass


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
