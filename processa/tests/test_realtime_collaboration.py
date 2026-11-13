"""Real-time collaboration on the BPMN process model editor (server side).

Run with:
    bench --site SITE run-tests --app processa --module processa.tests.test_realtime_collaboration
"""

from __future__ import annotations

import time
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.api import collaboration
from processa.api.collaboration import (
	EVENT_AWARENESS,
	EVENT_DIAGRAM_CHANGE,
	EVENT_DIAGRAM_SAVED,
	EVENT_PRESENCE,
	PRESENCE_CACHE_KEY,
	StaleDiagramRevision,
)


def _diagram(process_id: str, label: str = "v1") -> str:
	return (
		'<?xml version="1.0" encoding="UTF-8"?>'
		'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"'
		' xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI">'
		f'<bpmn:process id="{process_id}" name="{label}" isExecutable="true" />'
		'<bpmndi:BPMNDiagram id="d1">'
		f'<bpmndi:BPMNPlane id="p1" bpmnElement="{process_id}" />'
		"</bpmndi:BPMNDiagram></bpmn:definitions>"
	)


def _calls(publish, event: str) -> list:
	"""The (args, kwargs) of every publish_realtime call for one event name."""
	return [(c.args, c.kwargs) for c in publish.call_args_list if c.args and c.args[0] == event]


class CollaborationCase(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		suffix = frappe.generate_hash(length=8)
		self.process_id = f"collab_{suffix}"
		doc = frappe.new_doc("BPMN Process Model")
		doc.title = f"Collab {suffix}"
		doc.process_id = self.process_id
		doc.bpmn_xml = _diagram(self.process_id)
		doc.version = 0
		doc.flags.skip_editability_check = True
		doc.flags.skip_script_security_check = True
		doc.flags.skip_process_id_regeneration = True
		doc.insert(ignore_permissions=True)
		self.model = doc.name

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.cache.delete_value(PRESENCE_CACHE_KEY.format(self.model))
		for snap in frappe.get_all("BPMN Diagram Version", filters={"model": self.model}, pluck="name"):
			frappe.delete_doc("BPMN Diagram Version", snap, ignore_permissions=True, force=True)
		if frappe.db.exists("BPMN Process Model", self.model):
			frappe.delete_doc("BPMN Process Model", self.model, ignore_permissions=True, force=True)

	def revision(self) -> int:
		return frappe.db.get_value("BPMN Process Model", self.model, "diagram_revision") or 0


class TestDiagramRevision(CollaborationCase):
	def test_a_new_model_starts_at_revision_zero(self):
		self.assertEqual(self.revision(), 0)

	def test_changing_the_diagram_advances_the_revision(self):
		doc = frappe.get_doc("BPMN Process Model", self.model)
		doc.bpmn_xml = _diagram(self.process_id, "v2")
		doc.flags.skip_editability_check = True
		doc.flags.skip_script_security_check = True
		doc.save()

		self.assertEqual(self.revision(), 1)

	def test_a_metadata_only_save_leaves_the_revision_alone(self):
		doc = frappe.get_doc("BPMN Process Model", self.model)
		doc.description = "just a note"
		doc.flags.skip_editability_check = True
		doc.save()

		self.assertEqual(self.revision(), 0)

	def test_a_revision_sent_by_the_caller_is_ignored(self):
		doc = frappe.get_doc("BPMN Process Model", self.model)
		doc.bpmn_xml = _diagram(self.process_id, "v2")
		doc.diagram_revision = 500
		doc.flags.skip_editability_check = True
		doc.flags.skip_script_security_check = True
		doc.save()

		self.assertEqual(self.revision(), 1)


class TestSavingADiagram(CollaborationCase):
	def test_a_save_on_the_current_revision_succeeds_and_broadcasts_to_the_model_room(self):
		new_xml = _diagram(self.process_id, "from-alice")

		with patch.object(frappe, "publish_realtime") as publish:
			out = collaboration.save_diagram(self.model, new_xml, base_revision=0, client_id="tab-1")

		self.assertTrue(out["saved"])
		self.assertEqual(out["revision"], 1)
		self.assertEqual(frappe.db.get_value("BPMN Process Model", self.model, "bpmn_xml"), new_xml)

		# Saving also emits Frappe's own doc_update / list_update events; look at ours only.
		calls = _calls(publish, EVENT_DIAGRAM_SAVED)
		self.assertEqual(len(calls), 1)
		args, kwargs = calls[0]
		self.assertEqual(args[0], EVENT_DIAGRAM_SAVED)
		self.assertEqual(kwargs["doctype"], "BPMN Process Model")
		self.assertEqual(kwargs["docname"], self.model)
		self.assertTrue(kwargs["after_commit"])
		payload = args[1]
		self.assertEqual(payload["revision"], 1)
		self.assertEqual(payload["previous_revision"], 0)
		self.assertEqual(payload["client_id"], "tab-1")
		self.assertEqual(payload["saved_by"]["user"], "Administrator")

	def test_a_stale_save_is_refused_and_does_not_overwrite_or_broadcast(self):
		collaboration.save_diagram(self.model, _diagram(self.process_id, "from-alice"), base_revision=0)
		alice_xml = frappe.db.get_value("BPMN Process Model", self.model, "bpmn_xml")

		with patch.object(frappe, "publish_realtime") as publish:
			with self.assertRaises(StaleDiagramRevision):
				# Bob still holds revision 0.
				collaboration.save_diagram(self.model, _diagram(self.process_id, "from-bob"), base_revision=0)

		self.assertEqual(frappe.db.get_value("BPMN Process Model", self.model, "bpmn_xml"), alice_xml)
		self.assertEqual(self.revision(), 1)
		publish.assert_not_called()

	def test_a_stale_save_answers_with_conflict(self):
		self.assertEqual(StaleDiagramRevision.http_status_code, 409)

	def test_after_reloading_the_new_revision_a_save_goes_through(self):
		collaboration.save_diagram(self.model, _diagram(self.process_id, "from-alice"), base_revision=0)
		out = collaboration.save_diagram(self.model, _diagram(self.process_id, "from-bob"), base_revision=1)

		self.assertEqual(out["revision"], 2)

	def test_a_save_without_a_base_revision_is_refused(self):
		# Frappe's type validation rejects None before the function body even runs.
		with self.assertRaises((TypeError, frappe.ValidationError)):
			collaboration.save_diagram(self.model, _diagram(self.process_id, "x"), base_revision=None)

		self.assertEqual(self.revision(), 0)

	def test_a_save_with_no_xml_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			collaboration.save_diagram(self.model, "", base_revision=0)


class TestPublishingALiveChange(CollaborationCase):
	def test_a_change_goes_to_the_model_room_with_the_sender_named(self):
		change = {"commands": [{"op": "shape.move", "id": "Task_1", "delta": {"x": 10, "y": 0}}]}

		with patch.object(frappe, "publish_realtime") as publish:
			out = collaboration.publish_diagram_change(self.model, 0, change, client_id="tab-1")

		self.assertEqual(out, {"ok": True, "stale": False, "revision": 0})
		publish.assert_called_once()
		args, kwargs = publish.call_args
		self.assertEqual(args[0], EVENT_DIAGRAM_CHANGE)
		self.assertEqual(kwargs["doctype"], "BPMN Process Model")
		self.assertEqual(kwargs["docname"], self.model)
		self.assertNotIn("user", kwargs)  # scoped to the model, not to one user
		payload = args[1]
		self.assertEqual(payload["model"], self.model)
		self.assertEqual(payload["change"], change)
		self.assertEqual(payload["revision"], 0)
		self.assertEqual(payload["client_id"], "tab-1")
		self.assertEqual(payload["sender"]["user"], "Administrator")

	def test_a_json_string_change_is_parsed(self):
		with patch.object(frappe, "publish_realtime") as publish:
			collaboration.publish_diagram_change(self.model, 0, '{"a": 1}')

		self.assertEqual(publish.call_args.args[1]["change"], {"a": 1})

	def test_publishing_writes_nothing(self):
		with patch.object(frappe, "publish_realtime"):
			collaboration.publish_diagram_change(self.model, 0, {"a": 1})

		self.assertEqual(self.revision(), 0)

	def test_a_change_based_on_an_old_revision_is_not_broadcast(self):
		collaboration.save_diagram(self.model, _diagram(self.process_id, "from-alice"), base_revision=0)

		with patch.object(frappe, "publish_realtime") as publish:
			out = collaboration.publish_diagram_change(self.model, 0, {"a": 1})

		self.assertEqual(out, {"ok": False, "stale": True, "current_revision": 1})
		publish.assert_not_called()

	def test_an_empty_change_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			collaboration.publish_diagram_change(self.model, 0, {})

	def test_an_oversized_change_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			collaboration.publish_diagram_change(self.model, 0, {"blob": "x" * (collaboration.MAX_CHANGE_BYTES + 1)})


class TestPermissions(CollaborationCase):
	def test_guest_cannot_do_anything(self):
		frappe.set_user("Guest")
		for call in (
			lambda: collaboration.join_model(self.model),
			lambda: collaboration.leave_model(self.model),
			lambda: collaboration.get_active_editors(self.model),
			lambda: collaboration.get_model_state(self.model),
			lambda: collaboration.publish_diagram_change(self.model, 0, {"a": 1}),
			lambda: collaboration.save_diagram(self.model, "<x/>", base_revision=0),
		):
			with patch.object(frappe, "publish_realtime") as publish, self.assertRaises(frappe.PermissionError):
				call()
			publish.assert_not_called()

	def test_an_unknown_model_is_refused(self):
		with self.assertRaises(frappe.DoesNotExistError):
			collaboration.join_model("no such model")

	def test_a_locked_model_cannot_be_edited_by_a_non_administrator(self):
		doc = frappe.get_doc("BPMN Process Model", self.model)
		with patch.object(collaboration, "_is_editable", return_value=False), patch.object(
			frappe.model.document.Document, "check_permission", return_value=None
		), patch.object(frappe, "publish_realtime") as publish:
			with self.assertRaises(frappe.PermissionError):
				collaboration._assert_can_edit(doc)
			with self.assertRaises(frappe.PermissionError):
				collaboration.publish_diagram_change(self.model, 0, {"a": 1})
			with self.assertRaises(frappe.PermissionError):
				collaboration.save_diagram(self.model, _diagram(self.process_id, "x"), base_revision=0)

		publish.assert_not_called()
		self.assertEqual(self.revision(), 0)


class TestPresence(CollaborationCase):
	def _key(self):
		return PRESENCE_CACHE_KEY.format(self.model)

	def test_joining_lists_the_user_and_the_current_revision(self):
		with patch.object(frappe, "publish_realtime"):
			out = collaboration.join_model(self.model, client_id="tab-1")

		self.assertEqual(out["model"], self.model)
		self.assertEqual(out["revision"], 0)
		self.assertTrue(out["can_edit"])
		self.assertEqual([e["name"] for e in out["editors"]], ["Administrator"])

	def test_joining_tells_the_room_and_a_heartbeat_does_not_repeat_it(self):
		with patch.object(frappe, "publish_realtime") as publish:
			collaboration.join_model(self.model, client_id="tab-1")
			collaboration.join_model(self.model, client_id="tab-1")

		calls = _calls(publish, EVENT_PRESENCE)
		self.assertEqual(len(calls), 1)
		args, kwargs = calls[0]
		self.assertEqual(args[0], EVENT_PRESENCE)
		self.assertEqual(kwargs["docname"], self.model)
		self.assertEqual(args[1]["action"], "joined")
		self.assertEqual(args[1]["user"], "Administrator")

	def test_other_active_editors_are_listed_and_expired_ones_are_not(self):
		frappe.cache.set_value(self._key(), {"Guest": time.time(), "Administrator": time.time() - 500})

		names = {e["name"] for e in collaboration.get_active_editors(self.model)}

		self.assertEqual(names, {"Guest"})

	def test_leaving_removes_the_user_and_tells_the_room(self):
		with patch.object(frappe, "publish_realtime") as publish:
			collaboration.join_model(self.model)
			publish.reset_mock()
			out = collaboration.leave_model(self.model, client_id="tab-1")

		self.assertEqual(out["editors"], [])
		self.assertEqual(collaboration.get_active_editors(self.model), [])
		self.assertEqual(publish.call_args.args[1]["action"], "left")

	def test_presence_shares_the_existing_editor_lock_entry(self):
		with patch.object(frappe, "publish_realtime"):
			collaboration.join_model(self.model)

		stored = frappe.cache.get_value(f"bpmn_editor_lock:{self.model}")
		self.assertIn("Administrator", stored or {}, f"stored={stored!r}")


class TestModelState(CollaborationCase):
	def test_state_carries_the_diagram_and_its_revision(self):
		collaboration.save_diagram(self.model, _diagram(self.process_id, "v2"), base_revision=0)

		state = collaboration.get_model_state(self.model)

		self.assertEqual(state["revision"], 1)
		self.assertIn('name="v2"', state["bpmn_xml"])
		self.assertEqual(state["model"], self.model)


class TestAwareness(CollaborationCase):
	def _set(self, **kwargs):
		with patch.object(frappe, "publish_realtime") as publish:
			collaboration.set_awareness(self.model, "tab-1", **kwargs)
		return _calls(publish, EVENT_AWARENESS)

	def test_the_selection_goes_to_the_model_room_with_who_sent_it(self):
		(args, kwargs), = self._set(mode="editing", selection=["Task_1"])
		self.assertEqual(kwargs["doctype"], "BPMN Process Model")
		self.assertEqual(kwargs["docname"], self.model)
		self.assertEqual(args[1]["selection"], ["Task_1"])
		self.assertEqual(args[1]["client_id"], "tab-1")
		self.assertEqual(args[1]["user"], "Administrator")
		self.assertEqual(args[1]["mode"], "editing")

	def test_a_viewer_who_cannot_edit_is_shown_as_viewing(self):
		with patch.object(collaboration, "_can_edit", return_value=False):
			(args, _), = self._set(mode="editing")
		self.assertEqual(args[1]["mode"], "viewing")

	def test_junk_is_dropped_and_the_selection_is_capped(self):
		(args, _), = self._set(mode="bogus", selection=["a", 5, None] + ["x"] * 100)
		self.assertEqual(args[1]["mode"], "viewing")
		self.assertEqual(len(args[1]["selection"]), 48)  # 50 kept, 2 of them not strings

	def test_awareness_writes_nothing_and_needs_a_client_id(self):
		with self.assertRaises(frappe.ValidationError):
			collaboration.set_awareness(self.model, "")

	def test_guest_is_refused(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			collaboration.set_awareness(self.model, "tab-1")
