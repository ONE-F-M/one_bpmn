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

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.shape_tools import execute_shape
from one_bpmn.api.process_map_api import _connector_tools_without_result_variable
from one_bpmn.one_bpmn.doctype.bpmn_process_instance.dispatchers import CONNECTOR_OUTCOME_KEY

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

	def _dispatch_service_task(self, task, task_cfg_override=None):
		self.behaviour(task)


def _run(cfg, behaviour=None, kwargs=None):
	return json.loads(execute_shape(_Instance(behaviour), "Tool_Connector_1", cfg, kwargs or {}))


def _left(status, **detail):
	"""What dispatch_connector records on the task for the case under test."""
	def behaviour(task):
		task.data[CONNECTOR_OUTCOME_KEY] = {"connector": "google_drive/createFile", "status": status, **detail}
		if status == "failed" and CONNECTOR_CFG["resultVariable"]:
			task.data[CONNECTOR_CFG["resultVariable"]] = None
	return behaviour


class TestAConnectorFailureIsNotReportedAsSuccess(FrappeTestCase):
	def test_a_swallowed_handler_error_is_reported_as_a_failure(self):
		"""failOnError off: the dispatcher logs, records the failure and carries on."""
		res = _run(CONNECTOR_CFG, _left("failed", error="upstream 500"))

		self.assertEqual(res["error"], "connector_failed")
		self.assertIn("google_drive/createFile", res["connector"])
		self.assertIn("upstream 500", res["message"])
		self.assertNotIn("ok", res, msg="a failed call must not look like a success")

	def test_a_call_that_never_ran_is_distinguished_from_one_that_failed(self):
		"""Unknown connector / bad params return before the handler is called."""
		res = _run(CONNECTOR_CFG, _left("not_run", reason="unknown or disabled connector operation"))

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
	def test_data_that_was_returned_and_discarded_is_named(self):
		"""The measured case: the connector returned data, the shape had nowhere
		to put it, and the agent used to receive a bare {"ok": true}."""
		cfg = dict(CONNECTOR_CFG, resultVariable="")
		res = _run(cfg, _left("ok", returned=True, stored=False))

		self.assertTrue(res["ok"])
		self.assertEqual(res["warning"], "no_result_variable")
		self.assertIn("discarded", res["message"])
		self.assertIn("Result Variable", res["message"])

	def test_a_fire_and_forget_shape_is_still_plainly_ok(self):
		"""A connector that returns nothing has nothing to lose — the sandbox
		tools run this way on every Dev, Frontend and Mobile agent map."""
		cfg = dict(CONNECTOR_CFG, resultVariable="")
		res = _run(cfg, _left("ok", returned=False, stored=False))

		self.assertEqual(res, {"ok": True})

	def test_the_outcome_record_never_reaches_the_model(self):
		res = _run(CONNECTOR_CFG, lambda task: task.data.update({
			CONNECTOR_OUTCOME_KEY: {"status": "ok", "returned": True, "stored": True},
			"connector_result": {"id": "abc"},
		}))

		self.assertEqual(res, {"connector_result": {"id": "abc"}})


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


class TestAParkedConnectorStillSuspends(FrappeTestCase):
	def test_the_waiting_marker_wins_over_the_outcome_report(self):
		"""A delegation connector answers later, from elsewhere. Reporting its
		empty result as "did not complete" would end the turn the model was
		supposed to wait out — the loop must still see the pause."""
		from one_bpmn.agents.shape_tools import ToolDeferred
		from one_bpmn.one_bpmn.connectors.a2a_client_ops import A2A_WAITING_KEY

		with self.assertRaises(ToolDeferred):
			_run(CONNECTOR_CFG, lambda task: task.data.update({A2A_WAITING_KEY: {"task": "A2A-1"}}))


class TestTheEndpointStaysReachable(FrappeTestCase):
	"""Inserting a helper between @frappe.whitelist() and its function moves the
	decorator onto the helper. Everything still passes in-process — whitelisting
	only matters over HTTP — while the Deploy button dies with "not whitelisted".
	"""

	def test_validate_bpmn_readiness_is_whitelisted(self):
		from one_bpmn.api.process_map_api import validate_bpmn_readiness

		self.assertIn(validate_bpmn_readiness, frappe.whitelisted)

	def test_the_private_helper_is_not_exposed_over_http(self):
		from one_bpmn.api.process_map_api import _connector_tools_without_result_variable

		self.assertNotIn(_connector_tools_without_result_variable, frappe.whitelisted)


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


class TestConnectorsThatAnswerOutOfBandAreNotFlagged(FrappeTestCase):
	def test_a_sandbox_tool_without_a_result_variable_is_by_design(self):
		"""Every Dev, Frontend and Mobile agent map has run_tests and
		open_pull_request with no Result Variable: they park and answer through
		the callback. Flagging them would put a warning on every deploy of every
		sandbox agent, and a warning that is always there is one nobody reads."""
		from one_bpmn.api.compilation import _check_connector_tools_can_answer

		xml = TestCompileSaysSoToo.XML.replace(
			'spiffworkflow:connectorId="google_drive" spiffworkflow:operation="getFile"',
			'spiffworkflow:connectorId="agent_sandbox" spiffworkflow:operation="run_tests"',
		) % ""

		self.assertEqual(_connector_tools_without_result_variable(xml), [])
		self.assertEqual(_check_connector_tools_can_answer(xml), [])


class TestCompileSaysSoToo(FrappeTestCase):
	"""The deploy checklist names the gap; a compile that skips the checklist —
	an import, a call from the API — has to as well, because an import is
	exactly where a shape arrives with the field dropped."""

	XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" id="D">
  <bpmn:process id="P" isExecutable="true">
    <bpmn:serviceTask id="Agent_1" name="Helper" spiffworkflow:serviceType="ai_agent"
        spiffworkflow:aiToolsAdhoc="Tools_1" />
    <bpmn:adHocSubProcess id="Tools_1">
      <bpmn:serviceTask id="Tool_Mute" name="Look up the file" spiffworkflow:serviceType="connector"
          spiffworkflow:connectorId="google_drive" spiffworkflow:operation="getFile" %s />
    </bpmn:adHocSubProcess>
  </bpmn:process>
</bpmn:definitions>"""

	def test_a_tool_without_a_result_variable_is_a_compile_warning(self):
		from one_bpmn.api.compilation import _check_connector_tools_can_answer

		warnings = _check_connector_tools_can_answer(self.XML % "")

		self.assertEqual(len(warnings), 1)
		self.assertEqual(warnings[0]["type"], "warning")
		for expected in ("Look up the file", "google_drive/getFile", "Helper", "Result Variable"):
			self.assertIn(expected, warnings[0]["detail"])

	def test_a_tool_with_one_is_not(self):
		from one_bpmn.api.compilation import _check_connector_tools_can_answer

		self.assertEqual(
			_check_connector_tools_can_answer(self.XML % 'spiffworkflow:resultVariable="file"'), []
		)


class TestThroughTheRealDispatcher(FrappeTestCase):
	"""The fakes above pin what is reported for each state the dispatcher leaves.
	These run the real ``dispatch_connector`` with only the handler stubbed, so
	the states are the ones it actually leaves — the merge onto today's dispatch
	branch is what this guards."""

	def setUp(self):
		super().setUp()
		patcher = patch.object(frappe, "log_error")
		patcher.start()
		self.addCleanup(patcher.stop)

		inst = frappe.new_doc("BPMN Process Instance")
		inst.name = "INST-CONNECTOR-TOOL"
		inst.context_doctype = ""
		inst.context_docname = ""
		inst._service_task_extensions = {"Tool_Connector_1": dict(CONNECTOR_CFG)}
		inst._script_task_extensions = {}
		self.instance = inst

	def _run(self, handler, cfg=None):
		with patch(
			"one_bpmn.one_bpmn.doctype.bpmn_process_instance.dispatchers._resolve_connector_handler",
			return_value=handler,
		), patch("one_bpmn.one_bpmn.connectors.manifest.user_may_use_connector", return_value=True):
			return json.loads(execute_shape(self.instance, "Tool_Connector_1", cfg or dict(CONNECTOR_CFG), {"q": 1}))

	def test_a_handler_that_raises_with_fail_on_error_off_is_reported_as_failed(self):
		def boom(params, ctx):
			raise RuntimeError("upstream 500")

		res = self._run(boom)

		self.assertEqual(res["error"], "connector_failed")
		self.assertNotIn("ok", res)

	def test_a_handler_that_answers_hands_its_data_back(self):
		res = self._run(lambda params, ctx: {"id": "file-1"})

		self.assertEqual(res, {"connector_result": {"id": "file-1"}})

	def test_no_result_variable_means_the_data_is_reported_discarded(self):
		res = self._run(lambda params, ctx: {"id": "file-1"}, cfg=dict(CONNECTOR_CFG, resultVariable=""))

		self.assertTrue(res["ok"])
		self.assertEqual(res["warning"], "no_result_variable")

	def test_a_handler_that_returns_nothing_without_a_result_variable_is_plainly_ok(self):
		res = self._run(lambda params, ctx: None, cfg=dict(CONNECTOR_CFG, resultVariable=""))

		self.assertEqual(res, {"ok": True})

	def test_an_unknown_operation_is_reported_as_not_run(self):
		res = self._run(None)

		self.assertEqual(res["error"], "call_did_not_complete")
		self.assertIn("unknown or disabled", res["message"])

	def test_a_refusal_at_the_dispatcher_is_still_reported_as_permission(self):
		"""If the gate ever moves or the pre-check is skipped, the dispatcher's
		own record still names it a permission decision, not missing data."""
		with patch(
			"one_bpmn.one_bpmn.doctype.bpmn_process_instance.dispatchers._resolve_connector_handler",
			return_value=lambda params, ctx: {"id": "x"},
		), patch("one_bpmn.agents.shape_tools._connector_not_permitted", return_value=None), patch(
			"one_bpmn.one_bpmn.connectors.manifest.user_may_use_connector", return_value=False
		):
			res = json.loads(execute_shape(self.instance, "Tool_Connector_1", dict(CONNECTOR_CFG), {}))

		self.assertEqual(res["error"], "not_permitted")


class TestTheToolCallRowAgreesWithItsBody(FrappeTestCase):
	"""The inspector colours a row by its status. A row that says Success above
	a body that says connector_failed is the same lie one level up."""

	def test_a_failed_connector_is_an_error_row(self):
		from one_bpmn.agents.observability import _tool_call_status

		self.assertEqual(_tool_call_status(json.dumps({"error": "connector_failed", "connector": "x/y"})), "Error")
		self.assertEqual(_tool_call_status(json.dumps({"error": "call_did_not_complete"})), "Error")

	def test_a_refused_connector_is_a_denied_row_like_a_policy_refusal(self):
		from one_bpmn.agents.observability import _tool_call_status

		self.assertEqual(_tool_call_status(json.dumps({"error": "not_permitted"})), "Denied")

	def test_data_and_plain_ok_stay_success(self):
		from one_bpmn.agents.observability import _tool_call_status

		self.assertEqual(_tool_call_status(json.dumps({"connector_result": {"id": 1}})), "Success")
		self.assertEqual(_tool_call_status(json.dumps({"ok": True, "warning": "no_result_variable"})), "Success")
		self.assertEqual(_tool_call_status("plain text answer"), "Success")
		self.assertEqual(_tool_call_status("{not json"), "Success")
