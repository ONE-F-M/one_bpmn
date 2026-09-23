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
from frappe.utils import add_to_date, now_datetime

from one_bpmn.agents._eval_test_factories import (
    make_agent_configuration,
    make_eval_case,
    make_eval_run,
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


def chat_agent_on(model_name: str):
    """A Chat agent pointed at *model_name*, whatever that map starts on.

    A Chat agent may no longer be SAVED with a map that has no Chat Conversation
    start event — validation refuses it, which is right for authoring and wrong
    for these tests: the routing they check exists precisely because such an
    agent can be reached (an older record, or a map edited after the fact). So
    the agent is created against a chat-startable map and repointed underneath.
    """
    cfg = make_agent_configuration(process_model=make_process_model(CHAT_START_XML).name)
    frappe.db.set_value("AI Agent Configuration", cfg.name, "process_model", model_name,
                        update_modified=False)
    cfg.reload()
    return cfg


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
        cfg = chat_agent_on(make_process_model(RECORD_START_XML).name)
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
        cfg = chat_agent_on(agent_map.name)
        suite = make_eval_suite(agent_configuration=cfg.name, process_model=suite_map.name)
        case = make_eval_case(suite=suite.name, process_model=case_map.name)
        self.assertEqual(_eval_map_for_case(cfg, case), case_map.name)

    def test_falls_back_to_suite_then_agent(self):
        agent_map = make_process_model(RECORD_START_XML)
        suite_map = make_process_model(RECORD_START_XML)
        cfg = chat_agent_on(agent_map.name)

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

    def test_falls_back_to_the_source_runs_instance_context(self):
        """A case captured from a real run carries no input_context, but its
        source_run's instance already recorded the document — use that rather
        than making the author retype it."""
        todo = frappe.get_doc({
            "doctype": "ToDo", "description": "_Test subject",
            "allocated_to": frappe.session.user,
        }).insert(ignore_permissions=True)
        instance = frappe.get_doc({
            "doctype": "BPMN Process Instance",
            "status": "Completed",
            "context_doctype": "ToDo",
            "context_docname": todo.name,
        })
        instance.flags.ignore_mandatory = True
        instance.flags.ignore_links = True
        instance.insert(ignore_permissions=True)
        run = frappe.get_doc({
            "doctype": "AI Agent Run", "instance": instance.name,
            "bpmn_id": "ai_agent_task", "status": "Success",
        })
        run.flags.ignore_mandatory = True
        run.flags.ignore_links = True
        run.insert(ignore_permissions=True)

        case = make_eval_case(source_run=run.name, input_context=None)
        self.assertEqual(_eval_context_document(case), ("ToDo", todo.name))

    def test_explicit_context_wins_over_source_run(self):
        """Editing a captured case must re-point it, not be silently ignored."""
        case = frappe._dict(
            input_context=json.dumps(
                {"context_doctype": "ToDo", "context_docname": "chosen-by-hand"}
            ),
            source_run="some-run",
        )
        self.assertEqual(_eval_context_document(case), ("ToDo", "chosen-by-hand"))


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

    def test_a_script_rolling_the_transaction_back_is_named(self):
        """A tool script that calls frappe.db.rollback() takes the eval's instance
        with it. The error must say so, not blame the map's routing."""
        todo = self._todo()
        cfg, case, _ = self._agent_and_case(
            input_context=json.dumps(
                {"context_doctype": "ToDo", "context_docname": todo.name}
            )
        )
        with patch(INSTANCE_START, side_effect=lambda *a, **k: frappe.db.rollback()):
            with self.assertRaises(ValueError) as ctx:
                _run_map_eval(cfg, case)
        self.assertIn("rolled the transaction back", str(ctx.exception))

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

    def test_a_delegated_workers_answer_beats_its_last_message(self):
        """A worker's final model message is narration; its answer is the one it
        wrote back to the A2A Task that asked for the work. The first Connector
        Agent suite scored "now let me finalize" and failed a run that had in
        fact delivered a written, disabled connector."""
        task = frappe.get_doc({
            "doctype": "A2A Task",
            "direction": "Internal",
            "state": "submitted",
            "principal": frappe.session.user,
        }).insert(ignore_permissions=True)

        cfg, case, model = self._agent_and_case(
            input_context=json.dumps(
                {"context_doctype": "A2A Task", "context_docname": task.name}
            )
        )

        def fake_start(self, initial_data=None):
            frappe.db.set_value(
                "A2A Task", task.name,
                {"result": '{"connector": "frankfurter", "enabled": false}'},
                update_modified=False,
            )
            run = frappe.get_doc({
                "doctype": "AI Agent Run",
                "instance": self.name,
                "process_model": model.name,
                "agent_configuration": cfg.name,
                "bpmn_id": "ai_agent_task",
                "element_type": "task",
                "origin": "eval",
                "status": "Success",
                "final_output": "Perfect! The test passed. Now let me finalize.",
                "total_tokens": 10,
            })
            run.flags.ignore_mandatory = True
            run.flags.ignore_links = True
            run.insert(ignore_permissions=True)

        with patch(INSTANCE_START, new=fake_start):
            output, _usage = _run_map_eval(cfg, case)

        self.assertIn("frankfurter", output)
        self.assertNotIn("let me finalize", output)

    def test_a_context_document_that_is_not_a_task_keeps_the_run_output(self):
        todo = self._todo()
        cfg, case, model = self._agent_and_case(
            input_context=json.dumps(
                {"context_doctype": "ToDo", "context_docname": todo.name}
            )
        )

        def fake_start(self, initial_data=None):
            run = frappe.get_doc({
                "doctype": "AI Agent Run",
                "instance": self.name,
                "process_model": model.name,
                "agent_configuration": cfg.name,
                "bpmn_id": "ai_agent_task",
                "element_type": "task",
                "origin": "eval",
                "status": "Success",
                "final_output": "2 net days.",
                "total_tokens": 10,
            })
            run.flags.ignore_mandatory = True
            run.flags.ignore_links = True
            run.insert(ignore_permissions=True)

        with patch(INSTANCE_START, new=fake_start):
            output, _usage = _run_map_eval(cfg, case)

        self.assertEqual(output, "2 net days.")


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


def _insert_agent_run(cfg, tokens: int, cost: float, **tags):
    """Insert a finished chat AI Agent Run for *cfg* with the given usage and eval tags."""
    run = frappe.get_doc({
        "doctype": "AI Agent Run",
        "agent_configuration": cfg.name,
        "bpmn_id": "chat_reply",
        "status": "Success",
        "started_at": now_datetime(),
        "origin": "eval" if tags else "production",
        "total_prompt_tokens": tokens,
        "total_completion_tokens": 0,
        "total_tokens": tokens,
        "estimated_cost": cost,
        **tags,
    })
    run.flags.ignore_mandatory = True
    run.flags.ignore_links = True
    run.insert(ignore_permissions=True)
    return run


class TestChatEvalRunAttribution(FrappeTestCase):
    """A chat eval case counts only the AI Agent Runs tagged to it, not other runs of the agent."""

    def setUp(self):
        model = make_process_model(CHAT_START_XML)
        self.cfg = make_agent_configuration(process_model=model.name)
        suite = make_eval_suite(
            agent_configuration=self.cfg.name, eval_type="Agent", process_model=model.name
        )
        self.case = make_eval_case(suite=suite.name)
        self.eval_run = make_eval_run(suite.name)

    def _eval_tags(self):
        return {"eval_case": self.case.name, "eval_run": self.eval_run.name}

    def test_only_the_eval_tagged_run_is_counted(self):
        def fake_invoke_agent(agent_id, prompt, context=None, **kwargs):
            _insert_agent_run(self.cfg, 1000, 50.0)
            _insert_agent_run(self.cfg, 15, 0.02, **self._eval_tags())
            return {"response": "hi there"}

        with patch("one_bpmn.api.agent_invocation.invoke_agent", new=fake_invoke_agent):
            output, usage = _run_agent_eval(self.cfg, self.case, self.eval_run.name)

        self.assertEqual(output, "hi there")
        self.assertEqual(usage["tokens"], 15)
        self.assertEqual(usage["prompt_tokens"], 15)
        self.assertEqual(usage["cost"], 0.02)

    def test_no_eval_tagged_run_raises(self):
        def fake_invoke_agent(agent_id, prompt, context=None, **kwargs):
            _insert_agent_run(self.cfg, 1000, 50.0)
            return {"response": "hi there"}

        with patch("one_bpmn.api.agent_invocation.invoke_agent", new=fake_invoke_agent):
            with self.assertRaises(ValueError) as ctx:
                _run_agent_eval(self.cfg, self.case, self.eval_run.name)
        self.assertIn(self.case.name, str(ctx.exception))

    def test_second_attempt_counts_only_its_own_run(self):
        attempt_tokens = iter([100, 7])

        def fake_invoke_agent(agent_id, prompt, context=None, **kwargs):
            _insert_agent_run(self.cfg, next(attempt_tokens), 0.01, **self._eval_tags())
            return {"response": "hi there"}

        with patch("one_bpmn.api.agent_invocation.invoke_agent", new=fake_invoke_agent):
            _, first = _run_agent_eval(self.cfg, self.case, self.eval_run.name)
            first_run = frappe.get_all(
                "AI Agent Run", filters=self._eval_tags(), pluck="name"
            )[0]
            frappe.db.set_value(
                "AI Agent Run", first_run, "creation",
                add_to_date(now_datetime(), hours=-1), update_modified=False,
            )
            _, second = _run_agent_eval(self.cfg, self.case, self.eval_run.name)

        self.assertEqual(first["tokens"], 100)
        self.assertEqual(second["tokens"], 7)
