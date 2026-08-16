# Copyright (c) 2026, one-fm and contributors
# WI-002007: a connector modelled as an agent tool must say when it cannot
# return its data.
#
# The path works; it fails invisibly. dispatch_connector writes its output to
# task.data[resultVariable] and does nothing when that is empty, swallows
# handler errors unless failOnError is set, and no-ops when the role gate
# refuses. All three reached the model as an ordinary empty result — which
# execute_shape then reported as {"ok": true}, i.e. success.
#
# Nothing here changes how a connector runs. These tests pin what the agent is
# TOLD, which is read from the state the dispatcher already leaves behind.

from __future__ import annotations

import json
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.shape_tools import execute_shape
from one_bpmn.api.process_map_api import _connector_tools_without_result_variable

CONNECTOR_CFG = {"serviceType": "connector", "connectorId": "google_drive",
                 "operation": "createFile", "resultVariable": "connector_result"}


class _Instance:
	"""Stands in for the BPMN Process Instance router.

	``behaviour`` mimics what dispatch_connector leaves on task.data for the
	case under test — it does not re-implement the dispatcher.
	"""

	def __init__(self, behaviour=None):
		self.behaviour = behaviour or (lambda task: None)
		self.context_doctype = ""
		self.context_docname = ""

	def _dispatch_service_task(self, task):
		self.behaviour(task)


def _run(cfg, behaviour=None, kwargs=None):
	return json.loads(execute_shape(_Instance(behaviour), "Tool_Connector_1", cfg, kwargs or {}))


class TestAConnectorFailureIsNotReportedAsSuccess(FrappeTestCase):
	def test_a_swallowed_handler_error_is_reported_as_a_failure(self):
		"""failOnError off: output stays None and is written anyway."""
		res = _run(CONNECTOR_CFG, lambda task: task.data.update({"connector_result": None}))

		self.assertEqual(res["error"], "connector_failed")
		self.assertIn("google_drive/createFile", res["connector"])
		self.assertNotIn("ok", res, msg="a failed call must not look like a success")

	def test_a_call_that_never_ran_is_distinguished_from_one_that_failed(self):
		"""Unknown connector / bad params return before the key is written."""
		res = _run(CONNECTOR_CFG, lambda task: None)

		self.assertEqual(res["error"], "call_did_not_complete")

	def test_a_successful_call_returns_its_data(self):
		res = _run(CONNECTOR_CFG, lambda task: task.data.update({"connector_result": {"id": "abc"}}))

		self.assertEqual(res, {"connector_result": {"id": "abc"}})

	def test_the_arguments_the_model_supplied_are_not_echoed_back(self):
		res = _run(
			CONNECTOR_CFG,
			lambda task: task.data.update({"connector_result": {"id": "abc"}}),
			kwargs={"folder": "root"},
		)

		self.assertEqual(res, {"connector_result": {"id": "abc"}})


class TestTheConfigIsReadFromWhereTheDispatcherReadsIt(FrappeTestCase):
	def test_connector_config_comes_from_the_instance_extensions(self):
		"""The tool descriptor carries only bpmn_id/description/serviceType.

		connectorId and resultVariable live in _service_task_extensions — the
		same place the dispatcher reads them. Reading them off the descriptor
		instead makes every real call look like it had no Result Variable.
		"""
		descriptor = {"serviceType": "connector"}  # what compile_shape_tools passes
		instance = _Instance(lambda task: task.data.update({"memory_hits": {"chunks": []}}))
		instance._service_task_extensions = {
			"Tool_Connector_1": dict(CONNECTOR_CFG, resultVariable="memory_hits"),
		}

		res = json.loads(execute_shape(instance, "Tool_Connector_1", descriptor, {}))

		self.assertEqual(res, {"memory_hits": {"chunks": []}})
		self.assertNotIn("error", res)


class TestMissingResultVariableIsSaidOutLoud(FrappeTestCase):
	def test_without_a_result_variable_the_model_is_not_told_ok(self):
		"""This is the measured case: the agent used to receive {"ok": true}."""
		cfg = dict(CONNECTOR_CFG, resultVariable="")
		res = _run(cfg, lambda task: None)

		self.assertEqual(res["error"], "no_result_variable")
		self.assertNotEqual(res.get("ok"), True)
		self.assertIn("Result Variable", res["message"])


class TestNotPermittedIsNotTheSameAsNoData(FrappeTestCase):
	def test_a_refused_connector_says_so_and_is_never_dispatched(self):
		dispatched = []

		with patch("one_bpmn.one_bpmn.connectors.manifest.user_may_use_connector", return_value=False):
			res = _run(CONNECTOR_CFG, lambda task: dispatched.append(True))

		self.assertEqual(res["error"], "not_permitted")
		self.assertEqual(dispatched, [], msg="the gate must be answered before dispatch")
		self.assertIn("permission", res["message"].lower())

	def test_a_permitted_connector_is_dispatched_normally(self):
		with patch("one_bpmn.one_bpmn.connectors.manifest.user_may_use_connector", return_value=True):
			res = _run(CONNECTOR_CFG, lambda task: task.data.update({"connector_result": {"id": "x"}}))

		self.assertEqual(res, {"connector_result": {"id": "x"}})


class TestDeployReadinessFlagsTheGap(FrappeTestCase):
	BPMN = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
                  id="Definitions_1" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_1" isExecutable="true">
    <bpmn:serviceTask id="agent_1" name="Run Agent"
        spiffworkflow:serviceType="ai_agent" spiffworkflow:aiToolsAdhoc="tools_1" />
    <bpmn:adHocSubProcess id="tools_1" name="Tools">
      <bpmn:serviceTask id="tool_no_var" name="Create File"
          spiffworkflow:serviceType="connector"
          spiffworkflow:connectorId="google_drive" spiffworkflow:operation="createFile" />
      <bpmn:serviceTask id="tool_with_var" name="Read File"
          spiffworkflow:serviceType="connector"
          spiffworkflow:connectorId="google_drive" spiffworkflow:operation="readFile"
          spiffworkflow:resultVariable="file_data" />
    </bpmn:adHocSubProcess>
    <bpmn:serviceTask id="plain_connector" name="Ordinary Step"
        spiffworkflow:serviceType="connector" spiffworkflow:connectorId="google_drive" />
  </bpmn:process>
</bpmn:definitions>"""

	def test_only_the_tool_without_a_result_variable_is_flagged(self):
		found = _connector_tools_without_result_variable(self.BPMN)

		self.assertEqual([f["bpmn_id"] for f in found], ["tool_no_var"])

	def test_the_finding_names_the_shape_the_agent_and_the_connector(self):
		f = _connector_tools_without_result_variable(self.BPMN)[0]

		self.assertEqual(f["shape"], "Create File")
		self.assertEqual(f["agent"], "Run Agent")
		self.assertEqual(f["connector"], "google_drive/createFile")

	def test_a_connector_outside_a_tools_subprocess_is_not_flagged(self):
		"""An ordinary process step's output is genuinely optional."""
		found = _connector_tools_without_result_variable(self.BPMN)

		self.assertNotIn("plain_connector", [f["bpmn_id"] for f in found])

	def test_unparseable_xml_reports_nothing_rather_than_raising(self):
		self.assertEqual(_connector_tools_without_result_variable("<not-xml"), [])
