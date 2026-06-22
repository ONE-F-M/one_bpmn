# Copyright (c) 2026, kartiksharma9319@gmail.com and Contributors
# See license.txt

"""
Characterization tests for the BPMN Process Instance controller helpers.

These tests pin the *current* behavior of the 8 helper methods that are about
to be extracted into sibling modules (dispatchers.py, assignment.py).  They are
written BEFORE the refactor so the extraction can be proven behavior-preserving.

To keep the test bodies untouched across the refactor, every call into a
soon-to-move method goes through a thin adapter defined in the ADAPTERS block
below.  After extraction, ONLY those adapters are repointed at the new
module-level functions (e.g. `inst._dispatch_email_notification(...)` becomes
`dispatch_email(inst, ...)`).  The assertions never change.
"""

import json
import sys
import types
from unittest.mock import Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

import one_bpmn.one_bpmn.engine as bpmn_engine
from one_bpmn.one_bpmn.doctype.bpmn_process_instance.dispatchers import (
	dispatch_email,
	dispatch_google_chat,
	dispatch_push_notification,
	dispatch_update_field,
)
from one_bpmn.one_bpmn.doctype.bpmn_process_instance.assignment import (
	_send_assignee_notification,
	add_frappe_assignment,
	get_reliever_if_on_leave,
	remove_frappe_assignment,
	resolve_assignment,
)

# ──────────────────────────────────────────────────────────────────────────────
# ADAPTERS — the ONLY lines that change across the refactor.
# All adapters now call the extracted dispatchers.py / assignment.py functions.
# ──────────────────────────────────────────────────────────────────────────────
def call_dispatch_update_field(inst, task, cfg, bpmn_id):
	return dispatch_update_field(inst, task, cfg, bpmn_id)


def call_dispatch_email(inst, task, cfg):
	return dispatch_email(inst, task, cfg)


def call_dispatch_google_chat(inst, task, cfg, bpmn_id):
	return dispatch_google_chat(inst, task, cfg, bpmn_id)


def call_dispatch_push(inst, task, cfg, bpmn_id):
	return dispatch_push_notification(inst, task, cfg, bpmn_id)


def call_resolve_assignment(inst, task):
	return resolve_assignment(inst, task)


def call_get_reliever(user):
	return get_reliever_if_on_leave(user)


def call_add_assignment(inst, user, task_name="", task_cfg=None):
	return add_frappe_assignment(inst, user, task_name, task_cfg=task_cfg)


def call_send_assignee_notification(inst, user, task_name, task_cfg):
	return _send_assignee_notification(inst, user, task_name, task_cfg)


def call_remove_assignment(inst, user):
	return remove_frappe_assignment(inst, user)


# ──────────────────────────────────────────────────────────────────────────────
# Test doubles
# ──────────────────────────────────────────────────────────────────────────────
class FakeTaskSpec:
	def __init__(self, bpmn_id):
		self.bpmn_id = bpmn_id


class FakeTask:
	"""Minimal stand-in for a SpiffWorkflow Task."""

	def __init__(self, bpmn_id="task_1", data=None):
		self.task_spec = FakeTaskSpec(bpmn_id)
		self.data = data or {}
		self.id = "task-uuid-001"


def make_instance(**kwargs):
	"""
	Build an unsaved BPMNProcessInstance with the attributes the helpers read.
	No DB insert — the helpers only read these attributes.
	"""
	inst = frappe.new_doc("BPMN Process Instance")
	inst.name = kwargs.get("name", "TEST-PI-001")
	inst.context_doctype = kwargs.get("context_doctype")
	inst.context_docname = kwargs.get("context_docname")
	inst.initiated_by = kwargs.get("initiated_by")
	inst.process_model = kwargs.get("process_model")
	# runtime-set attribute the engine populates at compile time
	inst._user_task_extensions = kwargs.get("user_task_extensions", {})
	return inst


class BaseBPMNHelperTest(FrappeTestCase):
	"""
	Neutralize frappe.log_error for the duration of each test.

	In this bench, an Error Log insert triggers an onefm_mcp doc-event hook that
	imports a broken google.adk/pydantic chain, so any helper that logs an error
	would crash the test on an unrelated environment defect.  These are
	control-flow characterization tests, not logging tests.
	"""

	def setUp(self):
		super().setUp()
		patcher = patch.object(frappe, "log_error")
		patcher.start()
		self.addCleanup(patcher.stop)


# ──────────────────────────────────────────────────────────────────────────────
# update_field dispatcher
# ──────────────────────────────────────────────────────────────────────────────
class TestDispatchUpdateField(BaseBPMNHelperTest):
	def _make_todo(self):
		return frappe.get_doc(
			{
				"doctype": "ToDo",
				"description": "bpmn characterization test",
				"allocated_to": "Administrator",
			}
		).insert(ignore_permissions=True)

	def test_update_field_rows_writes_value(self):
		todo = self._make_todo()
		inst = make_instance(context_docname=todo.name)
		cfg = {
			"updateFieldDoctype": "ToDo",
			"updateFieldRows": json.dumps([{"field": "priority", "value": "High"}]),
		}

		call_dispatch_update_field(inst, FakeTask(), cfg, "task_1")

		self.assertEqual(frappe.db.get_value("ToDo", todo.name, "priority"), "High")

	def test_update_field_legacy_single_field(self):
		todo = self._make_todo()
		inst = make_instance(context_docname=todo.name)
		cfg = {
			"updateFieldDoctype": "ToDo",
			"updateFieldName": "priority",
			"updateFieldValue": "Low",
		}

		call_dispatch_update_field(inst, FakeTask(), cfg, "task_1")

		self.assertEqual(frappe.db.get_value("ToDo", todo.name, "priority"), "Low")

	def test_update_field_renders_jinja(self):
		todo = self._make_todo()
		inst = make_instance(name="TEST-PI-XYZ", context_docname=todo.name)
		cfg = {
			"updateFieldDoctype": "ToDo",
			"updateFieldRows": json.dumps(
				[{"field": "description", "value": "From {{ instance.name }}"}]
			),
		}

		call_dispatch_update_field(inst, FakeTask(), cfg, "task_1")

		self.assertEqual(
			frappe.db.get_value("ToDo", todo.name, "description"), "From TEST-PI-XYZ"
		)

	def test_update_field_missing_context_is_noop(self):
		inst = make_instance(context_docname=None)
		cfg = {"updateFieldRows": json.dumps([{"field": "priority", "value": "High"}])}

		# No doctype/docname -> logs and returns, must not raise
		call_dispatch_update_field(inst, FakeTask(), cfg, "task_1")


# ──────────────────────────────────────────────────────────────────────────────
# send_email dispatcher
# ──────────────────────────────────────────────────────────────────────────────
class TestDispatchEmail(BaseBPMNHelperTest):
	def _patched_sendemail(self):
		"""
		Inject a fake one_fm.processor.sendemail so the test is deterministic
		regardless of whether one_fm is installed (the dispatcher imports it
		locally and falls back to frappe.sendmail only on ImportError).
		"""
		fake_proc = types.ModuleType("one_fm.processor")
		fake_proc.sendemail = Mock()
		fake_root = sys.modules.get("one_fm") or types.ModuleType("one_fm")
		patcher = patch.dict(
			sys.modules, {"one_fm": fake_root, "one_fm.processor": fake_proc}
		)
		return patcher, fake_proc.sendemail

	def test_email_direct_recipient_and_jinja_subject(self):
		inst = make_instance(name="TEST-PI-EMAIL", context_doctype="ToDo")
		cfg = {
			"emailTo": "a@b.com",
			"emailSubject": "Hello {{ instance.name }}",
			"emailBody": "Body text",
		}

		patcher, sendemail = self._patched_sendemail()
		with patcher:
			call_dispatch_email(inst, FakeTask(), cfg)

		self.assertTrue(sendemail.called)
		kwargs = sendemail.call_args.kwargs
		self.assertEqual(kwargs["recipients"], ["a@b.com"])
		self.assertEqual(kwargs["subject"], "Hello TEST-PI-EMAIL")

	def test_email_no_recipients_is_noop(self):
		inst = make_instance()
		cfg = {"emailSubject": "Hi", "emailBody": "x"}

		patcher, sendemail = self._patched_sendemail()
		with patcher:
			call_dispatch_email(inst, FakeTask(), cfg)

		self.assertFalse(sendemail.called)


# ──────────────────────────────────────────────────────────────────────────────
# google_chat dispatcher (guard / validation behavior)
# ──────────────────────────────────────────────────────────────────────────────
class TestDispatchGoogleChat(BaseBPMNHelperTest):
	def test_invalid_gchat_type_returns_without_error(self):
		inst = make_instance()
		cfg = {"gchatType": "bogus", "gchatMessage": "hi"}
		# Misconfigured -> logs and returns, must not raise
		call_dispatch_google_chat(inst, FakeTask(), cfg, "task_1")

	def test_missing_credentials_returns_without_error(self):
		inst = make_instance()
		cfg = {
			"gchatType": "space",
			"gchatSpaceId": "spaces/AAAA",
			"gchatMessage": "hi",
		}
		# Replace conf with an empty dict so the credentials key is absent
		with patch.object(frappe, "conf", frappe._dict()):
			call_dispatch_google_chat(inst, FakeTask(), cfg, "task_1")


# ──────────────────────────────────────────────────────────────────────────────
# push_notification dispatcher
# ──────────────────────────────────────────────────────────────────────────────
class TestDispatchPush(BaseBPMNHelperTest):
	def _inject_one_fm_utils(self):
		fake_utils = types.ModuleType("one_fm.utils")
		fake_utils.send_push_notification = Mock(return_value=True)
		fake_root = sys.modules.get("one_fm") or types.ModuleType("one_fm")
		patcher = patch.dict(
			sys.modules, {"one_fm": fake_root, "one_fm.utils": fake_utils}
		)
		return patcher, fake_utils.send_push_notification

	def test_push_no_recipients_is_noop(self):
		inst = make_instance()
		cfg = {"pushTitle": "T", "pushMessage": "M"}
		# No recipients resolved -> logs and returns
		call_dispatch_push(inst, FakeTask(), cfg, "task_1")

	def test_push_recipient_without_employee_is_noop(self):
		inst = make_instance()
		cfg = {"pushToUsers": "nobody@x.com", "pushTitle": "T", "pushMessage": "M"}
		# No Employee linked -> "no employees resolved", returns
		with patch.object(frappe.db, "get_value", return_value=None):
			call_dispatch_push(inst, FakeTask(), cfg, "task_1")

	def test_push_sends_to_resolved_employee(self):
		inst = make_instance(name="TEST-PI-PUSH")
		cfg = {
			"pushToUsers": "u1@x.com",
			"pushTitle": "Hi {{ instance.name }}",
			"pushMessage": "Msg",
		}

		patcher, send = self._inject_one_fm_utils()
		with patcher, patch.object(frappe.db, "get_value", return_value="EMP-1"):
			call_dispatch_push(inst, FakeTask(), cfg, "task_1")

		send.assert_called_once_with("EMP-1", "Hi TEST-PI-PUSH", "Msg")


# ──────────────────────────────────────────────────────────────────────────────
# Assignment resolution
# ──────────────────────────────────────────────────────────────────────────────
class TestGetReliever(BaseBPMNHelperTest):
	def test_empty_user_returns_empty(self):
		self.assertEqual(call_get_reliever(""), "")

	def test_no_employee_returns_original_user(self):
		with patch.object(frappe.db, "get_value", return_value=None):
			self.assertEqual(call_get_reliever("alice@x.com"), "alice@x.com")

	def test_on_leave_returns_reliever(self):
		# First get_value -> Employee name; second -> reliever_user_id
		with patch.object(
			frappe.db, "get_value", side_effect=["EMP-1", "bob@x.com"]
		):
			self.assertEqual(call_get_reliever("alice@x.com"), "bob@x.com")


class TestResolveAssignment(BaseBPMNHelperTest):
	def test_user_mode(self):
		inst = make_instance(
			user_task_extensions={
				"task_1": {"assigneeMode": "User", "assigneeUser": "alice@x.com"}
			}
		)
		# Employee lookup inside reliever check -> None -> user unchanged
		with patch.object(frappe.db, "get_value", return_value=None):
			self.assertEqual(call_resolve_assignment(inst, FakeTask("task_1")), "alice@x.com")

	def test_docfield_mode(self):
		inst = make_instance(
			context_docname="DOC-1",
			user_task_extensions={
				"task_1": {
					"assigneeMode": "DocField",
					"targetDoctype": "ToDo",
					"assigneeDocfield": "owner",
				}
			},
		)

		def gv(doctype, *a, **k):
			if doctype == "Employee":
				return None  # reliever check -> user unchanged
			return "bob@x.com"  # docfield read

		with patch.object(frappe.db, "get_value", side_effect=gv):
			self.assertEqual(call_resolve_assignment(inst, FakeTask("task_1")), "bob@x.com")

	def test_round_robin_picks_first_then_advances(self):
		inst = make_instance(
			process_model="PM-1",
			user_task_extensions={
				"task_1": {
					"assigneeMode": "Round Robin",
					"assigneeUsers": "a@x.com, b@x.com",
				}
			},
		)
		model = frappe._dict(round_robin_state="{}")
		model.save = Mock()

		with patch.object(frappe, "get_doc", return_value=model), patch.object(
			frappe.db, "get_value", return_value=None
		):
			result = call_resolve_assignment(inst, FakeTask("task_1"))

		self.assertEqual(result, "a@x.com")
		# rotation state was persisted with next_idx advanced to 1
		state = json.loads(model.round_robin_state)
		self.assertEqual(state["task_1"]["next_idx"], 1)
		self.assertEqual(state["task_1"]["last_user"], "a@x.com")

	def test_load_balancing_picks_least_loaded(self):
		inst = make_instance(
			user_task_extensions={
				"task_1": {
					"assigneeMode": "Load Balancing",
					"assigneeUsers": "a@x.com, b@x.com",
				}
			}
		)

		def count(doctype, filters=None, *a, **k):
			return {"a@x.com": 3, "b@x.com": 1}[filters["assigned_user"]]

		with patch.object(bpmn_engine, "get_task_display_name", return_value="My Task"), patch.object(
			frappe.db, "count", side_effect=count
		), patch.object(frappe.db, "get_value", return_value=None):
			result = call_resolve_assignment(inst, FakeTask("task_1"))

		self.assertEqual(result, "b@x.com")

	def test_unknown_mode_returns_empty(self):
		inst = make_instance(user_task_extensions={"task_1": {"assigneeMode": ""}})
		self.assertEqual(call_resolve_assignment(inst, FakeTask("task_1")), "")


# ──────────────────────────────────────────────────────────────────────────────
# Frappe assignment (ToDo) management
# ──────────────────────────────────────────────────────────────────────────────
class TestFrappeAssignment(BaseBPMNHelperTest):
	def test_add_assignment_calls_assign_to_add(self):
		inst = make_instance(context_doctype="ToDo", context_docname="DOC-1")
		with patch("frappe.desk.form.assign_to.add") as add_mock, patch.object(
			frappe.db, "exists", return_value=None
		), patch.object(
			frappe.db, "get_value", return_value="TODO-NEW-001"
		), patch.object(
			frappe.db, "set_value"
		) as set_value_mock:
			call_add_assignment(inst, "alice@x.com", "Approve")

		self.assertTrue(add_mock.called)
		payload = add_mock.call_args.args[0]
		self.assertEqual(payload["doctype"], "ToDo")
		self.assertEqual(payload["name"], "DOC-1")
		self.assertEqual(payload["assign_to"], ["alice@x.com"])

		# Verify the ToDo is stamped with type "Process"
		set_value_mock.assert_called_once_with("ToDo", "TODO-NEW-001", "type", "Process")

	def test_add_assignment_skips_when_already_assigned(self):
		inst = make_instance(context_doctype="ToDo", context_docname="DOC-1")
		with patch("frappe.desk.form.assign_to.add") as add_mock, patch.object(
			frappe.db, "exists", return_value="TODO-EXISTING"
		):
			call_add_assignment(inst, "alice@x.com", "Approve")

		self.assertFalse(add_mock.called)

	def test_add_assignment_skips_without_context(self):
		inst = make_instance(context_doctype=None, context_docname=None)
		with patch("frappe.desk.form.assign_to.add") as add_mock:
			call_add_assignment(inst, "alice@x.com")

		self.assertFalse(add_mock.called)

	def test_remove_assignment_sets_status_closed(self):
		inst = make_instance(context_doctype="ToDo", context_docname="DOC-1")
		with patch("frappe.desk.form.assign_to.set_status") as set_status_mock:
			call_remove_assignment(inst, "alice@x.com")

		self.assertTrue(set_status_mock.called)
		kwargs = set_status_mock.call_args.kwargs
		self.assertEqual(kwargs["assign_to"], "alice@x.com")
		self.assertEqual(kwargs["status"], "Closed")


# ──────────────────────────────────────────────────────────────────────────────
# Assignee notification email
# ──────────────────────────────────────────────────────────────────────────────
class TestAssigneeNotification(BaseBPMNHelperTest):
	def _patched_sendemail(self):
		"""
		Inject a fake one_fm.processor.sendemail so the test is deterministic
		regardless of whether one_fm is installed.
		"""
		fake_proc = types.ModuleType("one_fm.processor")
		fake_proc.sendemail = Mock()
		fake_root = sys.modules.get("one_fm") or types.ModuleType("one_fm")
		patcher = patch.dict(
			sys.modules, {"one_fm": fake_root, "one_fm.processor": fake_proc}
		)
		return patcher, fake_proc.sendemail

	def test_notification_sends_rendered_html_email(self):
		"""When notifyAssignee=true and notifyAssigneeBody has Jinja, send rendered email."""
		inst = make_instance(name="TEST-PI-NOTIFY", context_doctype="ToDo")
		cfg = {
			"notifyAssignee": "true",
			"notifyAssigneeBody": "<p>Hello from {{ instance.name }}</p>",
		}

		patcher, sendemail = self._patched_sendemail()
		with patcher:
			call_send_assignee_notification(inst, "alice@x.com", "Review Task", cfg)

		self.assertTrue(sendemail.called)
		kwargs = sendemail.call_args.kwargs
		self.assertEqual(kwargs["recipients"], ["alice@x.com"])
		self.assertIn("TEST-PI-NOTIFY", kwargs["message"])
		self.assertIn("<p>Hello from", kwargs["message"])

	def test_notification_not_sent_when_body_empty(self):
		"""When notifyAssigneeBody is empty, no email should be sent."""
		inst = make_instance(name="TEST-PI-EMPTY")
		cfg = {
			"notifyAssignee": "true",
			"notifyAssigneeBody": "",
		}

		patcher, sendemail = self._patched_sendemail()
		with patcher:
			call_send_assignee_notification(inst, "alice@x.com", "Review Task", cfg)

		self.assertFalse(sendemail.called)

	def test_notification_not_sent_when_flag_unchecked(self):
		"""When notifyAssignee is not 'true', the notification helper should be a no-op."""
		inst = make_instance(name="TEST-PI-OFF")
		cfg = {
			"notifyAssigneeBody": "<p>Should not send</p>",
		}

		# _send_assignee_notification checks for body but NOT the flag —
		# the flag check is in add_frappe_assignment.  But if the flag is
		# unchecked, add_frappe_assignment never calls the helper.  We test
		# that flow via a full add_frappe_assignment call.
		patcher, sendemail = self._patched_sendemail()
		inst_with_ctx = make_instance(
			name="TEST-PI-OFF",
			context_doctype="ToDo",
			context_docname="DOC-1",
		)
		with patcher, patch("frappe.desk.form.assign_to.add") as add_mock, \
			patch.object(frappe.db, "exists", return_value=None), \
			patch.object(frappe.db, "get_value", return_value="TODO-NEW"), \
			patch.object(frappe.db, "set_value"):
			call_add_assignment(inst_with_ctx, "alice@x.com", "Review Task", task_cfg=cfg)

		# assign_add was called (ToDo created) but no email sent
		self.assertTrue(add_mock.called)
		self.assertFalse(sendemail.called)

	def test_add_assignment_sends_notification_when_configured(self):
		"""Full flow: add_frappe_assignment triggers email when notifyAssignee=true."""
		cfg = {
			"notifyAssignee": "true",
			"notifyAssigneeBody": "<p>You have a task on {{ instance.name }}</p>",
		}

		patcher, sendemail = self._patched_sendemail()
		inst = make_instance(
			name="TEST-PI-FULL",
			context_doctype="ToDo",
			context_docname="DOC-1",
		)
		with patcher, patch("frappe.desk.form.assign_to.add") as add_mock, \
			patch.object(frappe.db, "exists", return_value=None), \
			patch.object(frappe.db, "get_value", return_value="TODO-NEW"), \
			patch.object(frappe.db, "set_value"):
			call_add_assignment(inst, "bob@x.com", "Approve PR", task_cfg=cfg)

		# ToDo was created
		self.assertTrue(add_mock.called)
		# Notification email was sent
		self.assertTrue(sendemail.called)
		kwargs = sendemail.call_args.kwargs
		self.assertEqual(kwargs["recipients"], ["bob@x.com"])
		self.assertIn("TEST-PI-FULL", kwargs["message"])
