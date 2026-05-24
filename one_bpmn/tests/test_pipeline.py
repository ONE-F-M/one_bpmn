"""
Tests for the IR → BPMN pipeline (pipeline.mjs).

Covers:
  1. Known-good IR compiles to a lint-clean XML document
  2. Task with fan-out (>1 outgoing) compiles clean — normalizeGateways auto-inserts split
  3. Parallel split paired with exclusive join rejected by assertGatewayPairing
  4. IR with deliberate fake-join (>1 incoming to a task) compiles clean — normalizeGateways auto-inserts join

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


def _run_pipeline(ir_dict: dict) -> dict:
    node = shutil.which("node")
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
