"""
Post-generation BPMN validator for ProsAlly.

Parses the generated XML and checks it against the bpmnlint rule set.
Returns a structured list of human-readable violations that are injected
back into the LLM prompt for a targeted correction pass.

Rules implemented (mirrors https://github.com/bpmn-io/bpmnlint/tree/main/docs/rules):
  R00  task-type              — no plain bpmn:task; use userTask/scriptTask/serviceTask/manualTask
  R01  start-event-required   — exactly one startEvent per process
  R02  end-event-required     — at least one endEvent per process
  R03  single-blank-start-event — only one untyped startEvent
  R04  no-disconnected        — every flow element has ≥1 connection
  R05  no-implicit-start      — only startEvent has 0 incoming
  R06  no-implicit-end        — only endEvent has 0 outgoing
  R07  no-implicit-split      — tasks/events have ≤1 outgoing flow
  R08  fake-join              — tasks/events have ≤1 incoming flow
  R09  no-gateway-join-fork   — gateway does JOIN or FORK, never both
  R10  superfluous-gateway    — no gateway with exactly 1 in + 1 out
  R11  conditional-flows      — exclusive gateway split needs default + conditions
  R12  label-required         — every element has a non-empty name
  R13  no-bpmndi              — every semantic element has a DI shape/edge
  R14  no-complex-gateway     — complexGateway forbidden
  R15  no-inclusive-gateway   — inclusiveGateway forbidden
  R16  no-duplicate-sequence-flows — no two flows with same source+target
"""

from xml.etree import ElementTree as ET

# ── Namespace constants ───────────────────────────────────────────────────────
BPMN = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI = "http://www.omg.org/spec/BPMN/20100524/DI"

def _t(local):
    return f"{{{BPMN}}}{local}"

# ── Element type sets ─────────────────────────────────────────────────────────
_PLAIN_TASK   = _t("task")
_TYPED_TASKS  = {_t(x) for x in ("userTask", "scriptTask", "serviceTask", "manualTask",
                                   "businessRuleTask", "callActivity", "subProcess")}
_ALL_TASKS    = _TYPED_TASKS | {_plain_task := _t("task")}

_EVENTS       = {_t(x) for x in ("startEvent", "endEvent",
                                   "intermediateThrowEvent", "intermediateCatchEvent",
                                   "boundaryEvent")}
_GATEWAYS     = {_t(x) for x in ("exclusiveGateway", "parallelGateway",
                                   "eventBasedGateway", "inclusiveGateway", "complexGateway")}
_FLOW_NODES   = _ALL_TASKS | _EVENTS | _GATEWAYS
_TASK_EVENTS  = _ALL_TASKS | {_t("startEvent"), _t("endEvent"),
                               _t("intermediateThrowEvent"), _t("intermediateCatchEvent")}
_SEQUENCE_FLOW = _t("sequenceFlow")


def _label(el: ET.Element) -> str:
    name = (el.get("name") or "").strip()
    eid  = el.get("id") or "?"
    return f'"{name}" (id={eid})' if name else f"(id={eid})"


def _element_type_hint(el: ET.Element) -> str:
    """Return a suggestion for plain bpmn:task elements based on their name."""
    name = (el.get("name") or "").lower()
    system_keywords = (
        "system", "send", "email", "notif", "creat", "updat", "check",
        "validat", "calculat", "look up", "generat", "process", "set up",
        "access", "record", "log", "fetch", "sync",
    )
    human_keywords = (
        "fill", "submit", "review", "approve", "reject", "select",
        "assign", "sign", "enter", "confirm", "manager", "hr", "employee",
    )
    if any(k in name for k in system_keywords):
        return "<bpmn:scriptTask> (system runs this automatically)"
    if any(k in name for k in human_keywords):
        return "<bpmn:userTask> (a person does this)"
    return "<bpmn:userTask> if a person does it, or <bpmn:scriptTask> if the system does it"


# ── Main validator ────────────────────────────────────────────────────────────

def validate_bpmn_xml(xml_string: str) -> dict:
    """
    Parse xml_string and check all implemented bpmnlint rules.

    Returns:
        {
            "valid":      bool,
            "violations": [str],   # human-readable, LLM-injectable
        }
    """
    violations: list[str] = []

    # ── Parse ─────────────────────────────────────────────────────────────────
    try:
        root = ET.fromstring(xml_string.strip())
    except ET.ParseError as exc:
        return {"valid": False, "violations": [f"XML parse error: {exc}"]}

    process_el = root.find(_t("process"))
    if process_el is None:
        return {"valid": False, "violations": ["No <bpmn:process> element found in the document"]}

    # ── Build index ───────────────────────────────────────────────────────────
    elements: dict[str, ET.Element] = {}
    incoming: dict[str, int] = {}
    outgoing: dict[str, int] = {}
    flows_by_source: dict[str, list[ET.Element]] = {}
    seen_pairs: dict[tuple, str] = {}

    # Tags that are structural containers, not flow nodes — skip from all checks
    _SKIP_TAGS = {_t("laneSet"), _t("lane"), _t("flowNodeRef")}

    for child in process_el:
        eid = child.get("id")
        if not eid or child.tag in _SKIP_TAGS:
            continue
        elements[eid] = child
        if child.tag == _SEQUENCE_FLOW:
            src = child.get("sourceRef")
            tgt = child.get("targetRef")
            if src:
                outgoing[src] = outgoing.get(src, 0) + 1
                flows_by_source.setdefault(src, []).append(child)
            if tgt:
                incoming[tgt] = incoming.get(tgt, 0) + 1

    # ── R00 — task-type ───────────────────────────────────────────────────────
    for eid, el in elements.items():
        if el.tag == _t("task"):
            hint = _element_type_hint(el)
            violations.append(
                f"[task-type] Task {_label(el)} uses plain <bpmn:task> which is forbidden. "
                f"Change it to {hint}."
            )

    # ── R01 — start-event-required ────────────────────────────────────────────
    start_events = [el for el in elements.values() if el.tag == _t("startEvent")]
    if not start_events:
        violations.append("[start-event-required] Process has no startEvent.")

    # ── R02 — end-event-required ──────────────────────────────────────────────
    end_events = [el for el in elements.values() if el.tag == _t("endEvent")]
    if not end_events:
        violations.append("[end-event-required] Process has no endEvent.")

    # ── R03 — single-blank-start-event ────────────────────────────────────────
    def _is_blank_start(el: ET.Element) -> bool:
        return all(
            ch.tag in (_t("incoming"), _t("outgoing"))
            for ch in el
        )

    blank_starts = [el for el in start_events if _is_blank_start(el)]
    if len(blank_starts) > 1:
        ids = ", ".join(el.get("id", "?") for el in blank_starts)
        violations.append(
            f"[single-blank-start-event] Multiple blank startEvents found ({ids}). "
            "Keep exactly one."
        )

    # ── R04 — no-disconnected ─────────────────────────────────────────────────
    for eid, el in elements.items():
        if el.tag not in _FLOW_NODES:
            continue
        if incoming.get(eid, 0) == 0 and outgoing.get(eid, 0) == 0:
            violations.append(
                f"[no-disconnected] Element {_label(el)} has no incoming or outgoing flows. "
                "Connect it or remove it."
            )

    # ── R05 — no-implicit-start ───────────────────────────────────────────────
    for eid, el in elements.items():
        if el.tag in _FLOW_NODES and el.tag != _t("startEvent"):
            if incoming.get(eid, 0) == 0:
                violations.append(
                    f"[no-implicit-start] Element {_label(el)} has no incoming flow. "
                    "Only startEvent may have zero incoming flows."
                )

    # ── R06 — no-implicit-end ────────────────────────────────────────────────
    for eid, el in elements.items():
        if el.tag in _FLOW_NODES and el.tag != _t("endEvent"):
            if outgoing.get(eid, 0) == 0:
                violations.append(
                    f"[no-implicit-end] Element {_label(el)} has no outgoing flow. "
                    "Only endEvent may have zero outgoing flows."
                )

    # ── R07 — no-implicit-split ───────────────────────────────────────────────
    for eid, el in elements.items():
        if el.tag in _TASK_EVENTS:
            n = outgoing.get(eid, 0)
            if n > 1:
                violations.append(
                    f"[no-implicit-split] Task/event {_label(el)} has {n} outgoing flows. "
                    "Tasks and events must have at most 1 outgoing flow. "
                    "Insert an explicit splitting gateway after it."
                )

    # ── R08 — fake-join ───────────────────────────────────────────────────────
    for eid, el in elements.items():
        if el.tag in _TASK_EVENTS:
            n = incoming.get(eid, 0)
            if n > 1:
                violations.append(
                    f"[fake-join] Task/event {_label(el)} has {n} incoming flows. "
                    "Tasks and events must have at most 1 incoming flow. "
                    "Insert an explicit joining gateway before it — ALL flows including the initial must go through it."
                )

    # ── R09 — no-gateway-join-fork ────────────────────────────────────────────
    for eid, el in elements.items():
        if el.tag in _GATEWAYS:
            n_in  = incoming.get(eid, 0)
            n_out = outgoing.get(eid, 0)
            if n_in > 1 and n_out > 1:
                violations.append(
                    f"[no-gateway-join-fork] Gateway {_label(el)} both joins ({n_in} incoming) "
                    f"and forks ({n_out} outgoing). A gateway must do only one: "
                    "split into a joining gateway followed by a separate forking gateway."
                )

    # ── R10 — superfluous-gateway ─────────────────────────────────────────────
    for eid, el in elements.items():
        if el.tag in _GATEWAYS:
            if incoming.get(eid, 0) == 1 and outgoing.get(eid, 0) == 1:
                violations.append(
                    f"[superfluous-gateway] Gateway {_label(el)} has exactly 1 incoming and "
                    "1 outgoing flow — it serves no purpose. Remove it and connect its "
                    "predecessor directly to its successor."
                )

    # ── R11 — conditional-flows ───────────────────────────────────────────────
    for eid, el in elements.items():
        if el.tag == _t("exclusiveGateway") and outgoing.get(eid, 0) > 1:
            default_id = el.get("default")
            if not default_id:
                violations.append(
                    f"[conditional-flows] ExclusiveGateway {_label(el)} splits but has no "
                    "'default' attribute. Add default=\"Flow_[id]\" pointing to the else/fallback flow."
                )
            for flow in flows_by_source.get(eid, []):
                if flow.get("id") == default_id:
                    continue
                has_cond = flow.find(_t("conditionExpression")) is not None
                if not has_cond:
                    fn = flow.get("name") or flow.get("id") or "?"
                    violations.append(
                        f"[conditional-flows] Flow '{fn}' from exclusiveGateway {_label(el)} "
                        "has no <bpmn:conditionExpression>. Every non-default outgoing flow "
                        "of an exclusive gateway must have a condition."
                    )

    # ── R12 — label-required ─────────────────────────────────────────────────
    for eid, el in elements.items():
        if el.tag in _FLOW_NODES:
            if not (el.get("name") or "").strip():
                violations.append(
                    f"[label-required] Element with id='{eid}' (type={el.tag.split('}')[1]}) "
                    "has no name. Add a descriptive name attribute."
                )

    # ── R13 — no-bpmndi ──────────────────────────────────────────────────────
    di_diagram = root.find(f"{{{BPMNDI}}}BPMNDiagram")
    if di_diagram is not None:
        plane = di_diagram.find(f"{{{BPMNDI}}}BPMNPlane")
        if plane is not None:
            di_refs: set[str] = set()
            for shape in plane.findall(f"{{{BPMNDI}}}BPMNShape"):
                di_refs.add(shape.get("bpmnElement", ""))
            for edge in plane.findall(f"{{{BPMNDI}}}BPMNEdge"):
                di_refs.add(edge.get("bpmnElement", ""))

            for eid, el in elements.items():
                if el.tag in (_FLOW_NODES | {_SEQUENCE_FLOW}):
                    if eid not in di_refs:
                        shape_or_edge = "BPMNEdge" if el.tag == _SEQUENCE_FLOW else "BPMNShape"
                        violations.append(
                            f"[no-bpmndi] Element {_label(el)} has no {shape_or_edge} in the "
                            "DI section. Add a placeholder shape/edge for it."
                        )

    # ── R14 — no-complex-gateway ─────────────────────────────────────────────
    for eid, el in elements.items():
        if el.tag == _t("complexGateway"):
            violations.append(
                f"[no-complex-gateway] Gateway {_label(el)} is a complexGateway which is forbidden. "
                "Replace it with an exclusiveGateway or parallelGateway."
            )

    # ── R15 — no-inclusive-gateway ───────────────────────────────────────────
    for eid, el in elements.items():
        if el.tag == _t("inclusiveGateway"):
            violations.append(
                f"[no-inclusive-gateway] Gateway {_label(el)} is an inclusiveGateway which is forbidden. "
                "Replace it with an exclusiveGateway or parallelGateway."
            )

    # ── R16 — no-duplicate-sequence-flows ────────────────────────────────────
    for eid, el in elements.items():
        if el.tag == _SEQUENCE_FLOW:
            src = el.get("sourceRef", "")
            tgt = el.get("targetRef", "")
            pair = (src, tgt)
            if pair in seen_pairs:
                violations.append(
                    f"[no-duplicate-sequence-flows] Two flows connect '{src}' → '{tgt}'. "
                    f"Remove the duplicate (keep one of: {seen_pairs[pair]}, {eid})."
                )
            else:
                seen_pairs[pair] = eid

    return {
        "valid":      len(violations) == 0,
        "violations": violations,
    }
