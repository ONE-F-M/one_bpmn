# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
ProsAlly deterministic tools.

These are the non-LLM steps of ProsAlly's IR pipeline, extracted as standalone,
unit-testable functions and exposed as ``ToolSpec`` entries in ``PROSALLY_TOOLS``
so the Epic-4 multi-turn loop can call them directly (the Camunda agentic-AI
tool-calling pattern). The LLM-reasoning steps (intent classify / clarify /
confirm / generate IR) stay in the loop; these are the things the model cannot
do itself:

    get_diagram_facts    read the current diagram (process name, lanes, element ids)
    compile_ir           IR JSON -> BPMN XML via spiff/pipeline.mjs
    validate_bpmn        semantic lint + IR-level fix hints
    preserve_properties  transfer extension config from an old diagram to a new one

Each core function returns a plain dict (ergonomic for Python callers and
tests). The ToolSpec wrappers JSON-encode the result to match the tool-result
convention used across ``agents/`` (see tool_for_server_scripts.py /
tool_registry.py) so a tool-calling loop handles them identically to any other
tool.

This is the single source of truth for these transforms — ``prosally_agent.py``
delegates to it, so the agent and the future loop never diverge.
"""

from __future__ import annotations

import json
import os
import re
import subprocess


# ── IR repair hints (rule name -> IR-level fix description) ──────────────────
# Turns cryptic linter rule ids into IR-level instructions the LLM can act on.
# Kept here (not in the orchestrator) so any consumer of ``validate_bpmn`` gets
# self-repair guidance for free.
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

# Rules whose problems are fixed by the compiler, not by LLM IR changes.
_IR_IGNORABLE_RULES: frozenset[str] = frozenset({"no-bpmndi"})

# Element types that are structural containers / DI / definitions — never part
# of the "IDs the LLM must preserve" table.
_ID_SKIP_TYPES: frozenset[str] = frozenset({
    "definitions", "process", "collaboration", "participant",
    "laneSet", "lane", "BPMNDiagram", "BPMNPlane",
    "BPMNShape", "BPMNEdge", "messageEventDefinition",
    "timerEventDefinition", "conditionalEventDefinition",
    "signalEventDefinition", "terminateEventDefinition",
    "dataObject", "incoming", "outgoing", "conditionExpression",
})


# ── Node.js discovery + pipeline invocation ─────────────────────────────────
def _find_node() -> str | None:
    """Return the path to a Node.js ≥ 18 binary, falling back to whatever is in PATH."""
    import shutil

    nvm_dir = os.path.join(os.path.expanduser("~"), ".nvm", "versions", "node")
    if os.path.isdir(nvm_dir):
        try:
            entries = os.listdir(nvm_dir)
        except OSError:
            entries = []
        versions: list[tuple[tuple[int, int, int], str]] = []
        for entry in entries:
            if not entry.startswith("v"):
                continue
            candidate = os.path.join(nvm_dir, entry, "bin", "node")
            if not (os.path.isfile(candidate) and os.access(candidate, os.X_OK)):
                continue
            try:
                parts = entry.lstrip("v").split(".")
                major, minor, patch = (int(parts[0]), int(parts[1]), int(parts[2]))
            except (ValueError, IndexError):
                continue
            if major >= 18:
                versions.append(((major, minor, patch), candidate))
        if versions:
            versions.sort(key=lambda x: x[0], reverse=True)
            return versions[0][1]
    return shutil.which("node")


def _pipeline_path() -> str:
    """Absolute path to spiff/pipeline.mjs, resolved relative to this module.

    tools.py lives in the same directory as prosally_agent.py, so the relative
    hop is identical to the original agent's.
    """
    return os.path.normpath(os.path.join(
        os.path.dirname(__file__),
        "..", "..", "..", "..",
        "spiff", "pipeline.mjs",
    ))


def compile_ir(ir: dict) -> dict:
    """Compile an IR dict into BPMN XML via ``spiff/pipeline.mjs``.

    Runs the Node pipeline (normalise → compile → layout) in a subprocess and
    returns its raw JSON result:

        {"ok": bool, "xml": str, "problems": list, "normalizedIR": dict?}

    Never raises — a missing node binary, empty output, timeout, or any other
    failure is returned as ``{"ok": False, "xml": "", "problems": [...]}`` so a
    tool-calling loop stays alive.
    """
    node = _find_node()
    if not node:
        return {
            "ok": False, "xml": "",
            "problems": [{"kind": "fatal", "message": "node not found in PATH"}],
        }
    try:
        result = subprocess.run(
            [node, _pipeline_path()],
            input=json.dumps(ir),
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
    except Exception as exc:  # noqa: BLE001 — must never propagate into the loop
        return {"ok": False, "xml": "", "problems": [{"kind": "fatal", "message": str(exc)}]}


# ── Diagram reading (pure string parsing) ────────────────────────────────────
def extract_process_name(bpmn_xml: str) -> str:
    """Extract the human-readable process name from BPMN XML.

    pipeline.mjs puts the process name on ``<bpmn:Participant name="...">`` (the
    pool header), not on ``<bpmn:Process>``. Prefer the participant name; fall
    back to the process name. Returns "" if none is found.
    """
    if not bpmn_xml:
        return ""
    match = re.search(r'<bpmn:Participant[^>]+name="([^"]+)"', bpmn_xml)
    if match and match.group(1) != "Process":
        return match.group(1)
    match = re.search(r'<bpmn:Process[^>]+name="([^"]+)"', bpmn_xml)
    if match:
        return match.group(1)
    return ""


def extract_element_ids(xml: str) -> str:
    """Return a table of element IDs the LLM must preserve during a modify.

    Skips structural/DI/definition elements (see ``_ID_SKIP_TYPES``) and lists
    each real element as ``  <type> id="..." name="..."``.
    """
    lines = []
    tag_pattern = re.compile(r'<bpmn:(\w+)\s([^>]*?)/?>')
    for m in tag_pattern.finditer(xml or ""):
        bpmn_type = m.group(1)
        attrs_str = m.group(2)
        if bpmn_type in _ID_SKIP_TYPES:
            continue
        id_m = re.search(r'id="([^"]+)"', attrs_str)
        if not id_m:
            continue
        elem_id = id_m.group(1)
        name_m = re.search(r'name="([^"]*)"', attrs_str)
        elem_name = name_m.group(1) if name_m else None
        label = f' name="{elem_name}"' if elem_name else ""
        lines.append(f'  {bpmn_type} id="{elem_id}"{label}')
    return "\n".join(lines)


def has_lanes(xml: str) -> bool:
    """True when the diagram uses swimlanes/pools."""
    return bool(xml) and ("laneSet" in xml or "bpmn:laneSet" in xml)


def get_diagram_facts(xml: str) -> dict:
    """Read the salient facts of the current diagram the LLM needs to modify it.

    Returns ``{process_name, has_lanes, element_ids}`` where ``element_ids`` is
    the newline-delimited preserve-these-IDs table (empty string when none).
    """
    return {
        "process_name": extract_process_name(xml),
        "has_lanes": has_lanes(xml),
        "element_ids": extract_element_ids(xml),
    }


# ── Validation + hint translation ────────────────────────────────────────────
def translate_problems(problems: list) -> list[str]:
    """Convert pipeline problem dicts into IR-level fix hints (deduped, ignorable rules removed)."""
    hints: list[str] = []
    seen: set[tuple] = set()
    for p in problems:
        rule = p.get("rule") or ""
        kind = p.get("kind") or ""
        eid = p.get("elementId") or ""
        msg = p.get("message") or str(p)

        if rule in _IR_IGNORABLE_RULES:
            continue

        key = (rule or kind, eid)
        if key in seen:
            continue
        seen.add(key)

        hint_body = _RULE_HINTS.get(rule, msg)
        label = rule or kind or "problem"
        if eid:
            hints.append(f"[{label}] Element '{eid}': {hint_body}")
        else:
            hints.append(f"[{label}] {hint_body}")
    return hints


def translate_violations(violations: list[str]) -> list[str]:
    """Convert Python bpmn_validator violation strings to IR-level fix hints (deduped)."""
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


def validate_bpmn(xml: str) -> dict:
    """Semantic-lint a BPMN XML string and return actionable fix hints.

    Returns ``{valid, violations, fix_hints}`` where ``violations`` are the raw
    validator strings and ``fix_hints`` are the IR-level repair instructions a
    self-correcting loop can feed straight back to the model.
    """
    from one_bpmn.security.bpmn_validator import validate_bpmn_xml

    result = validate_bpmn_xml(xml)
    violations = result.get("violations", []) or []
    return {
        "valid": bool(result.get("valid")),
        "violations": violations,
        "fix_hints": translate_violations(violations),
    }


# ── Property preservation ────────────────────────────────────────────────────
def preserve_properties(old_xml: str, new_xml: str) -> dict:
    """Transfer extension config from an old diagram onto a freshly generated one.

    Returns ``{merged_xml, removed_elements}``. ``removed_elements`` lists the
    configured elements present in ``old_xml`` that no longer exist in
    ``new_xml`` (so a caller can warn before applying).
    """
    from one_bpmn.agents.google_adk.prosally_agent.xml_property_preserver import (
        transfer_properties,
    )

    merged_xml, removed_elements = transfer_properties(old_xml, new_xml)
    return {"merged_xml": merged_xml, "removed_elements": removed_elements}


# ── MCP/ToolSpec registry ─────────────────────────────────────────────────────
# ToolSpec.fn returns a JSON string (the tool-result convention the llm_provider
# loops consume); the core functions above return dicts for Python/test callers.
def _import_toolspec():
    from one_bpmn.agents.llm_provider.base import ToolSpec
    return ToolSpec


def _build_registry() -> list:
    ToolSpec = _import_toolspec()
    return [
        ToolSpec(
            fn=lambda xml="": json.dumps(get_diagram_facts(xml)),
            name="get_diagram_facts",
            description=(
                "Read the current BPMN diagram: returns its process name, whether it "
                "uses swimlanes, and the table of existing element ids that must be "
                "preserved when modifying it."
            ),
            parameters={"xml": {"type": "string", "description": "The current BPMN 2.0 XML."}},
            required=["xml"],
        ),
        ToolSpec(
            fn=lambda ir=None: json.dumps(compile_ir(ir or {})),
            name="compile_ir",
            description=(
                "Compile a process IR JSON object into BPMN 2.0 XML via the pipeline "
                "(normalise, compile, layout). Returns {ok, xml, problems, normalizedIR}."
            ),
            parameters={"ir": {"type": "object", "description": "The process IR JSON to compile."}},
            required=["ir"],
        ),
        ToolSpec(
            fn=lambda xml="": json.dumps(validate_bpmn(xml)),
            name="validate_bpmn",
            description=(
                "Semantic-lint BPMN 2.0 XML. Returns {valid, violations, fix_hints} — "
                "fix_hints are IR-level instructions for correcting any problems."
            ),
            parameters={"xml": {"type": "string", "description": "The BPMN 2.0 XML to validate."}},
            required=["xml"],
        ),
        ToolSpec(
            fn=lambda old_xml="", new_xml="": json.dumps(preserve_properties(old_xml, new_xml)),
            name="preserve_properties",
            description=(
                "Transfer extension configuration (service/task config, documentation) from "
                "an old diagram onto a newly generated one, matching by element id. Returns "
                "{merged_xml, removed_elements}."
            ),
            parameters={
                "old_xml": {"type": "string", "description": "The existing diagram XML with configuration."},
                "new_xml": {"type": "string", "description": "The freshly generated diagram XML."},
            },
            required=["old_xml", "new_xml"],
        ),
    ]


PROSALLY_TOOLS: list = _build_registry()
