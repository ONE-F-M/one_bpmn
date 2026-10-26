# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn import trigger

EDIT = "TestMessageStartDoc_Edit_Action"
DELETE = "TestMessageStartDoc_Delete_Action"
MODEL = "_Test Message Start Listener"


def _diagram(start_message, catch_message=None):
	catch = (
		f'<bpmn:intermediateCatchEvent id="c1"><bpmn:messageEventDefinition messageRef="m2" />'
		f"</bpmn:intermediateCatchEvent>"
		if catch_message
		else ""
	)
	declared = f'<bpmn:message id="m2" name="{catch_message}" />' if catch_message else ""
	return (
		'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="d">'
		f'<bpmn:message id="m1" name="{start_message}" />{declared}'
		'<bpmn:process id="p" isExecutable="true">'
		'<bpmn:startEvent id="s1"><bpmn:messageEventDefinition messageRef="m1" /></bpmn:startEvent>'
		f"{catch}</bpmn:process></bpmn:definitions>"
	)


def _model(name, xml):
	if frappe.db.exists("BPMN Process Model", name):
		frappe.delete_doc("BPMN Process Model", name, force=True)
	doc = frappe.get_doc(
		{
			"doctype": "BPMN Process Model",
			"title": name,
			"process_id": "p",
			"version": 1,
			"is_active": 1,
			"bpmn_xml": xml,
		}
	)
	doc.name = name
	doc.db_insert()


def _instance(model, status, doc):
	frappe.get_doc(
		{
			"doctype": "BPMN Process Instance",
			"process_model": model,
			"status": status,
			"context_doctype": doc.doctype,
			"context_docname": doc.name,
		}
	).db_insert()


class MessageStartFixtures(FrappeTestCase):
	def setUp(self):
		frappe.cache.delete_value(trigger.MESSAGE_START_INDEX_KEY)
		_model(MODEL, _diagram(EDIT, catch_message=DELETE))
		self.doc = frappe._dict(doctype="TestMessageStartDoc", name="_test-doc-1")
		frappe.flags._bpmn_message_sent = set()

	def tearDown(self):
		frappe.cache.delete_value(trigger.MESSAGE_START_INDEX_KEY)
		frappe.db.rollback()


class TestWhichMapsAMessageStarts(MessageStartFixtures):
	def test_a_start_event_bound_to_the_message_is_found(self):
		self.assertIn(MODEL, trigger.message_start_models(EDIT))

	def test_a_map_that_only_catches_the_message_part_way_is_not_started_by_it(self):
		self.assertNotIn(MODEL, trigger.message_start_models(DELETE))


class TestAnEditStartsTheListeningMap(MessageStartFixtures):
	def test_an_edit_with_no_running_instance_starts_the_listening_map(self):
		with patch("one_bpmn.api.instance_api._start_and_deliver_message") as start:
			trigger._maybe_send_message(self.doc, "Edit_Action")
		start.assert_called_once()
		kwargs = start.call_args.kwargs
		self.assertEqual(kwargs["model_name"], MODEL)
		self.assertEqual(kwargs["message_name"], EDIT)
		self.assertEqual((kwargs["context_doctype"], kwargs["context_docname"]), (self.doc.doctype, self.doc.name))

	def test_a_running_instance_of_the_listening_map_is_not_doubled(self):
		_instance(MODEL, "Active", self.doc)
		with patch("one_bpmn.api.instance_api._start_and_deliver_message") as start:
			trigger._maybe_send_message(self.doc, "Edit_Action")
		start.assert_not_called()

	def test_two_maps_on_one_message_start_neither(self):
		_model(MODEL + " 2", _diagram(EDIT))
		with (
			patch("one_bpmn.api.instance_api._start_and_deliver_message") as start,
			patch.object(frappe, "log_error") as log_error,
		):
			trigger._maybe_send_message(self.doc, "Edit_Action")
		start.assert_not_called()
		log_error.assert_called_once()

	def test_a_failing_map_does_not_block_the_save(self):
		with (
			patch("one_bpmn.api.instance_api._start_and_deliver_message", side_effect=Exception("boom")),
			patch.object(frappe, "log_error") as log_error,
		):
			trigger._maybe_send_message(self.doc, "Edit_Action")
		log_error.assert_called_once()


class TestADeleteStartsTheListeningMapWhileTheDocumentExists(MessageStartFixtures):
	def test_a_delete_with_no_instance_runs_the_listening_map_in_the_request(self):
		_model(MODEL, _diagram(DELETE))
		with patch("one_bpmn.api.instance_api._start_and_deliver_message") as start:
			trigger.delete_linked_bpmn_instances(self.doc, "on_trash")
		start.assert_called_once()
		self.assertEqual(start.call_args.kwargs["message_name"], DELETE)

	def test_a_delete_after_another_map_finished_still_runs_the_listening_map(self):
		_model(MODEL, _diagram(DELETE))
		_instance(MODEL + " other", "Completed", self.doc)
		with patch("one_bpmn.api.instance_api._start_and_deliver_message") as start:
			trigger.delete_linked_bpmn_instances(self.doc, "on_trash")
		start.assert_called_once()

	def test_a_delete_nothing_listens_for_does_nothing(self):
		with patch("one_bpmn.api.instance_api._start_and_deliver_message") as start:
			trigger.delete_linked_bpmn_instances(self.doc, "on_trash")
		start.assert_not_called()
