"""
Tests for the IR → BPMN pipeline (pipeline.mjs).

Covers:
  1. Known-good IR compiles to a lint-clean XML document
  2. Task with fan-out (>1 outgoing) compiles clean — normalizeGateways auto-inserts split
  3. Parallel split paired with exclusive join rejected by assertGatewayPairing
  4. IR with deliberate fake-join (>1 incoming to a task) compiles clean — normalizeGateways auto-inserts join
  5. Swimlane IR: BPMNPlane references the collaboration id, not the process id
  6. Swimlane IR: lane bands tile exactly (heights sum to pool inner height, no gaps)
  7. Swimlane IR: every node's DI shape sits within its lane's band
  8. No-lane IR: output is identical whether or not lanes field is omitted
  9. Swimlane IR: a lane with zero members still emits a lane element and a DI shape
 10. Gateway regression: multi-incoming pure-join and multi-outgoing pure-fork both pass

Each test calls pipeline.mjs directly via subprocess so no LLM or Frappe context is needed.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

PIPELINE_PATH = os.path.normpath(os.path.join(
    os.path.dirname(__file__),
    "..", "..",
    "spiff", "pipeline.mjs",
))


def _find_node() -> str | None:
    """Prefer nvm Node 18+ to avoid system Node 12 ESM compatibility issues."""
    home = os.path.expanduser("~")
    for ver in ("v20.19.4", "v20.19.2", "v18.19.0"):
        candidate = os.path.join(home, ".nvm", "versions", "node", ver, "bin", "node")
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return shutil.which("node")


def _run_pipeline(ir_dict: dict) -> dict:
    node = _find_node()
    if not node:
        pytest.skip("node not found in PATH — skipping pipeline test")
    result = subprocess.run(
        [node, PIPELINE_PATH],
        input=json.dumps(ir_dict),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.stdout.strip(), (
        f"pipeline.mjs produced no stdout.\nstderr: {result.stderr.strip()}"
    )
    return json.loads(result.stdout)


# ── Test 1: Known-good IR ──────────────────────────────────────────────────────

def test_known_good_ir_compiles_clean():
    ir = {
        "name": "Leave Request",
        "nodes": [
            {"id": "start",               "type": "startEvent",       "name": "Request Received"},
            {"id": "task_fill",           "type": "userTask",         "name": "Fill Leave Form"},
            {"id": "gw_decision",         "type": "exclusiveGateway", "name": "Approved?"},
            {"id": "task_notify_ok",      "type": "scriptTask",       "name": "Send Approval Email"},
            {"id": "task_notify_reject",  "type": "scriptTask",       "name": "Send Rejection Email"},
            {"id": "end_ok",              "type": "endEvent",         "name": "Leave Approved"},
            {"id": "end_rejected",        "type": "endEvent",         "name": "Leave Rejected"},
        ],
        "flows": [
            {"from": "start",          "to": "task_fill",          "name": "Begin"},
            {"from": "task_fill",      "to": "gw_decision",        "name": "Submitted"},
            {"from": "gw_decision",    "to": "task_notify_ok",     "name": "Yes",     "condition": "approved == true"},
            {"from": "gw_decision",    "to": "task_notify_reject",  "name": "No",     "default": True},
            {"from": "task_notify_ok",     "to": "end_ok",        "name": "Done"},
            {"from": "task_notify_reject", "to": "end_rejected",  "name": "Done"},
        ],
    }

    result = _run_pipeline(ir)

    assert result["ok"] is True, (
        f"Expected ok=True for a valid IR.\nProblems: {result.get('problems')}"
    )
    assert result["xml"].strip().startswith("<?xml"), "Expected XML in 'xml' field"


# ── Test 2: Fan-out task — normalizeGateways inserts split gateway ─────────────

def test_fan_out_task_normalised_to_clean():
    ir = {
        "name": "Parallel Notifications",
        "nodes": [
            {"id": "start",     "type": "startEvent",       "name": "Work Completed"},
            {"id": "task_work", "type": "userTask",         "name": "Complete Work"},
            {"id": "task_email","type": "scriptTask",       "name": "Send Email"},
            {"id": "task_sms",  "type": "scriptTask",       "name": "Send SMS"},
            {"id": "gw_join",   "type": "exclusiveGateway", "name": "Notifications Sent"},
            {"id": "end",       "type": "endEvent",         "name": "Done"},
        ],
        "flows": [
            {"from": "start",      "to": "task_work",  "name": "Begin"},
            {"from": "task_work",  "to": "task_email", "name": "Email"},
            {"from": "task_work",  "to": "task_sms",   "name": "SMS"},
            {"from": "task_email", "to": "gw_join",    "name": "Email Done"},
            {"from": "task_sms",   "to": "gw_join",    "name": "SMS Done"},
            {"from": "gw_join",    "to": "end",        "name": "Finish"},
        ],
    }

    result = _run_pipeline(ir)

    assert result["ok"] is True, (
        f"Expected ok=True — normalizeGateways should have fixed the fan-out.\n"
        f"Problems: {result.get('problems')}"
    )


# ── Test 3: Parallel split + exclusive join → assertGatewayPairing rejects ────

def test_gateway_pairing_mismatch_rejected():
    ir = {
        "name": "Mismatched Gateways",
        "nodes": [
            {"id": "start",    "type": "startEvent",       "name": "Start"},
            {"id": "gw_split", "type": "parallelGateway",  "name": "Split"},
            {"id": "task_a",   "type": "scriptTask",       "name": "Task A"},
            {"id": "task_b",   "type": "scriptTask",       "name": "Task B"},
            # exclusive join claims to close a parallel split — type mismatch
            {"id": "gw_join",  "type": "exclusiveGateway", "name": "Join", "closes": "gw_split"},
            {"id": "end",      "type": "endEvent",         "name": "End"},
        ],
        "flows": [
            {"from": "start",    "to": "gw_split", "name": "Begin"},
            {"from": "gw_split", "to": "task_a",   "name": "Branch A"},
            {"from": "gw_split", "to": "task_b",   "name": "Branch B"},
            {"from": "task_a",   "to": "gw_join",  "name": "A Done"},
            {"from": "task_b",   "to": "gw_join",  "name": "B Done"},
            {"from": "gw_join",  "to": "end",      "name": "Finish"},
        ],
    }

    result = _run_pipeline(ir)

    assert result["ok"] is False, (
        "Expected ok=False — parallel split / exclusive join mismatch must be rejected"
    )
    pairing = [p for p in result.get("problems", []) if p.get("kind") == "pairing"]
    assert pairing, (
        f"Expected at least one 'pairing' problem.\nGot: {result.get('problems')}"
    )
    msg = pairing[0]["message"]
    assert "parallelGateway" in msg or "gw_split" in msg, (
        f"Pairing message should reference the split or its type.\nGot: {msg}"
    )


# ── Test 4: Fake-join IR — normalizeGateways auto-inserts join gateway ─────────

def test_fake_join_normalised_to_clean():
    ir = {
        "name": "Converging Paths",
        "nodes": [
            {"id": "start",        "type": "startEvent",       "name": "Start"},
            {"id": "gw_route",     "type": "exclusiveGateway", "name": "Route Decision"},
            {"id": "task_path_a",  "type": "userTask",         "name": "Handle Path A"},
            {"id": "task_path_b",  "type": "userTask",         "name": "Handle Path B"},
            {"id": "task_confirm", "type": "scriptTask",       "name": "Send Confirmation"},
            {"id": "end",          "type": "endEvent",         "name": "Done"},
        ],
        "flows": [
            {"from": "start",       "to": "gw_route",     "name": "Begin"},
            {"from": "gw_route",    "to": "task_path_a",  "name": "Path A", "condition": "route == 'a'"},
            {"from": "gw_route",    "to": "task_path_b",  "name": "Path B", "default": True},
            # Both paths flow into task_confirm — deliberate fake-join
            {"from": "task_path_a", "to": "task_confirm", "name": "A Done"},
            {"from": "task_path_b", "to": "task_confirm", "name": "B Done"},
            {"from": "task_confirm","to": "end",          "name": "Finish"},
        ],
    }

    result = _run_pipeline(ir)

    assert result["ok"] is True, (
        f"Expected ok=True — normalizeGateways should have inserted a join gateway.\n"
        f"Problems: {result.get('problems')}"
    )
    assert result["xml"].strip().startswith("<?xml"), "Expected XML in 'xml' field"


# ── Helpers shared by swimlane tests ─────────────────────────────────────────

def _parse_bpmndi(xml: str):
    """Return a dict with parsed DI information from the XML string."""
    import xml.etree.ElementTree as ET
    BPMNDI = "http://www.omg.org/spec/BPMN/20100524/DI"
    DC      = "http://www.omg.org/spec/DD/20100524/DC"

    root    = ET.fromstring(xml.strip())
    diagram = root.find(f"{{{BPMNDI}}}BPMNDiagram")
    plane   = diagram.find(f"{{{BPMNDI}}}BPMNPlane") if diagram is not None else None

    shapes = {}
    if plane is not None:
        for s in plane.findall(f"{{{BPMNDI}}}BPMNShape"):
            elem = s.get("bpmnElement")
            b = s.find(f"{{{DC}}}Bounds")
            if b is not None:
                shapes[elem] = {
                    "x": float(b.get("x", 0)),
                    "y": float(b.get("y", 0)),
                    "w": float(b.get("width",  0)),
                    "h": float(b.get("height", 0)),
                }

    return {
        "plane_bpmn_element": plane.get("bpmnElement") if plane is not None else None,
        "shapes": shapes,
    }


def _swimlane_ir():
    """Three-lane leave-request IR (Employee / Manager / System)."""
    return {
        "name": "Leave Request with Lanes",
        "nodes": [
            {"id": "start",           "type": "startEvent",       "name": "Request Received",   "lane": "employee"},
            {"id": "task_fill",       "type": "userTask",         "name": "Fill Leave Form",    "lane": "employee"},
            {"id": "gw_decision",     "type": "exclusiveGateway", "name": "Approved?",          "lane": "manager"},
            {"id": "task_notify_ok",  "type": "scriptTask",       "name": "Send Approval Email","lane": "system"},
            {"id": "task_notify_rej", "type": "scriptTask",       "name": "Send Rejection Email","lane": "system"},
            {"id": "end_ok",          "type": "endEvent",         "name": "Leave Approved",     "lane": "employee"},
            {"id": "end_rejected",    "type": "endEvent",         "name": "Leave Rejected",     "lane": "employee"},
        ],
        "flows": [
            {"from": "start",           "to": "task_fill",       "name": "Begin"},
            {"from": "task_fill",       "to": "gw_decision",     "name": "Submitted"},
            {"from": "gw_decision",     "to": "task_notify_ok",  "name": "Yes", "condition": "approved == true"},
            {"from": "gw_decision",     "to": "task_notify_rej", "name": "No",  "default": True},
            {"from": "task_notify_ok",  "to": "end_ok",          "name": "Done"},
            {"from": "task_notify_rej", "to": "end_rejected",    "name": "Done"},
        ],
        "lanes": [
            {"id": "employee", "name": "Employee"},
            {"id": "manager",  "name": "Manager"},
            {"id": "system",   "name": "System (Automatic)"},
        ],
    }


# ── Test 5: BPMNPlane references collaboration id ─────────────────────────────

def test_swimlane_plane_references_collaboration():
    result = _run_pipeline(_swimlane_ir())
    assert result["ok"] is True, f"Pipeline failed: {result.get('problems')}"
    di = _parse_bpmndi(result["xml"])
    assert di["plane_bpmn_element"] == "Collaboration_1", (
        f"BPMNPlane bpmnElement should be 'Collaboration_1', got '{di['plane_bpmn_element']}'"
    )


# ── Test 6: Lane bands tile exactly ───────────────────────────────────────────

def test_swimlane_bands_tile_exactly():
    ir = _swimlane_ir()
    result = _run_pipeline(ir)
    assert result["ok"] is True, f"Pipeline failed: {result.get('problems')}"
    di = _parse_bpmndi(result["xml"])
    shapes = di["shapes"]

    participant = shapes.get("Participant_1")
    assert participant is not None, "Participant_1 DI shape missing"

    pool_inner_h = participant["h"]
    pool_top     = participant["y"]

    lane_ids      = [l["id"] for l in ir["lanes"]]
    total_band_h  = sum(shapes[lid]["h"] for lid in lane_ids if lid in shapes)

    assert abs(total_band_h - pool_inner_h) < 1, (
        f"Lane band heights ({total_band_h}) do not sum to pool inner height ({pool_inner_h})"
    )

    sorted_bands = sorted((shapes[lid] for lid in lane_ids if lid in shapes), key=lambda s: s["y"])
    expected_y = pool_top
    for band in sorted_bands:
        assert abs(band["y"] - expected_y) < 1, (
            f"Lane band gap: expected y={expected_y}, got y={band['y']}"
        )
        expected_y += band["h"]


# ── Test 7: Every node sits within its lane band ───────────────────────────────

def test_swimlane_nodes_inside_bands():
    ir = _swimlane_ir()
    result = _run_pipeline(ir)
    assert result["ok"] is True, f"Pipeline failed: {result.get('problems')}"
    di = _parse_bpmndi(result["xml"])
    shapes = di["shapes"]

    lane_bands = {l["id"]: shapes[l["id"]] for l in ir["lanes"] if l["id"] in shapes}

    for node in ir["nodes"]:
        nid  = node["id"]
        lid  = node.get("lane")
        pos  = shapes.get(nid)
        band = lane_bands.get(lid) if lid else None
        if pos is None or band is None:
            continue
        node_top    = pos["y"]
        node_bottom = pos["y"] + pos["h"]
        band_top    = band["y"]
        band_bottom = band["y"] + band["h"]
        assert node_top >= band_top - 1 and node_bottom <= band_bottom + 1, (
            f"Node '{nid}' (y={node_top}–{node_bottom}) is outside its lane band "
            f"'{lid}' (y={band_top}–{band_bottom})"
        )


# ── Test 8: No-lane output identical whether lanes absent or empty ─────────────

def test_no_lane_output_unaffected():
    base = {
        "name": "Simple",
        "nodes": [
            {"id": "start", "type": "startEvent", "name": "Start"},
            {"id": "task",  "type": "userTask",   "name": "Do Work"},
            {"id": "end",   "type": "endEvent",   "name": "Done"},
        ],
        "flows": [
            {"from": "start", "to": "task", "name": "Begin"},
            {"from": "task",  "to": "end",  "name": "Finish"},
        ],
    }
    r1 = _run_pipeline(base)
    r2 = _run_pipeline({**base, "lanes": []})

    assert r1["ok"] is True, f"No-lane IR failed: {r1.get('problems')}"
    assert r2["ok"] is True, f"Empty-lanes IR failed: {r2.get('problems')}"
    assert r1["xml"] == r2["xml"], (
        "Output must be identical when lanes is absent vs. empty list"
    )


# ── Test 9: Empty lane still emits lane element and DI shape ──────────────────

def test_empty_lane_still_emitted():
    ir = {
        "name": "One Empty Lane",
        "nodes": [
            {"id": "start", "type": "startEvent", "name": "Start",   "lane": "actor"},
            {"id": "task",  "type": "userTask",   "name": "Do Work", "lane": "actor"},
            {"id": "end",   "type": "endEvent",   "name": "Done",    "lane": "actor"},
        ],
        "flows": [
            {"from": "start", "to": "task", "name": "Begin"},
            {"from": "task",  "to": "end",  "name": "Finish"},
        ],
        "lanes": [
            {"id": "actor",  "name": "Actor"},
            {"id": "unused", "name": "Unused Lane"},
        ],
    }
    result = _run_pipeline(ir)
    assert result["ok"] is True, f"Pipeline failed: {result.get('problems')}"

    di = _parse_bpmndi(result["xml"])
    assert "unused" in di["shapes"], "Empty lane must have a DI shape"
    assert 'bpmnElement="unused"' in result["xml"], (
        "Empty lane must appear as bpmnElement reference in the XML"
    )


# ── Test 10: Pure join / pure fork gateway regression ─────────────────────────

def test_no_duplicate_incoming_outgoing_in_swimlane_xml():
    """bpmn-moddle auto-wires incoming/outgoing via sourceRef/targetRef inverse
    associations; manual pushes used to cause every flow to appear twice.
    This test catches that regression in the swimlane (no-auto-layout) path."""
    import xml.etree.ElementTree as ET
    BPMN = "http://www.omg.org/spec/BPMN/20100524/MODEL"

    result = _run_pipeline(_swimlane_ir())
    assert result["ok"] is True, f"Pipeline failed: {result.get('problems')}"

    root = ET.fromstring(result["xml"].strip())
    process = root.find(f"{{{BPMN}}}process")
    assert process is not None

    for el in process.iter():
        inc_ids = [c.text for c in el if c.tag == f"{{{BPMN}}}incoming"]
        out_ids = [c.text for c in el if c.tag == f"{{{BPMN}}}outgoing"]
        assert len(inc_ids) == len(set(inc_ids)), (
            f"Element '{el.get('id')}' has duplicate <bpmn:incoming>: {inc_ids}"
        )
        assert len(out_ids) == len(set(out_ids)), (
            f"Element '{el.get('id')}' has duplicate <bpmn:outgoing>: {out_ids}"
        )


def test_lane_orphan_node_rejected():
    """A non-inferred node without a 'lane' field must be rejected with kind='structure'."""
    ir = {
        "name": "Orphan Node",
        "nodes": [
            {"id": "start",  "type": "startEvent", "name": "Start",   "lane": "actor"},
            {"id": "task",   "type": "userTask",   "name": "Do Work"},   # ← no lane
            {"id": "end",    "type": "endEvent",   "name": "Done",    "lane": "actor"},
        ],
        "flows": [
            {"from": "start", "to": "task", "name": "Begin"},
            {"from": "task",  "to": "end",  "name": "Finish"},
        ],
        "lanes": [{"id": "actor", "name": "Actor"}],
    }
    result = _run_pipeline(ir)
    assert result["ok"] is False, "Orphan node (no lane field) must be rejected"
    struct = [p for p in result.get("problems", []) if p.get("rule") == "lane-orphan"]
    assert struct, f"Expected 'lane-orphan' problem, got: {result.get('problems')}"
    assert "task" in struct[0]["message"], "Problem should identify the orphan node id"


def test_lane_invalid_reference_rejected():
    """A node referencing a lane id that doesn't exist must be rejected."""
    ir = {
        "name": "Bad Lane Ref",
        "nodes": [
            {"id": "start", "type": "startEvent", "name": "Start", "lane": "actor"},
            {"id": "task",  "type": "userTask",   "name": "Work",  "lane": "nonexistent_lane"},
            {"id": "end",   "type": "endEvent",   "name": "Done",  "lane": "actor"},
        ],
        "flows": [
            {"from": "start", "to": "task", "name": "Begin"},
            {"from": "task",  "to": "end",  "name": "Finish"},
        ],
        "lanes": [{"id": "actor", "name": "Actor"}],
    }
    result = _run_pipeline(ir)
    assert result["ok"] is False, "Invalid lane reference must be rejected"
    struct = [p for p in result.get("problems", []) if p.get("rule") == "lane-orphan"]
    assert struct, f"Expected 'lane-orphan' problem, got: {result.get('problems')}"


def test_pure_join_and_pure_fork_gateways_pass():
    ir = {
        "name": "Parallel Work",
        "nodes": [
            {"id": "start",    "type": "startEvent",      "name": "Start"},
            {"id": "gw_split", "type": "parallelGateway", "name": "Split Work"},
            {"id": "task_a",   "type": "scriptTask",      "name": "Task A"},
            {"id": "task_b",   "type": "scriptTask",      "name": "Task B"},
            {"id": "gw_join",  "type": "parallelGateway", "name": "Merge Work"},
            {"id": "end",      "type": "endEvent",        "name": "Done"},
        ],
        "flows": [
            {"from": "start",    "to": "gw_split", "name": "Begin"},
            {"from": "gw_split", "to": "task_a",   "name": "A"},
            {"from": "gw_split", "to": "task_b",   "name": "B"},
            {"from": "task_a",   "to": "gw_join",  "name": "A Done"},
            {"from": "task_b",   "to": "gw_join",  "name": "B Done"},
            {"from": "gw_join",  "to": "end",      "name": "Finish"},
        ],
    }
    result = _run_pipeline(ir)
    assert result["ok"] is True, (
        f"Pure join + pure fork must pass without no-gateway-join-fork.\n"
        f"Problems: {result.get('problems')}"
    )
