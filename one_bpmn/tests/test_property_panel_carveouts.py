# Copyright (c) 2026, one-fm and contributors
"""What a released property panel may and may not change.

Releasing the panel widens editing on a LOCKED production map, so the value of
this module is entirely in what it refuses. The rule it enforces is that a panel
edit may change what a step does, never what the map is: an edit that breaks
compilation, orphans a reference or silently discards other settings stays
blocked even here.

The frontend applies the same carve-outs in BpmnEditor.vue so the fields never
become editable in the first place. These tests cover the server side, because
that is the half that holds when the canvas guard is bypassed.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api import property_panel as P

PREFIX = "ZZ PropPanel"

XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
                  id="defs_zz" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="zz_proc" isExecutable="true">
    <bpmn:userTask id="zz_user" name="Approve the thing" />
    <bpmn:serviceTask id="zz_service" name="Set the state"
                      spiffworkflow:serviceType="apply_workflow" />
    <bpmn:serviceTask id="zz_agent" name="Ask the agent"
                      spiffworkflow:serviceType="ai_agent" />
    <bpmn:scriptTask id="zz_script" name="Compute a total" />
    <bpmn:sequenceFlow id="zz_flow" sourceRef="zz_user" targetRef="zz_service" />
  </bpmn:process>
</bpmn:definitions>"""


class CarveOutCase(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._cleanup()
		self.original_instance_type = frappe.db.get_single_value("Processa Settings", "instance_type")
		# The panel is Production-only and that guard runs first, so without this
		# every test below would pass by being refused for the wrong reason.
		self._set_instance_type("Production")
		self.model = frappe.get_doc({
			"doctype": "BPMN Process Model",
			"title": f"{PREFIX} model",
			"process_id": "zz_proc",
			"version": 1,
			"bpmn_xml": XML,
		}).insert(ignore_permissions=True).name

	def tearDown(self):
		self._set_instance_type(self.original_instance_type)
		self._cleanup()
		frappe.db.commit()

	def _set_instance_type(self, value):
		frappe.db.set_single_value("Processa Settings", "instance_type", value)
		frappe.clear_cache(doctype="Processa Settings")

	def _cleanup(self):
		for name in frappe.get_all(
			"BPMN Process Model", filters={"title": ["like", f"{PREFIX}%"]}, pluck="name"
		):
			frappe.delete_doc("BPMN Process Model", name, force=True, ignore_permissions=True)

	def _xml(self):
		return frappe.db.get_value("BPMN Process Model", self.model, "bpmn_xml") or ""


class TestWhatItAllows(CarveOutCase):
	def test_a_user_task_assignment_still_works(self):
		"""The behaviour this began as, which must survive the widening."""
		out = P.update_element_properties(
			self.model, "zz_user", {"assigneeMode": "User", "assigneeUser": "Administrator"}
		)
		self.assertTrue(out["updated"])
		self.assertIn('assigneeMode="User"', self._xml())

	def test_a_service_task_can_be_reconfigured(self):
		"""The whole point of releasing the panel — a Service Task's settings
		were unreachable before, User Tasks being the only editable element."""
		out = P.update_element_properties(
			self.model, "zz_service",
			{"serviceTargetDoctype": "Visa Request", "workflowState": "Draft"},
		)
		self.assertTrue(out["updated"])
		self.assertIn('workflowState="Draft"', self._xml())

	def test_a_display_name_can_be_corrected(self):
		P.update_element_properties(self.model, "zz_user", {"name": "Approve the request"})
		self.assertIn('name="Approve the request"', self._xml())

	def test_clearing_a_value_removes_the_attribute(self):
		P.update_element_properties(self.model, "zz_service", {"workflowState": "Draft"})
		P.update_element_properties(self.model, "zz_service", {"workflowState": ""})
		self.assertNotIn("workflowState", self._xml())


class TestWhatItRefuses(CarveOutCase):
	def _refused(self, element, properties):
		with self.assertRaises(frappe.ValidationError):
			P.update_element_properties(self.model, element, properties)

	def test_a_script_task_stays_read_only(self):
		self._refused("zz_script", {"name": "Renamed"})

	def test_an_ai_agent_task_stays_read_only(self):
		"""An AI Agent Task is a Service Task wearing a serviceType, so it has to
		be recognised by that attribute rather than by its element name."""
		self._refused("zz_agent", {"aiModel": "claude-sonnet-5"})

	def test_a_sequence_flow_stays_read_only(self):
		"""A wrong condition does not look broken, it just takes the wrong
		branch, so routing is not a panel edit."""
		self._refused("zz_flow", {"name": "Approved"})

	def test_the_id_cannot_be_changed(self):
		"""Every flow, the compiled spec and every running instance reference it."""
		self._refused("zz_user", {"id": "something_else"})

	def test_the_service_type_cannot_be_switched(self):
		"""Switching the kind of a Service Task makes its other attributes
		meaningless and the panel clears them — silent config loss on a live map."""
		self._refused("zz_service", {"serviceType": "send_email"})

	def test_a_call_activity_cannot_be_repointed(self):
		self._refused("zz_user", {"calledElement": "SomeOtherProcess"})

	def test_no_script_bearing_attribute_can_be_written(self):
		"""Scripts are read-only wherever they hang, not only on Script Tasks."""
		for attr in ("preScript", "postScript", "scriptFormat"):
			self._refused("zz_user", {attr: "frappe.db.sql('...')"})

	def test_a_refused_property_leaves_the_map_untouched(self):
		"""A rejected call must not half-apply the rest of the same request."""
		before = self._xml()
		with self.assertRaises(frappe.ValidationError):
			P.update_element_properties(
				self.model, "zz_user", {"assigneeMode": "User", "id": "nope"}
			)
		self.assertEqual(self._xml(), before)


class TestTheProductionGate(CarveOutCase):
	def test_a_non_production_instance_refuses_everything(self):
		"""The gate that makes the whole feature acceptable — checked here and
		not only in the Actions menu, so bypassing the menu changes nothing."""
		self._set_instance_type("BA")
		with self.assertRaises(frappe.ValidationError):
			P.update_element_properties(self.model, "zz_user", {"assigneeMode": "Round Robin"})
