"""send_message reports whether a waiting task took the message ("caught")."""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from one_bpmn.api.instance_api import send_message


def _fake_instance(caught):
	"""A stand-in BPMN Process Instance whose receive_message sets the flag."""
	instance = MagicMock()
	instance.status = "Active"
	instance.context_doctype = None
	instance.context_docname = None
	instance.flags = frappe._dict()
	instance.check_permission = MagicMock()

	def receive_message(message_name=None, payload=None):
		instance.flags.bpmn_message_caught = caught
		return [{"task": "Wait for PR"}]

	instance.receive_message = MagicMock(side_effect=receive_message)
	return instance


class TestSendMessageCaught(unittest.TestCase):
	def _send(self, caught):
		instance = _fake_instance(caught)
		with patch.object(frappe, "get_doc", return_value=instance), patch.object(
			frappe, "publish_realtime"
		):
			result = send_message(message_name="GitHub: PR Merged", instance_name="INST-1")
		instance.check_permission.assert_called_once_with("write")
		instance.receive_message.assert_called_once()
		return result

	def test_caught_true_when_flag_is_true(self):
		result = self._send(True)
		self.assertIn("caught", result)
		self.assertIs(result["caught"], True)

	def test_caught_false_when_flag_is_false(self):
		result = self._send(False)
		self.assertIn("caught", result)
		self.assertIs(result["caught"], False)

	def test_existing_keys_unchanged(self):
		result = self._send(True)
		self.assertEqual(result["instance"], "INST-1")
		self.assertEqual(result["status"], "Active")
		self.assertEqual(result["active_tasks"], [{"task": "Wait for PR"}])
