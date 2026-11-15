# Copyright (c) 2026, one-fm and contributors
"""Server steps of the executable DSS signing processes, called from their Server Script tasks."""

import base64
import json

import frappe
from frappe import _

REASON_TTL_SECONDS = 600
SIGNING_MAX_ATTEMPTS = 6


def signer_outcome(user: str) -> str:
	"""skip, no_employee, no_civil_id, no_email or ok: what DSS signing needs from this user."""
	if not frappe.get_single("Bumblebee Settings").dss_general_activation:
		return "skip"

	employee = frappe.db.get_value(
		"Employee",
		{"user_id": user},
		["employment_type", "one_fm_civil_id", "under_company_residency", "personal_email"],
		as_dict=True,
	)
	if not employee:
		return "no_employee"

	allowed = frappe.get_all(
		"Allowed Employment Type", filters={"parent": "Bumblebee Settings"}, pluck="employment_type"
	)
	if employee.employment_type not in allowed:
		return "skip"
	if not employee.one_fm_civil_id:
		return "no_civil_id"
	if not employee.personal_email:
		return "no_email"
	if not employee.under_company_residency:
		return "skip"
	return "ok"


def set_reason(instance_name: str, reason: str) -> None:
	frappe.cache.set_value(f"dss_reason:{instance_name}", reason, expires_in_sec=REASON_TTL_SECONDS)


def get_reason(instance_name: str) -> str:
	return frappe.cache.get_value(f"dss_reason:{instance_name}") or ""


def check_signer(user: str, instance_name: str) -> dict:
	"""Pre-check step: record why a signer cannot sign, and return the outcome for the gateway."""
	outcome = signer_outcome(user)
	reasons = {
		"no_employee": _("Employee record not found for session user. Please contact your HR department."),
		"no_civil_id": _(
			"Employee does not have a civil ID in their employee record. Please contact your HR department."
		),
		"no_email": _(
			"Employee does not have a personal email address in their employee record. "
			"Please contact your HR department."
		),
	}
	if outcome in reasons:
		set_reason(instance_name, reasons[outcome])
	return {"outcome": outcome, "level_outcome": ""}


def check_mobile_id(user: str, instance_name: str) -> dict:
	"""Pre-check step: the signer's Mobile ID verification level must be High."""
	from bumblebee.api.v1.gcpnext.digital_signature import check_verification_level

	civil_id = frappe.db.get_value("Employee", {"user_id": user}, "one_fm_civil_id")
	response = check_verification_level(civil_id)
	if response["status_code"] != 200:
		set_reason(
			instance_name,
			_("A problem occurred while retrieving your verification level. Please try again."),
		)
		return {"level_outcome": "level_error"}
	if response["verification_level"] != "High":
		set_reason(
			instance_name,
			_("Your Mobile ID verification level is {0}. High is required. Please upgrade it and try again.").format(
				response["verification_level"]
			),
		)
		return {"level_outcome": "level_low"}
	return {"level_outcome": "ok"}


def request_signature(doc, instance_name: str) -> dict:
	"""Signing step: send the previously signed document, or a fresh print, to DSS for signature."""
	from bumblebee.api.v1.gcpnext import digital_signature as dss
	from bumblebee.api.v1.gcpnext.digital_signature_log import search_dss_response_log

	previous = search_dss_response_log(doc.name, doc.doctype)
	if previous["title"] == "Success":
		document_base64 = previous["document_base64"]
	elif previous["title"] == "Failed":
		set_reason(instance_name, _("Could not retrieve previously signed document. Please try again."))
		return {"request_ok": False, "signed": False}
	else:
		document_base64 = base64.b64encode(frappe.get_print(doc.doctype, doc.name, as_pdf=True)).decode()

	frappe.form_dict["doc"] = json.dumps({"doctype": doc.doctype, "name": doc.name})
	response = dss.initiate_signing_request(document_base64)
	request_ok = response.get("status_code") == 200
	if not request_ok:
		set_reason(instance_name, _("The signing request could not be sent. Please try again."))
	return {
		"request_id": response.get("request_id") or "",
		"request_ok": request_ok,
		"attempts": 0,
		"signed": False,
	}


def check_signature(request_id: str, attempts: int, instance_name: str) -> dict:
	"""Signing step: whether the signed document is ready, counting this check."""
	from bumblebee.api.v1.gcpnext.digital_signature import download_signed_document

	response = download_signed_document(request_id)
	signed = response.get("status_code") == 200
	attempts += 1
	if not signed and attempts >= SIGNING_MAX_ATTEMPTS:
		set_reason(instance_name, _("The signing request timed out. Please try again."))
	return {"signed": signed, "attempts": attempts}


def log_signature(doc, request_id: str, action: str) -> None:
	"""Signing step: write the DSS Response Log the other DSS features read."""
	settings = frappe.get_single("Bumblebee Settings")
	frappe.get_doc(
		{
			"doctype": "DSS Response Log",
			"signature_id": request_id,
			"status": "Success",
			"reference_doctype": doc.doctype,
			"reference_docname": doc.name,
			"requester": frappe.session.user,
			"workflow_state": doc.get("workflow_state") or "",
			"workflow_action": action,
			"tsa_certificate_issuance_date": settings.tsa_issue_date,
			"tsa_certificate_expiry_date": settings.tsa_expiry_date,
		}
	).insert()
