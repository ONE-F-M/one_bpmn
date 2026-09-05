# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
BPMN IR pipeline — shared deterministic infrastructure.

The non-LLM steps of the process-modelling pipeline, kept as importable Python
because they cannot live inside a BPMN Script Task body: ``compile_ir`` shells
out to ``spiff/pipeline.mjs`` via ``subprocess`` (and ``os``/``shutil`` for node
discovery), and the security gate (``deep_inspect_script``) bans those modules
in gated script bodies. The ProsAlly agent's LLM/prompt/routing logic now lives
inline in its BPMN tool scripts; these transforms are the shared seam those
scripts import.

    check_topology        is the flow graph planar (zero crossings possible)?
    flow_pairs_from_xml   (source, target) pairs of an existing diagram
    compile_ir            IR JSON -> BPMN XML via spiff/pipeline.mjs (subprocess)
    extract_process_name  read the pool/process name out of BPMN XML
    extract_element_ids   the preserve-these-ids table for a modify turn
    has_lanes             does the diagram use swimlanes/pools
    get_diagram_facts     bundle of the three reads above
    translate_problems    pipeline problem dicts -> IR-level fix hints
    translate_violations  validator strings -> IR-level fix hints
    validate_bpmn         semantic lint + fix hints

Previously ``one_bpmn/agents/google_adk/prosally_agent/tools.py`` (deleted with
the rest of the ProsAlly agent package during the per-agent migration).
"""

from __future__ import annotations

import json
import os
import re
import subprocess


# ── IR repair hints (rule name -> IR-level fix description) ──────────────────
# Turns cryptic linter rule ids into IR-level instructions the LLM can act on.
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
    "non-planar": (
        "The flow graph cannot be drawn without lines crossing; no layout can change that. "
        "If a returning flow can join at an existing merge gateway with the same behaviour, join there. "
        "Otherwise keep the IR as it is and tell the user one crossing is unavoidable. "
        "Do not regenerate to chase a crossing-free drawing."
    ),
}

# Rules whose problems are fixed by the compiler, not by LLM IR changes.
_IR_IGNORABLE_RULES: frozenset[str] = frozenset({
    "no-bpmndi", "edge-crossing", "edge-through-shape", "collinear-overlap", "label-collision",
})

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

    This module lives at ``one_bpmn/one_bpmn/agents/bpmn_ir_pipeline.py``; the
    pipeline lives at ``one_bpmn/spiff/pipeline.mjs`` (the app root's spiff dir),
    two directories up from ``agents/``.
    """
    return os.path.normpath(os.path.join(
        os.path.dirname(__file__),
        "..", "..",
        "spiff", "pipeline.mjs",
    ))


# ── Topology ─────────────────────────────────────────────────────────────────
def _flow_pairs(flows) -> list[tuple[str, str]]:
    """IR flow dicts or (from, to) tuples, minus self-loops and blanks."""
    pairs = []
    for f in flows or []:
        a, b = (f.get("from"), f.get("to")) if isinstance(f, dict) else (f[0], f[1])
        if a and b and a != b:
            pairs.append((str(a), str(b)))
    return pairs


def flow_pairs_from_xml(xml: str) -> list[tuple[str, str]]:
    """The (sourceRef, targetRef) of every sequence flow in a BPMN XML string."""
    pairs = []
    for m in re.finditer(r"<bpmn2?:sequenceFlow\b([^>]*)>", xml or ""):
        s = re.search(r'sourceRef="([^"]+)"', m.group(1))
        t = re.search(r'targetRef="([^"]+)"', m.group(1))
        if s and t:
            pairs.append((s.group(1), t.group(1)))
    return pairs


def check_topology(flows) -> dict:
    """Can the flow graph be drawn with no crossing lines at all?

    A non-planar graph forces a crossing in every layout, so ``planar`` fixes the
    crossing count the layout audit holds the drawing to. ``obstruction`` names
    the nodes of the Kuratowski subgraph — the part that cannot be flattened.
    """
    pairs = _flow_pairs(flows)
    if not pairs:
        return {"planar": True, "obstruction": [], "min_crossings": 0}
    try:
        import networkx as nx
    except ImportError:  # pragma: no cover — networkx ships with the bench env
        return {"planar": None, "obstruction": [], "min_crossings": 0}
    graph = nx.Graph()
    graph.add_edges_from(pairs)
    planar, cert = nx.check_planarity(graph, counterexample=True)
    obstruction = [] if planar else sorted(cert.nodes())
    return {"planar": bool(planar), "obstruction": obstruction, "min_crossings": 0 if planar else 1}


def _topology_problem(topo: dict, names: dict) -> dict:
    who = ", ".join(names.get(n, n) for n in topo.get("obstruction", [])[:6])
    return {
        "kind": "topology", "rule": "non-planar", "elementId": "", "nodes": topo.get("obstruction", []),
        "message": (
            "This process cannot be drawn without a crossing line: the paths through "
            f"{who} cannot all be laid flat. One crossing is the minimum."
        ),
    }


def compile_ir(ir: dict) -> dict:
    """Compile an IR dict into BPMN XML via ``spiff/pipeline.mjs``.

    Runs the Node pipeline (normalise → compile → layout → audit) in a
    subprocess and returns its JSON result:

        {"ok": bool, "xml": str, "problems": list, "normalizedIR": dict?,
         "layout": dict?, "topology": dict}

    ``topology`` is computed here, before the subprocess, so it is present even
    when the pipeline fails. A non-planar graph adds a ``topology`` problem
    without turning ``ok`` off: the XML compiles, and the crossing is a fact
    about the process rather than a failure. A drawing with more crossings than
    the graph requires adds a ``layout`` problem — the compiler's defect, never
    the IR's.

    Never raises — a missing node binary, empty output, timeout, or any other
    failure is returned as ``{"ok": False, "xml": "", "problems": [...]}`` so a
    tool-calling loop stays alive.
    """
    try:
        topo = check_topology((ir or {}).get("flows"))
    except Exception:  # noqa: BLE001 — topology must never block compilation
        topo = {"planar": None, "obstruction": [], "min_crossings": 0}

    def fail(message):
        return {"ok": False, "xml": "", "topology": topo, "problems": [{"kind": "fatal", "message": message}]}

    node = _find_node()
    if not node:
        return fail("node not found in PATH")
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
            return fail(result.stderr.strip() or "pipeline produced no output")
        out = json.loads(stdout)
    except subprocess.TimeoutExpired:
        return fail("pipeline timed out after 30 s")
    except Exception as exc:  # noqa: BLE001 — must never propagate into the loop
        return fail(str(exc))

    out["topology"] = topo
    out.setdefault("problems", [])
    if topo.get("planar") is False:
        names = {n.get("id"): n.get("name") or n.get("id") for n in (ir or {}).get("nodes") or [] if n.get("id")}
        out["problems"].append(_topology_problem(topo, names))
    crossings = (out.get("layout") or {}).get("crossings", 0)
    if out.get("ok") and crossings > topo.get("min_crossings", 0):
        out["problems"].append({
            "kind": "layout", "rule": "edge-crossing", "elementId": "",
            "message": (
                f"Drawing has {crossings} crossing(s); the flow graph needs {topo.get('min_crossings', 0)}. "
                "Layout defect, not an IR change."
            ),
        })
    return out


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
