# Copyright (c) 2026, one-fm and contributors
"""A document event raised by the engine itself must not advance the instance again."""

from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn import trigger


class TestTriggerEngineReentry(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.doc = frappe.get_doc({"doctype": "ToDo", "description": "reentry probe"})
		self.doc.name = "TODO-REENTRY"
		self.previous_flag = frappe.flags.bpmn_engine_action
		self.addCleanup(setattr, frappe.flags, "bpmn_engine_action", self.previous_flag)

	@mock.patch.object(trigger, "_advance_instance_on_doc_event")
	@mock.patch.object(trigger.frappe, "get_all", return_value=["INST-1"])
	def test_engine_raised_event_does_not_advance(self, _get_all, advance):
		frappe.flags.bpmn_engine_action = True

		trigger._maybe_advance_instances(self.doc, "Submit")

		advance.assert_not_called()

	@mock.patch.object(trigger, "_advance_instance_on_doc_event")
	@mock.patch.object(trigger.frappe, "get_all", return_value=["INST-1"])
	def test_user_raised_event_still_advances(self, _get_all, advance):
		frappe.flags.bpmn_engine_action = False

		trigger._maybe_advance_instances(self.doc, "Submit")

		advance.assert_called_once_with("INST-1", "Submit")
