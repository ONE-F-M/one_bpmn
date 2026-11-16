from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import UnitTestCase

from processa.api import editability

METHOD = "processa.api.editability.check_implementations_editable"


def _response(status, text="", message=None):
	resp = MagicMock(status_code=status, text=text)
	resp.json.return_value = {"message": message}
	resp.raise_for_status.side_effect = None if status == 200 else Exception(f"{status} Client Error")
	return resp


class TestProductionFallback(UnitTestCase):
	def setUp(self):
		creds = patch.object(editability, "_production_creds", return_value=("https://prod.example", "k", "s"))
		creds.start()
		self.addCleanup(creds.stop)

	def test_production_on_one_bpmn_is_asked_by_its_old_path(self):
		refused = _response(417, "Failed to get method for command x with App processa is not installed")
		with patch("requests.post", side_effect=[refused, _response(200, message={"PI-1": True})]) as post:
			result = editability._call_production_api(METHOD, {"pi_names": "[]"})

		self.assertEqual(result, {"PI-1": True})
		self.assertEqual(
			post.call_args_list[1].args[0],
			"https://prod.example/api/method/one_bpmn.api.editability.check_implementations_editable",
		)

	def test_production_on_processa_is_asked_once(self):
		with patch("requests.post", return_value=_response(200, message={"PI-1": False})) as post:
			result = editability._call_production_api(METHOD, {"pi_names": "[]"})

		self.assertEqual(result, {"PI-1": False})
		self.assertEqual(post.call_count, 1)

	def test_any_other_refusal_is_not_retried(self):
		with patch("requests.post", return_value=_response(417, "Insufficient Permission")) as post:
			with self.assertRaises(frappe.ValidationError):
				editability._call_production_api(METHOD, {"pi_names": "[]"})

		self.assertEqual(post.call_count, 1)
