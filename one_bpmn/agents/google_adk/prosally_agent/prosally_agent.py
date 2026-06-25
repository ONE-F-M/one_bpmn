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
import re
import subprocess

from onefm_mcp.onefm_mcp.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config
from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings

AGENT_ID = "prosally_agent"

# ── Required sub-prompt keys (must exist in AI Agent Configuration) ─────────────
_REQUIRED_SUB_PROMPTS = (
    "intent_classifier",
    "clarifier",
    "confirmer",
    "process_generator",
    "modifier",
)


def _extract_process_name_from_xml(bpmn_xml: str) -> str:
    """Extract the human-readable process name from BPMN XML.

    The pipeline compiler (pipeline.mjs) puts the process name on
    ``<bpmn:Participant name="...">`` (the pool header), **not** on
    ``<bpmn:Process>``.  We check both, preferring the participant name.
    Returns an empty string if no name is found.
    """
    if not bpmn_xml:
        return ""

    # 1. Check bpmn:Participant name (where pipeline.mjs puts ir.name)
    match = re.search(r'<bpmn:Participant[^>]+name="([^"]+)"', bpmn_xml)
    if match and match.group(1) != "Process":
        return match.group(1)

    # 2. Fallback: check bpmn:Process name attribute
    match = re.search(r'<bpmn:Process[^>]+name="([^"]+)"', bpmn_xml)
    if match:
        return match.group(1)

    return ""


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


class ProsAllyAgent:
    """Orchestrates intent classification and clarification for process modelling requests."""

    def __init__(self):
        self._config = dict(get_agent_config(AGENT_ID) or {})
        self._config.setdefault("agent_id", AGENT_ID)
        self._llm    = get_llm_adapter_from_settings(self._config)
        self._instructions = self._load_instructions()

    def _load_instructions(self) -> dict:
        """Load all sub-prompt instructions from AI Agent Configuration.

        Raises frappe.ValidationError if a required sub-prompt is missing,
        directing the user to populate it in the AI Agent Configuration UI.
        """
        sub_prompts = (self._config or {}).get("sub_prompts", {})
        instructions = {}

        for key in _REQUIRED_SUB_PROMPTS:
            prompt = sub_prompts.get(key, {}).get("prompt")
            if not prompt:
                import frappe
                frappe.throw(
                    f"AI Agent Configuration for '{AGENT_ID}' is missing "
                    f"the required sub-prompt '{key}'. "
                    f"Please add it in the AI Agent Configuration DocType."
                )

        return instructions



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
            # Detect whether the original XML uses lanes so the LLM preserves the structure
            has_lanes = "laneSet" in current_xml or "bpmn:laneSet" in current_xml
            lane_status = "HAS_LANES" if has_lanes else "NO_LANES"
            parts.append(f"LANE STATUS: {lane_status}")
            if not has_lanes:
                parts.append(
                    "IMPORTANT: This diagram has NO lanes/pools. "
                    "Do NOT add lanes to the output IR. Omit the \"lanes\" key entirely. "
                    "Do NOT add \"lane\" fields to any nodes. "
                    "Preserve the flat process structure."
                )

            # Extract element IDs from the XML so the LLM has an explicit lookup table.
            # This prevents the LLM from inventing new IDs for existing elements.
            id_table = self._extract_element_ids(current_xml)
            if id_table:
                parts.append(
                    "ELEMENT ID TABLE — you MUST use these EXACT IDs for existing elements:\n"
                    + id_table
                    + "\nDo NOT rename any of these IDs. Only NEW elements get new IDs."
                )

            parts.append(f"Current BPMN XML to analyse and modify:\n{current_xml.strip()}")
        parts.append("Output the complete IR JSON for the modified process now.")
        return "\n\n".join(parts)

    @staticmethod
    def _extract_element_ids(xml: str) -> str:
        """Parse BPMN XML and return a table of element IDs the LLM must preserve."""
        import re as _re
        lines = []
        # Two-pass: first capture each opening tag + all its attributes,
        # then extract id and name from the attribute string separately.
        tag_pattern = _re.compile(r'<bpmn:(\w+)\s([^>]*?)/?>') 
        skip_types = {
            "definitions", "process", "collaboration", "participant",
            "laneSet", "lane", "BPMNDiagram", "BPMNPlane",
            "BPMNShape", "BPMNEdge", "messageEventDefinition",
            "timerEventDefinition", "conditionalEventDefinition",
            "signalEventDefinition", "terminateEventDefinition",
            "dataObject", "incoming", "outgoing", "conditionExpression",
        }
        for m in tag_pattern.finditer(xml):
            bpmn_type = m.group(1)
            attrs_str = m.group(2)
            if bpmn_type in skip_types:
                continue
            id_m = _re.search(r'id="([^"]+)"', attrs_str)
            if not id_m:
                continue
            elem_id = id_m.group(1)
            name_m = _re.search(r'name="([^"]*)"', attrs_str)
            elem_name = name_m.group(1) if name_m else None
            label = f' name="{elem_name}"' if elem_name else ""
            lines.append(f'  {bpmn_type} id="{elem_id}"{label}')
        return "\n".join(lines)

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

            if confirmed_action == "MODIFY_EXISTING" and current_xml.strip():
                modifier_prompt = self._build_modifier_prompt(process_name, chat_history, current_xml)
                bpmn_xml, problems = await self._generate_and_validate("modifier", modifier_prompt)
                note = (
                    f" ({len(problems)} issue(s) remain — review the canvas.)"
                    if problems else ""
                )

                # Transfer extension properties from old XML to new XML
                from one_bpmn.agents.google_adk.prosally_agent.xml_property_preserver import (
                    transfer_properties, format_removal_warning,
                )
                merged_xml, removed_elements = transfer_properties(current_xml, bpmn_xml)

                # If configured elements will be removed, ask for user approval first
                if removed_elements:
                    warning = format_removal_warning(removed_elements)
                    return {
                        "intent":        "CONFIRM_REMOVAL",
                        "action_intent": "MODIFY_EXISTING",
                        "response":      warning,
                        "options":       ["Yes, apply changes", "No, keep existing"],
                        "pending_xml":   merged_xml,
                    }

                xml_name = _extract_process_name_from_xml(merged_xml) or process_name or "process"
                return {
                    "intent":        "BPMN_MODIFIED",
                    "action_intent": "MODIFY_EXISTING",
                    "bpmn_xml":      merged_xml,
                    "response":      f"I've updated the {xml_name} process.{note} All existing configurations have been preserved. Review the changes on the canvas.",
                    "options":       [],
                }

            generator_prompt = self._build_generator_prompt(process_name, confirmed_action, chat_history)
            bpmn_xml, problems = await self._generate_and_validate("process_generator", generator_prompt)
            note = (
                f" ({len(problems)} issue(s) remain — review the canvas.)"
                if problems else ""
            )
            xml_name = _extract_process_name_from_xml(bpmn_xml) or process_name or "process"
            return {
                "intent":        "BPMN_GENERATED",
                "action_intent": confirmed_action,
                "bpmn_xml":      bpmn_xml,
                "response":      f"I've generated the {xml_name} process model.{note} Review it on the canvas.",
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
            redirect_msg = sub_prompts.get("redirect", {}).get(
                "prompt",
                "I'm here to help with process modelling. I'm not able to help with that request."
            )
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

        # For OVERWRITE_EXISTING, warn about configured elements that will be lost
        if intent == "OVERWRITE_EXISTING" and current_xml.strip():
            from one_bpmn.agents.google_adk.prosally_agent.xml_property_preserver import (
                extract_configured_elements, summarize_configured_elements,
            )
            configured = extract_configured_elements(current_xml)
            if configured:
                overwrite_warning = summarize_configured_elements(configured)
                response_text = f"{response_text}\n\n⚠️ **Warning:**\n{overwrite_warning}"

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
