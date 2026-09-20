# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""An agent that cannot work is caught at compile, not in production.

Two ways a map can be wired to fail silently: its instructions name a tool that
does not exist, and its closing script reads a turn-store key nothing writes.
Both end the same way — an empty answer and nothing in the logs — so the tests
here are about the false positives as much as the catches. A check that cries
wolf on every agent gets ignored.
"""
import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.compilation import (
	_tool_contract_gaps,
	_validate_ai_tool_contract,
	_turn_keys_read,
	_turn_keys_written,
	_validate_turn_store_contract,
)

BPMN = "http://www.omg.org/spec/BPMN/20100524/MODEL"
SPIFF = "http://spiffworkflow.org/bpmn/schema/1.0/core"


class TestToolContractGaps(FrappeTestCase):
	def test_a_tool_the_instructions_call_but_the_box_lacks(self):
		gaps = _tool_contract_gaps("Then call propose_pull_request once.", {"register_hook"}, set())
		self.assertEqual(gaps, ["propose_pull_request"])

	def test_use_and_invoke_count_as_calling(self):
		self.assertEqual(_tool_contract_gaps("use draft_change first", set(), set()), ["draft_change"])
		self.assertEqual(_tool_contract_gaps("invoke review_change", set(), set()), ["review_change"])

	def test_a_tool_that_exists_is_not_reported(self):
		self.assertEqual(_tool_contract_gaps("call register_hook", {"register_hook"}, set()), [])

	def test_a_backticked_name_counts_when_it_is_a_real_tool_elsewhere(self):
		gaps = _tool_contract_gaps("Finish with `propose_pull_request`.", set(), {"propose_pull_request"})
		self.assertEqual(gaps, ["propose_pull_request"])

	def test_a_backticked_argument_name_is_not_a_tool(self):
		"""Prompts quote argument and field names constantly.

		Treating every backticked snake_case word as a tool reported
		'process_name', 'technical_plan' and 'user_stories' on the BA Agent, none
		of which is a tool. A name with no verb in front of it only counts when
		some map really has a tool of that name.
		"""
		prompt = "Pass `plan_approved: false` and put the answer in `response`."
		self.assertEqual(_tool_contract_gaps(prompt, set(), set()), [])


class TestThePromptThatRunsIsRead(FrappeTestCase):
	"""Whichever prompt reaches the model is the one checked.

	A shape with no configuration runs its own copy. A linked shape runs the
	configuration's and keeps a copy nothing reads — blocking on that copy meant
	refusing a deploy over text the editor does not show anywhere.
	"""

	def _exts(self, shape_prompt="", user_prompt="", config=""):
		import json

		return {"demo_agent": {
			"serviceType": "ai_agent",
			"aiToolsAdhoc": "demo_tools",
			"aiAgentConfig": config,
			"aiToolShapes": json.dumps([{"bpmn_id": "do_work"}]),
			"aiSystemPrompt": shape_prompt,
			"aiUserPrompt": user_prompt,
		}}

	def test_a_tool_named_only_on_the_shape_is_caught(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			_validate_ai_tool_contract(self._exts(shape_prompt="Then call propose_pull_request once."))
		self.assertIn("propose_pull_request", str(caught.exception))
		self.assertIn("demo_tools", str(caught.exception))

	def test_a_tool_named_only_in_the_turn_instructions_is_caught(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			_validate_ai_tool_contract(self._exts(user_prompt="Finish by calling propose_pull_request."))
		self.assertIn("propose_pull_request", str(caught.exception))

	def test_a_shape_naming_only_real_tools_is_quiet(self):
		_validate_ai_tool_contract(self._exts(shape_prompt="Call do_work once."))

	def test_a_linked_configuration_replaces_the_shape_copy(self):
		from unittest.mock import patch

		from one_bpmn.api import compilation as comp

		exts = self._exts(shape_prompt="Then call propose_pull_request once.", config="Demo Agent")
		with patch.object(comp, "_known_tool_ids", return_value={"do_work", "propose_pull_request"}), patch.object(
			frappe.db, "exists", return_value=True
		), patch.object(frappe.db, "get_value", return_value="Call do_work once."):
			_validate_ai_tool_contract(exts)

class TestTurnStoreKeys(FrappeTestCase):
	def test_keys_written_inline_and_by_name(self):
		top, out = _turn_keys_written('update_turn(d, work_order="x", output={"summary": 1})')
		self.assertEqual((top, out), ({"work_order"}, {"summary"}))

	def test_a_payload_built_as_a_named_dict_still_counts(self):
		"""ProsAlly's finalize builds `output` then passes it by name.

		Reading only inline literals reported every one of its keys as unwritten.
		"""
		script = 'output = {"intent": "CLARIFY", "response": "hi"}\nupdate_turn(d, output=output, done=True)'
		_, out = _turn_keys_written(script)
		self.assertEqual(out, {"intent", "response"})

	def test_set_turn_seeds_keys_positionally(self):
		top, _ = _turn_keys_written('set_turn(c, {"session_state": s, "user_text": t})')
		self.assertEqual(top, {"session_state", "user_text"})

	def test_reads_are_split_by_level(self):
		script = '_turn = get_turn(c)\n_out = _turn.get("output")\nx = _out.get("summary")\ny = turn.get("work_order")'
		top, out = _turn_keys_read(script)
		self.assertEqual((top, out), ({"work_order"}, {"summary"}))

	def test_the_output_envelope_is_not_a_key(self):
		"""Every closing script opens `output` to reach the payload.

		Counting it as a key made the check fire on every agent that works.
		"""
		top, _ = _turn_keys_read('_out = turn.get("output")')
		self.assertEqual(top, set())

	def test_a_script_that_will_not_parse_still_yields_its_reads(self):
		top, _ = _turn_keys_read('this is ( not python\nx = turn.get("summary")')
		self.assertEqual(top, {"summary"})


class TestTurnStoreContract(FrappeTestCase):
	"""End to end over a map: the closing script, the tools and the warning."""

	def setUp(self):
		self.made = []

	def tearDown(self):
		for name in self.made:
			if frappe.db.exists("Server Script", name):
				frappe.delete_doc("Server Script", name, force=True, ignore_permissions=True)

	def _script(self, name, body):
		doc = frappe.get_doc({
			"doctype": "Server Script", "name": name, "script_type": "API",
			"api_method": frappe.scrub(name), "script": body,
		})
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		self.made.append(doc.name)
		return doc.name

	def _map(self, tool_script, closing_script):
		return f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="{BPMN}" xmlns:spiffworkflow="{SPIFF}" id="D" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="p" isExecutable="true">
    <bpmn:adHocSubProcess id="probe_tools">
      <bpmn:scriptTask id="do_work" spiffworkflow:serverScript="{tool_script}" />
    </bpmn:adHocSubProcess>
    <bpmn:scriptTask id="answer" spiffworkflow:serverScript="{closing_script}" />
  </bpmn:process>
</bpmn:definitions>"""

	def _exts(self):
		import json

		return {"agent": {
			"serviceType": "ai_agent",
			"aiToolsAdhoc": "probe_tools",
			"aiToolShapes": json.dumps([{"bpmn_id": "do_work"}]),
		}}

	def test_a_key_nothing_writes_is_reported_with_the_script_and_the_key(self):
		tool = self._script("_Test Probe Tool", 'update_turn(c, output={"summary": 1})')
		closing = self._script("_Test Probe Answer", '_t = get_turn(c)\n_out = _t.get("output")\nx = _out.get("pull_request")')
		warnings = _validate_turn_store_contract(self._map(tool, closing), self._exts())
		self.assertEqual(len(warnings), 1)
		detail = warnings[0]["detail"]
		self.assertIn("pull_request", detail)
		self.assertIn("answer", detail)
		self.assertIn(closing, detail)
		self.assertEqual(warnings[0]["type"], "warning")

	def test_a_key_the_tool_writes_is_not_reported(self):
		tool = self._script("_Test Probe Tool", 'update_turn(c, output={"summary": 1})')
		closing = self._script("_Test Probe Answer", '_t = get_turn(c)\n_out = _t.get("output")\nx = _out.get("summary")')
		self.assertEqual(_validate_turn_store_contract(self._map(tool, closing), self._exts()), [])

	def test_a_key_a_main_flow_script_writes_is_not_reported(self):
		"""Build Context seeds the turn before the agent runs.

		Counting only the tools as writers reported keys that are set on every
		single turn, which is noise on every chat agent we have.
		"""
		tool = self._script("_Test Probe Tool", 'update_turn(c, done=True)')
		closing = self._script(
			"_Test Probe Answer",
			'set_turn(c, {"session_state": s})\n_t = get_turn(c)\nx = _t.get("session_state")',
		)
		self.assertEqual(_validate_turn_store_contract(self._map(tool, closing), self._exts()), [])
