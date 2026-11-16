# Copyright (c) 2026, ONE FM and contributors
# For license information, please see license.txt

"""Mobile push through the Firebase Cloud Messaging HTTP v1 API, configured on Processa Settings."""

import frappe
import requests
from frappe import _
from frappe.utils import cstr

from processa.processa_engine.dispatch.common import split_config

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
FCM_URL = "https://fcm.googleapis.com/v1/projects/{}/messages:send"


@frappe.whitelist(methods=["POST"])
def send_test_push() -> dict:
	"""Send a test push to the current user's devices."""
	frappe.has_permission("Processa Settings", "write", throw=True)
	tokens = tokens_for(frappe.session.user)
	if not tokens:
		frappe.throw(_("No device token found for {0}.").format(frappe.session.user))
	sender = FcmSender()
	reasons = [
		sender.send(token, _("Processa test push"), _("Push notifications work."), {}) for token in tokens
	]
	failed = [reason for reason in reasons if reason]
	if failed:
		frappe.throw(_("Firebase refused the push: {0}").format("; ".join(failed)))
	return {"sent": len(tokens)}


class FcmSender:
	"""One OAuth token for the Firebase project, reused for every message of a dispatch."""

	def __init__(self):
		from google.auth.transport.requests import Request
		from google.oauth2 import service_account

		key = frappe.get_cached_doc("Processa Settings").get_password(
			"push_service_account_json", raise_exception=False
		)
		if not key:
			frappe.throw(
				_("Set the Firebase Service Account JSON on Processa Settings to send push notifications.")
			)
		info = frappe.parse_json(key)
		credentials = service_account.Credentials.from_service_account_info(info, scopes=[FCM_SCOPE])
		credentials.refresh(Request())
		self.url = FCM_URL.format(info["project_id"])
		self.headers = {"Authorization": f"Bearer {credentials.token}"}

	def send(self, token: str, title: str, body: str, data: dict) -> str:
		"""Send one message. Returns Firebase's reason when it refuses, empty when sent."""
		message = {
			"token": token,
			"notification": {"title": title, "body": body},
			"data": {key: cstr(value) for key, value in data.items()},
		}
		response = requests.post(self.url, json={"message": message}, headers=self.headers, timeout=10)
		if response.ok:
			return ""
		try:
			return response.json()["error"]["message"]
		except (ValueError, KeyError, TypeError):
			return f"HTTP {response.status_code}: {response.text[:200]}"


def tokens_for(user: str) -> list[str]:
	"""Device tokens for a user, read from the token source named on Processa Settings."""
	settings = frappe.get_cached_doc("Processa Settings")
	if not settings.push_token_doctype:
		return []
	tokens = frappe.get_all(
		settings.push_token_doctype,
		filters={settings.push_token_user_field: user, settings.push_token_field: ["is", "set"]},
		pluck=settings.push_token_field,
	)
	return list(dict.fromkeys(tokens))


def users_in(doc, path: str) -> list[str]:
	"""Users named by a field of doc; "field.user_field" follows a Link to that record's user field."""
	fieldname, _sep, user_field = path.strip().partition(".")
	value = doc.get(fieldname)
	if not value:
		return []
	if user_field:
		df = doc.meta.get_field(fieldname)
		if not df or df.fieldtype != "Link":
			return []
		value = frappe.db.get_value(df.options, value, user_field)
	return users_from(value)


def users_from(value) -> list[str]:
	"""Users for a comma-separated value of user ids or email addresses."""
	users = []
	for part in split_config(value):
		user = part if frappe.db.exists("User", part) else frappe.db.get_value("User", {"email": part})
		if user:
			users.append(user)
	return users
