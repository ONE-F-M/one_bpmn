# Copyright (c) 2026, one-fm and contributors
"""The server steps of the executable DSS signing processes.

Run with:
    bench run-tests --app one_bpmn --module one_bpmn.tests.test_dss_signing
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api import dss_signing

def _only_for(real, doctype, result):
	"""Replace one doctype's lookup and leave every other call to the real function."""

	def fake(*args, **kwargs):
		name = args[0] if args else kwargs.get("doctype")
		return result if name == doctype else real(*args, **kwargs)

	return fake


def _employee(**overrides):
	row = {
		"employment_type": "Full-time",
		"one_fm_civil_id": "280000000001",
		"under_company_residency": 1,
		"personal_email": "signer@example.com",
	}
	row.update(overrides)
	return frappe._dict(row)


class TestSignerOutcome(FrappeTestCase):
	def _signer(self, activation=1, employee=None, allowed=("Full-time",)):
		settings = frappe._dict(dss_general_activation=activation)
		with (
			patch("frappe.get_single", _only_for(frappe.get_single, "Bumblebee Settings", settings)),
			patch("frappe.db.get_value", _only_for(frappe.db.get_value, "Employee", employee)),
			patch("frappe.get_all", _only_for(frappe.get_all, "Allowed Employment Type", list(allowed))),
		):
			return dss_signing.signer_outcome("signer@example.com")

	def test_dss_switched_off_skips_signing(self):
		self.assertEqual(self._signer(activation=0, employee=_employee()), "skip")

	def test_missing_employee_is_reported(self):
		self.assertEqual(self._signer(employee=None), "no_employee")

	def test_employment_type_outside_the_allowed_list_skips_signing(self):
		self.assertEqual(self._signer(employee=_employee(employment_type="Contractor")), "skip")

	def test_missing_civil_id_is_reported(self):
		self.assertEqual(self._signer(employee=_employee(one_fm_civil_id="")), "no_civil_id")

	def test_missing_personal_email_is_reported(self):
		self.assertEqual(self._signer(employee=_employee(personal_email="")), "no_email")

	def test_signer_outside_company_residency_skips_signing(self):
		self.assertEqual(self._signer(employee=_employee(under_company_residency=0)), "skip")

	def test_complete_record_is_eligible(self):
		self.assertEqual(self._signer(employee=_employee()), "ok")


class TestPreCheckSteps(FrappeTestCase):
	def tearDown(self):
		frappe.cache.delete_value("dss_reason:TEST-INST")

	def test_incomplete_record_records_the_reason(self):
		with patch.object(dss_signing, "signer_outcome", return_value="no_civil_id"):
			out = dss_signing.check_signer("signer@example.com", "TEST-INST")

		self.assertEqual(out, {"outcome": "no_civil_id", "level_outcome": ""})
		self.assertIn("civil ID", dss_signing.get_reason("TEST-INST"))

	def test_exempt_signer_records_no_reason(self):
		with patch.object(dss_signing, "signer_outcome", return_value="skip"):
			dss_signing.check_signer("signer@example.com", "TEST-INST")

		self.assertEqual(dss_signing.get_reason("TEST-INST"), "")

	def _mobile_id(self, response):
		with (
			patch("frappe.db.get_value", _only_for(frappe.db.get_value, "Employee", "280000000001")),
			patch("bumblebee.api.v1.gcpnext.digital_signature.check_verification_level", return_value=response),
		):
			return dss_signing.check_mobile_id("signer@example.com", "TEST-INST")

	def test_high_verification_level_passes(self):
		out = self._mobile_id({"status_code": 200, "verification_level": "High"})
		self.assertEqual(out, {"level_outcome": "ok"})

	def test_low_verification_level_is_refused_with_the_level_shown(self):
		out = self._mobile_id({"status_code": 200, "verification_level": "Low"})
		self.assertEqual(out, {"level_outcome": "level_low"})
		self.assertIn("Low", dss_signing.get_reason("TEST-INST"))

	def test_failed_lookup_is_reported(self):
		out = self._mobile_id({"status_code": 500})
		self.assertEqual(out, {"level_outcome": "level_error"})


class TestSigningSteps(FrappeTestCase):
	def setUp(self):
		self.doc = frappe._dict(doctype="ToDo", name="TODO-1")
		self.addCleanup(frappe.cache.delete_value, "dss_reason:TEST-INST")

	def _request(self, previous, init_status=200):
		with (
			patch("bumblebee.api.v1.gcpnext.digital_signature_log.search_dss_response_log", return_value=previous),
			patch(
				"bumblebee.api.v1.gcpnext.digital_signature.initiate_signing_request",
				return_value={"status_code": init_status, "request_id": "REQ-1"},
			) as initiate,
			patch.object(frappe, "get_print", return_value=b"%PDF-new"),
		):
			return dss_signing.request_signature(self.doc, "TEST-INST"), initiate

	def test_first_signature_sends_a_fresh_print(self):
		out, initiate = self._request({"title": "None"})

		self.assertTrue(out["request_ok"])
		self.assertEqual(out["request_id"], "REQ-1")
		self.assertEqual(initiate.call_args.args[0], "JVBERi1uZXc=")

	def test_later_signature_signs_the_previously_signed_document(self):
		_out, initiate = self._request({"title": "Success", "document_base64": "PREVIOUS"})
		self.assertEqual(initiate.call_args.args[0], "PREVIOUS")

	def test_unreadable_previous_document_stops_the_request(self):
		out, initiate = self._request({"title": "Failed"})

		self.assertEqual(out, {"request_ok": False, "signed": False})
		initiate.assert_not_called()
		self.assertIn("previously signed", dss_signing.get_reason("TEST-INST"))

	def test_refused_request_is_reported(self):
		out, _initiate = self._request({"title": "None"}, init_status=500)

		self.assertFalse(out["request_ok"])
		self.assertIn("could not be sent", dss_signing.get_reason("TEST-INST"))

	def test_check_counts_the_attempt_and_reports_signed(self):
		with patch(
			"bumblebee.api.v1.gcpnext.digital_signature.download_signed_document",
			return_value={"status_code": 200},
		):
			self.assertEqual(
				dss_signing.check_signature("REQ-1", 2, "TEST-INST"), {"signed": True, "attempts": 3}
			)

	def test_check_reports_unsigned_while_the_document_is_not_ready(self):
		with patch(
			"bumblebee.api.v1.gcpnext.digital_signature.download_signed_document",
			return_value={"status_code": 404},
		):
			out = dss_signing.check_signature("REQ-1", 0, "TEST-INST")

		self.assertEqual(out, {"signed": False, "attempts": 1})
		self.assertEqual(dss_signing.get_reason("TEST-INST"), "")

	def test_last_unsigned_check_records_a_timeout_reason(self):
		with patch(
			"bumblebee.api.v1.gcpnext.digital_signature.download_signed_document",
			return_value={"status_code": 404},
		):
			dss_signing.check_signature("REQ-1", dss_signing.SIGNING_MAX_ATTEMPTS - 1, "TEST-INST")

		self.assertIn("timed out", dss_signing.get_reason("TEST-INST"))

	def test_log_signature_writes_a_success_row_for_the_action(self):
		todo = frappe.get_doc(
			{"doctype": "ToDo", "description": "DSS log test", "allocated_to": "Administrator"}
		).insert()

		dss_signing.log_signature(todo, "REQ-LOG-1", "Sign Off")

		row = frappe.db.get_value(
			"DSS Response Log",
			{"signature_id": "REQ-LOG-1"},
			["status", "reference_docname", "workflow_action", "requester"],
			as_dict=True,
		)
		self.assertEqual(
			row,
			{
				"status": "Success",
				"reference_docname": todo.name,
				"workflow_action": "Sign Off",
				"requester": frappe.session.user,
			},
		)
