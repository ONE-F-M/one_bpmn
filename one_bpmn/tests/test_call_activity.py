# Copyright (c) 2026, one-fm and contributors
# WI-002111: a Call Activity must be able to run another BPMN Process Model.
#
# Before this, `calledElement` could only ever name a process inside the SAME
# document, because parse_bpmn registered exactly one file with the parser and
# SpiffWorkflow resolves calledElement only against processes that parser has
# seen. Compiling the caller failed with "The process 'x' was not found" — which
# is why the only Call Activity in the wild carried an empty calledElement.
#
# Two things had to be true, and the second is the one that bites silently:
#   1. the called document is registered with the parser, so the spec resolves;
#   2. the called document's spiffworkflow:* task extensions are merged into the
#      CALLER's extension maps. A Call Activity runs the called process inside
#      the caller's instance, so the caller's maps are what the engine consults.
#      Without (2) the child's tasks compile, run, and report "Completed" while
#      doing nothing at all.

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.compilation import _resolve_called_process_xml, compile_process_model
from one_bpmn.one_bpmn import engine

CHILD_ID = "wi2111_child"
PARENT_ID = "wi2111_parent"
OTHER_ID = "wi2111_other"


def _child_xml(process_id=CHILD_ID, script_task=True):
	"""A called process. Its Script Task is Server-Script-driven with NO inline
	<bpmn:script>, which is how the picker writes them and what used to break
	the parent's compile."""
	script = (
		'<bpmn:scriptTask id="child_step" name="Child step" '
		'spiffworkflow:serverScript="WI2111 Child Script" '
		'spiffworkflow:scriptType="Server Script" '
		'spiffworkflow:scriptName="WI2111 Child Script">'
		"<bpmn:incoming>cf1</bpmn:incoming><bpmn:outgoing>cf2</bpmn:outgoing>"
		"</bpmn:scriptTask>"
		if script_task
		else '<bpmn:task id="child_step"><bpmn:incoming>cf1</bpmn:incoming>'
		"<bpmn:outgoing>cf2</bpmn:outgoing></bpmn:task>"
	)
	return f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
 xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
 id="Defs_{process_id}" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="{process_id}" name="Child" isExecutable="true">
    <bpmn:startEvent id="cs"><bpmn:outgoing>cf1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:sequenceFlow id="cf1" sourceRef="cs" targetRef="child_step" />
    {script}
    <bpmn:sequenceFlow id="cf2" sourceRef="child_step" targetRef="ce" />
    <bpmn:endEvent id="ce"><bpmn:incoming>cf2</bpmn:incoming></bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>"""


def _parent_xml(called="wi2111_child", process_id=PARENT_ID):
	called_attr = f' calledElement="{called}"' if called else ""
	return f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
 xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
 id="Defs_{process_id}" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="{process_id}" name="Parent" isExecutable="true">
    <bpmn:startEvent id="ps"><bpmn:outgoing>pf1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:sequenceFlow id="pf1" sourceRef="ps" targetRef="call_child" />
    <bpmn:callActivity id="call_child" name="Call the child"{called_attr}>
      <bpmn:incoming>pf1</bpmn:incoming><bpmn:outgoing>pf2</bpmn:outgoing>
    </bpmn:callActivity>
    <bpmn:sequenceFlow id="pf2" sourceRef="call_child" targetRef="pe" />
    <bpmn:endEvent id="pe"><bpmn:incoming>pf2</bpmn:incoming></bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>"""


class TestCallActivityResolution(FrappeTestCase):
	"""parse_bpmn: registering the called document is what makes it resolve."""

	def test_calling_an_unregistered_process_fails(self):
		"""The bug, pinned: without the called document the parser cannot
		resolve calledElement, however valid the diagram looks."""
		with self.assertRaises(Exception) as ctx:
			engine.parse_bpmn(_parent_xml(), PARENT_ID)
		self.assertIn("not found", str(ctx.exception).lower())

	def test_registering_the_called_document_resolves_it(self):
		spec, _ = engine.parse_bpmn(
			_parent_xml(), PARENT_ID, called_xml_list=[_child_xml(script_task=False)]
		)
		self.assertIn(CHILD_ID, spec.get("subprocess_specs") or {})

	def test_called_spec_survives_serialization(self):
		"""The specs ride inside serialized_spec — parse_bpmn's empty second
		return value is deliberate, not a dropped result."""
		spec, sp_dict = engine.parse_bpmn(
			_parent_xml(), PARENT_ID, called_xml_list=[_child_xml(script_task=False)]
		)
		self.assertEqual(sp_dict, {})
		json.dumps(spec)  # storable
		child = (spec.get("subprocess_specs") or {}).get(CHILD_ID) or {}
		self.assertTrue(child.get("task_specs"), "called process has no task specs")

	def test_empty_called_element_is_rejected_by_the_parser(self):
		"""Pins PRE-EXISTING behaviour, not something this story introduced.

		SpiffWorkflow throws 'No "calledElement" attribute for Call Activity'
		for an unconfigured shape, so such a map has never compiled. `POA V1`
		is active only because it was compiled before its Call Activity was
		drawn; recompiling it fails today exactly as it did before this change.
		Recorded here so a future reader does not mistake it for a regression.
		"""
		with self.assertRaises(Exception) as ctx:
			engine.parse_bpmn(_parent_xml(called=""), PARENT_ID)
		self.assertIn("calledelement", str(ctx.exception).lower())


class TestCallActivityCompile(FrappeTestCase):
	"""compile_process_model: resolution, extension merging, and the errors."""

	def setUp(self):
		super().setUp()
		self._models = []

	def tearDown(self):
		for name in self._models:
			if frappe.db.exists("BPMN Process Model", name):
				frappe.delete_doc("BPMN Process Model", name, force=1, ignore_permissions=True)
		frappe.db.commit()
		super().tearDown()

	def _model(self, name, process_id, xml):
		if frappe.db.exists("BPMN Process Model", name):
			frappe.delete_doc("BPMN Process Model", name, force=1, ignore_permissions=True)
		doc = frappe.new_doc("BPMN Process Model")
		doc.name = name
		doc.title = name
		doc.process_id = process_id
		doc.bpmn_xml = xml
		doc.version = 1
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		self._models.append(name)
		return doc

	def test_resolver_returns_the_called_models_xml(self):
		self._model("WI2111 Child", CHILD_ID, _child_xml())
		self._model("WI2111 Parent", PARENT_ID, _parent_xml())
		found = _resolve_called_process_xml(_parent_xml(), "WI2111 Parent")
		self.assertEqual(len(found), 1)
		self.assertIn(f'id="{CHILD_ID}"', found[0])

	def test_server_script_task_in_the_called_map_gets_an_inline_script(self):
		"""A Script Task driven only by the Server Script picker carries no
		<bpmn:script>, and SpiffWorkflow asserts exactly one. The called
		document must get the same injection the main one does, or the parent
		fails with 'Invalid Script Task. No Script Provided.'"""
		self._model("WI2111 Child", CHILD_ID, _child_xml())
		found = _resolve_called_process_xml(_parent_xml(), "WI2111 Parent")
		self.assertIn("<bpmn:script>", found[0])

	def test_unknown_called_element_throws_a_readable_error(self):
		self._model("WI2111 Parent", PARENT_ID, _parent_xml(called="nope_does_not_exist"))
		with self.assertRaises(frappe.ValidationError) as ctx:
			_resolve_called_process_xml(
				_parent_xml(called="nope_does_not_exist"), "WI2111 Parent"
			)
		message = str(ctx.exception)
		self.assertIn("nope_does_not_exist", message)
		self.assertIn("call_child", message)

	def test_empty_called_element_resolves_to_nothing(self):
		"""An unconfigured Call Activity has nothing to look up, so the resolver
		must return empty rather than throwing its own error over the top of the
		parser's (which is the one that actually reports the problem)."""
		self.assertEqual(_resolve_called_process_xml(_parent_xml(called=""), "WI2111 Parent"), [])

	def test_an_ai_task_with_no_user_prompt_warns_at_deploy(self):
		"""An AI task with a system prompt but no user prompt is a broken map that
		looks fine: the model is handed an empty turn and answers "no content was
		provided to me", so every run afterwards reads as the agent misbehaving
		rather than the map missing a field. It cost two test cycles on the same
		map — the attribute went missing after a properties-panel edit both
		times — so deploy is where it gets said out loud."""
		from one_bpmn.api.compilation import _check_ai_tasks_have_a_user_prompt

		broken = {"service_task_extensions": {
			"orchestrate": {"serviceType": "ai_agent", "aiSystemPrompt": "You are..."}
		}}
		warnings = _check_ai_tasks_have_a_user_prompt(broken)
		self.assertEqual(len(warnings), 1)
		self.assertIn("orchestrate", warnings[0]["detail"])

	def test_a_complete_ai_task_does_not_warn(self):
		from one_bpmn.api.compilation import _check_ai_tasks_have_a_user_prompt

		fine = {"service_task_extensions": {
			"orchestrate": {
				"serviceType": "ai_agent",
				"aiSystemPrompt": "You are...",
				"aiUserPrompt": "{{ brief }}",
			}
		}}
		self.assertEqual(_check_ai_tasks_have_a_user_prompt(fine), [])

	def test_a_task_that_is_not_an_ai_agent_is_not_judged(self):
		from one_bpmn.api.compilation import _check_ai_tasks_have_a_user_prompt

		other = {"service_task_extensions": {
			"send_it": {"serviceType": "send_email", "aiSystemPrompt": "irrelevant"}
		}}
		self.assertEqual(_check_ai_tasks_have_a_user_prompt(other), [])

	def test_recompiling_a_called_map_refreshes_its_callers(self):
		"""A caller embeds a COPY of the called map, so editing the called map
		alone changed nothing for anyone calling it.

		This cost a real test cycle. A capability was set on a delegate shape in
		the Orchestrator Agent map and the map was activated; the map compiled
		with the setting, the caller kept the previous day's copy without it, and
		the run behaved as though the setting had never been made. Nothing
		errored, which is what made it invisible.
		"""
		from one_bpmn.api.compilation import compile_process_model

		child = self._model("WI2111 Child", CHILD_ID, _child_xml())
		parent = self._model("WI2111 Parent", PARENT_ID, _parent_xml())
		compile_process_model(parent.name)
		before = frappe.db.get_value("BPMN Process Model", parent.name, "serialized_spec")
		self.assertTrue(before, "the caller compiled")

		# Change the CALLED map only — the Server Script its task runs, which is
		# exactly the kind of edit that has to reach a caller — then compile only
		# the called map.
		child.bpmn_xml = _child_xml().replace(
			"WI2111 Child Script", "WI2111 Child Script Renamed"
		)
		child.flags.ignore_permissions = True
		child.save(ignore_permissions=True)
		compile_process_model(child.name)

		after = frappe.db.get_value("BPMN Process Model", parent.name, "serialized_spec")
		self.assertNotEqual(
			before, after, "compiling the called map must refresh the caller's embedded copy"
		)
		self.assertIn("WI2111 Child Script Renamed", after)

	def test_a_caller_that_cannot_compile_does_not_break_the_called_map(self):
		"""The map the person actually saved has already compiled; a problem in
		something that calls it must be logged, not rolled back onto them."""
		from one_bpmn.api.compilation import compile_process_model

		child = self._model("WI2111 Child", CHILD_ID, _child_xml())
		# A caller whose XML is broken enough that its own compile fails.
		self._model("WI2111 Broken", PARENT_ID, _parent_xml().replace("<bpmn:process", "<bpmn:proc"))
		result = compile_process_model(child.name)
		self.assertTrue(result["success"])

	def test_mutual_calls_do_not_recurse_forever(self):
		"""Two maps calling each other resolve once each rather than hanging."""
		self._model("WI2111 Child", CHILD_ID, _child_xml())
		self._model("WI2111 Other", OTHER_ID, _parent_xml(called=CHILD_ID, process_id=OTHER_ID))
		# child_xml has no call activity, so build a child that calls back.
		looping_child = _child_xml().replace(
			'<bpmn:endEvent id="ce"><bpmn:incoming>cf2</bpmn:incoming></bpmn:endEvent>',
			'<bpmn:endEvent id="ce"><bpmn:incoming>cf2</bpmn:incoming></bpmn:endEvent>'
			f'<bpmn:callActivity id="back" calledElement="{PARENT_ID}" />',
		)
		frappe.db.set_value("BPMN Process Model", "WI2111 Child", "bpmn_xml", looping_child)
		self._model("WI2111 Parent", PARENT_ID, _parent_xml())
		found = _resolve_called_process_xml(_parent_xml(), "WI2111 Parent")
		# The parent is already known to the parser, so only the child comes back.
		self.assertEqual(len(found), 1)

	def test_called_task_extensions_are_merged_into_the_caller(self):
		"""The silent one. A Call Activity runs the called process inside the
		caller's instance, so the caller's extension maps are what the engine
		reads at runtime. Miss this and the child's tasks report Completed
		having done nothing."""
		self._model("WI2111 Child", CHILD_ID, _child_xml())
		parent = self._model("WI2111 Parent", PARENT_ID, _parent_xml())
		compile_process_model(parent.name)
		spec = json.loads(
			frappe.db.get_value("BPMN Process Model", parent.name, "serialized_spec") or "{}"
		)
		self.assertIn(
			"child_step",
			spec.get("script_task_extensions") or {},
			"the called map's Script Task is missing from the caller's extensions — "
			"it would run as a silent no-op",
		)
		self.assertEqual(
			(spec["script_task_extensions"]["child_step"] or {}).get("serverScript"),
			"WI2111 Child Script",
		)

	def test_caller_own_extensions_win_on_id_collision(self):
		"""The document being compiled is authoritative for a shared bpmn_id."""
		self._model("WI2111 Child", CHILD_ID, _child_xml())
		colliding_parent = _parent_xml().replace(
			'<bpmn:sequenceFlow id="pf2" sourceRef="call_child" targetRef="pe" />',
			'<bpmn:sequenceFlow id="pf2" sourceRef="call_child" targetRef="child_step" />'
			'<bpmn:scriptTask id="child_step" name="Parent step" '
			'spiffworkflow:serverScript="WI2111 Parent Script" '
			'spiffworkflow:scriptType="Server Script" '
			'spiffworkflow:scriptName="WI2111 Parent Script">'
			"<bpmn:incoming>pf2</bpmn:incoming><bpmn:outgoing>pf3</bpmn:outgoing>"
			"</bpmn:scriptTask>"
			'<bpmn:sequenceFlow id="pf3" sourceRef="child_step" targetRef="pe" />',
		)
		parent = self._model("WI2111 Parent", PARENT_ID, colliding_parent)
		compile_process_model(parent.name)
		spec = json.loads(
			frappe.db.get_value("BPMN Process Model", parent.name, "serialized_spec") or "{}"
		)
		self.assertEqual(
			spec["script_task_extensions"]["child_step"]["serverScript"], "WI2111 Parent Script"
		)
