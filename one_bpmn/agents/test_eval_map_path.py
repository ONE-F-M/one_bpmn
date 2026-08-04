# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Tests for the map path of an Agent eval — the branch that lets a NON-chat agent
(Background, or any agent whose map is record-triggered) be evaluated with its
tools.

Before this path existed both eval types were dead ends for such an agent:
"Agent" went through invoke_agent, which needs a Chat Conversation and an
already-running instance, and "Direct" never attaches tools at all. So the tool
shapes of an AI Agent Task's ad-hoc sub-process could not be exercised from an
eval at all.

No real LLM call is made: the engine pass is mocked and the AI Agent Run it would
have produced is written by the mock.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents._eval_test_factories import (
    make_agent_configuration,
    make_eval_case,
    make_eval_suite,
)
from one_bpmn.agents.eval_runner import (
    _assert_agent_evaluatable,
    _eval_context_document,
    _eval_map_for_case,
    _map_is_chat_startable,
    _needs_map_eval,
    _run_agent_eval,
    _run_map_eval,
)

INSTANCE_START = (
    "one_bpmn.one_bpmn.doctype.bpmn_process_instance"
    ".bpmn_process_instance.BPMNProcessInstance.start"
)

CHAT_START_XML = (
    '<bpmn:definitions><bpmn:process id="p"><bpmn:startEvent id="s">'
    '<bpmn:conditionalEventDefinition spiffworkflow:triggerDoctype="Chat Conversation" '
    'spiffworkflow:triggerType="After Insert" />'
    "</bpmn:startEvent></bpmn:process></bpmn:definitions>"
)
RECORD_START_XML = (
    '<bpmn:definitions><bpmn:process id="p"><bpmn:startEvent id="s">'
    '<bpmn:conditionalEventDefinition spiffworkflow:triggerDoctype="Leave Application" '
    'spiffworkflow:triggerType="After Insert" />'
    "</bpmn:startEvent></bpmn:process></bpmn:definitions>"
)


def make_process_model(xml: str, **kwargs):
    """A BPMN Process Model carrying *xml*, enough for the routing checks."""
    suffix = frappe.generate_hash(length=8)
    defaults = {
        "doctype": "BPMN Process Model",
        "title": f"_Test Map {suffix}",
        "process_id": f"_test_map_{suffix}",
        "version": 1,
        "bpmn_xml": xml,
    }
    defaults.update(kwargs)
    doc = frappe.get_doc(defaults)
    doc.flags.ignore_mandatory = True
    doc.flags.ignore_links = True
    doc.flags.ignore_validate = True
    return doc.insert(ignore_permissions=True)


class TestMapStartability(FrappeTestCase):
    def test_chat_conversation_trigger_is_chat_startable(self):
        model = make_process_model(CHAT_START_XML)
        self.assertTrue(_map_is_chat_startable(model.name))

    def test_record_trigger_is_not_chat_startable(self):
        model = make_process_model(RECORD_START_XML)
        self.assertFalse(_map_is_chat_startable(model.name))

    def test_no_map_is_not_chat_startable(self):
        self.assertFalse(_map_is_chat_startable(""))
        self.assertFalse(_map_is_chat_startable(None))


class TestNeedsMapEval(FrappeTestCase):
    def test_background_agent_needs_map_path(self):
        cfg = make_agent_configuration(agent_type="Background", chat_mode_label=None)
        self.assertTrue(_needs_map_eval(cfg))

    def test_chat_agent_with_chat_map_uses_chat_path(self):
        model = make_process_model(CHAT_START_XML)
        cfg = make_agent_configuration(process_model=model.name)
        self.assertFalse(_needs_map_eval(cfg))

    def test_chat_agent_with_record_triggered_map_needs_map_path(self):
        """The case that used to throw "not running for this conversation"."""
        model = make_process_model(RECORD_START_XML)
        cfg = make_agent_configuration(process_model=model.name)
        self.assertTrue(_needs_map_eval(cfg))

    def test_mapless_chat_agent_keeps_legacy_chat_path(self):
        """Unchanged behaviour: a mapless Chat agent still goes through
        invoke_agent, so existing suites are not re-routed."""
        cfg = make_agent_configuration()
        self.assertFalse(_needs_map_eval(cfg))


class TestMapResolution(FrappeTestCase):
    def test_case_map_wins_over_suite_and_agent(self):
        agent_map = make_process_model(RECORD_START_XML)
        suite_map = make_process_model(RECORD_START_XML)
        case_map = make_process_model(RECORD_START_XML)
        cfg = make_agent_configuration(process_model=agent_map.name)
        suite = make_eval_suite(agent_configuration=cfg.name, process_model=suite_map.name)
        case = make_eval_case(suite=suite.name, process_model=case_map.name)
        self.assertEqual(_eval_map_for_case(cfg, case), case_map.name)

    def test_falls_back_to_suite_then_agent(self):
        agent_map = make_process_model(RECORD_START_XML)
        suite_map = make_process_model(RECORD_START_XML)
        cfg = make_agent_configuration(process_model=agent_map.name)

        suite = make_eval_suite(agent_configuration=cfg.name, process_model=suite_map.name)
        case = make_eval_case(suite=suite.name, process_model=None)
        self.assertEqual(_eval_map_for_case(cfg, case), suite_map.name)

        bare = make_eval_suite(agent_configuration=cfg.name, process_model=None)
        bare_case = make_eval_case(suite=bare.name, process_model=None)
        self.assertEqual(_eval_map_for_case(cfg, bare_case), agent_map.name)

    def test_no_map_anywhere_returns_empty(self):
        cfg = make_agent_configuration()
        suite = make_eval_suite(agent_configuration=cfg.name, process_model=None)
        case = make_eval_case(suite=suite.name, process_model=None)
        self.assertEqual(_eval_map_for_case(cfg, case), "")


class TestContextDocument(FrappeTestCase):
    def test_reads_explicit_context_keys(self):
        case = make_eval_case(
            input_context=json.dumps(
                {"context_doctype": "ToDo", "context_docname": "abc123"}
            )
        )
        self.assertEqual(_eval_context_document(case), ("ToDo", "abc123"))

    def test_missing_or_malformed_context_is_empty(self):
        """A stand-in is used rather than a saved case: input_context is a JSON
        column with a CHECK constraint, so malformed JSON cannot be inserted —
        but it can still reach the helper from an older row or an API caller."""
        for value in (None, "", "not json", json.dumps({"leave_application": "X"}),
                      json.dumps(["a", "b"])):
            case = frappe._dict(input_context=value)
            self.assertEqual(
                _eval_context_document(case), ("", ""),
                msg=f"input_context={value!r} should yield no context document",
            )


class TestRunMapEval(FrappeTestCase):
    def _agent_and_case(self, **case_kwargs):
        model = make_process_model(RECORD_START_XML)
        cfg = make_agent_configuration(agent_type="Background", chat_mode_label=None)
        suite = make_eval_suite(agent_configuration=cfg.name, process_model=None)
        case = make_eval_case(suite=suite.name, process_model=model.name, **case_kwargs)
        return cfg, case, model

    def test_no_map_named_raises(self):
        cfg = make_agent_configuration(agent_type="Background", chat_mode_label=None)
        suite = make_eval_suite(agent_configuration=cfg.name, process_model=None)
        case = make_eval_case(suite=suite.name, process_model=None)
        with self.assertRaises(ValueError) as ctx:
            _run_map_eval(cfg, case)
        self.assertIn("which process map to run", str(ctx.exception))

    def test_missing_context_document_raises(self):
        cfg, case, _ = self._agent_and_case(input_context=None)
        with self.assertRaises(ValueError) as ctx:
            _run_map_eval(cfg, case)
        self.assertIn("context_doctype", str(ctx.exception))

    def test_nonexistent_context_document_raises(self):
        cfg, case, _ = self._agent_and_case(
            input_context=json.dumps(
                {"context_doctype": "ToDo", "context_docname": "no-such-todo"}
            )
        )
        with self.assertRaises(ValueError) as ctx:
            _run_map_eval(cfg, case)
        self.assertIn("No ToDo named", str(ctx.exception))

    def _todo(self):
        """Any real document will do as the eval's subject; ToDo is the cheapest."""
        todo = frappe.get_doc({
            "doctype": "ToDo",
            "description": "_Test eval subject",
            "allocated_to": frappe.session.user,
        })
        return todo.insert(ignore_permissions=True)

    def test_engine_pass_producing_no_agent_run_raises(self):
        """A conditional start event that does not match leaves the process with
        nothing to do — that must be a clear Error, not a silent empty output."""
        todo = self._todo()
        cfg, case, _ = self._agent_and_case(
            input_context=json.dumps(
                {"context_doctype": "ToDo", "context_docname": todo.name}
            )
        )
        with patch(INSTANCE_START, return_value=None):
            with self.assertRaises(ValueError) as ctx:
                _run_map_eval(cfg, case)
        self.assertIn("produced no AI Agent Run", str(ctx.exception))

    def test_returns_run_output_and_usage_and_cancels_instance(self):
        todo = self._todo()
        cfg, case, model = self._agent_and_case(
            input_context=json.dumps(
                {"context_doctype": "ToDo", "context_docname": todo.name}
            )
        )
        case.db_set("bpmn_id", "ai_agent_task", update_modified=False)
        case.reload()

        created = {}

        def fake_start(self, initial_data=None):
            created["instance"] = self.name
            run = frappe.get_doc({
                "doctype": "AI Agent Run",
                "instance": self.name,
                "process_model": model.name,
                "agent_configuration": cfg.name,
                "bpmn_id": "ai_agent_task",
                "element_type": "task",
                "origin": "eval",
                "status": "Success",
                "final_output": "3 calendar days, 2 holidays, 1 net.",
                "total_prompt_tokens": 100,
                "total_completion_tokens": 20,
                "total_tokens": 120,
                "estimated_cost": 0.5,
            })
            run.flags.ignore_mandatory = True
            run.flags.ignore_links = True
            run.insert(ignore_permissions=True)

        with patch(INSTANCE_START, new=fake_start):
            output, usage = _run_map_eval(cfg, case)

        self.assertEqual(output, "3 calendar days, 2 holidays, 1 net.")
        self.assertEqual(usage["prompt_tokens"], 100)
        self.assertEqual(usage["completion_tokens"], 20)
        self.assertEqual(usage["tokens"], 120)
        self.assertEqual(usage["cost"], 0.5)
        # The eval must not leave a live instance parked on a human task.
        self.assertEqual(
            frappe.db.get_value("BPMN Process Instance", created["instance"], "status"),
            "Cancelled",
        )


class TestAgentEvalRouting(FrappeTestCase):
    def test_background_agent_routes_to_map_path(self):
        cfg = make_agent_configuration(agent_type="Background", chat_mode_label=None)
        suite = make_eval_suite(agent_configuration=cfg.name, process_model=None)
        case = make_eval_case(suite=suite.name)
        with patch(
            "one_bpmn.agents.eval_runner._run_map_eval", return_value=("out", {})
        ) as map_path:
            with patch("one_bpmn.agents.eval_runner._run_chat_agent_eval") as chat_path:
                _run_agent_eval(cfg, case)
        map_path.assert_called_once()
        chat_path.assert_not_called()

    def test_chat_agent_routes_to_chat_path(self):
        model = make_process_model(CHAT_START_XML)
        cfg = make_agent_configuration(process_model=model.name)
        suite = make_eval_suite(agent_configuration=cfg.name, process_model=model.name)
        case = make_eval_case(suite=suite.name)
        with patch(
            "one_bpmn.agents.eval_runner._run_chat_agent_eval", return_value=("out", {})
        ) as chat_path:
            with patch("one_bpmn.agents.eval_runner._run_map_eval") as map_path:
                _run_agent_eval(cfg, case)
        chat_path.assert_called_once()
        map_path.assert_not_called()

    def test_eval_flags_are_restored(self):
        """Parking must be re-enabled afterwards or later saves in the same
        request would run their AI work inline."""
        cfg = make_agent_configuration(agent_type="Background", chat_mode_label=None)
        suite = make_eval_suite(agent_configuration=cfg.name, process_model=None)
        case = make_eval_case(suite=suite.name)
        with patch("one_bpmn.agents.eval_runner._run_map_eval", return_value=("o", {})):
            _run_agent_eval(cfg, case)
        self.assertFalse(getattr(frappe.flags, "bpmn_disable_ai_parking", False))
        self.assertIsNone(getattr(frappe.flags, "eval_origin", None))


class TestEvaluatableGate(FrappeTestCase):
    def test_suite_named_map_bypasses_adk_guard(self):
        """A mapless Google ADK agent is evaluatable once the suite names the map
        to run — the map path does not need the agent to own one."""
        cfg = make_agent_configuration(
            agent_framework="Google ADK", agent_type="Background", chat_mode_label=None
        )
        model = make_process_model(RECORD_START_XML)
        # Without a named map the guard still fires.
        self.assertRaises(
            frappe.ValidationError, _assert_agent_evaluatable, cfg.name, "Agent"
        )
        # With one it does not.
        _assert_agent_evaluatable(cfg.name, "Agent", model.name)

    def test_direct_eval_type_is_never_gated(self):
        cfg = make_agent_configuration(agent_framework="Google ADK")
        _assert_agent_evaluatable(cfg.name, "Direct")
