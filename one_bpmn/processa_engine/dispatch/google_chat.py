# Copyright (c) 2026, one-fm and contributors
"""Service Task serviceType="google_chat": a direct message or a space post through the Chat API."""

import concurrent.futures
import json

import frappe
import requests

from one_bpmn.processa_engine.dispatch.common import split_config, template_renderer

CHAT_SCOPES = ["https://www.googleapis.com/auth/chat.bot"]


def dispatch_google_chat(instance, task, task_cfg: dict, bpmn_id: str) -> None:
	"""Send gchatMessage (Jinja) to a space (gchatSpaceId) or to people (gchatType="individual").

	Credentials come from Processa Settings. Failures are logged and the workflow continues.
	"""
	gchat_type = task_cfg.get("gchatType", "").strip()
	gchat_space_id = (task_cfg.get("gchatSpaceId") or "").strip()
	raw_message = (task_cfg.get("gchatMessage") or "").strip()

	if gchat_type not in ("individual", "space"):
		frappe.log_error(
			title=f"BPMN ServiceTask: google_chat misconfigured ({bpmn_id})",
			message=(
				f"gchatType={gchat_type!r} is not a valid destination type. "
				f"Expected 'individual' or 'space'."
			),
		)
		return

	if not raw_message:
		frappe.log_error(
			title=f"BPMN ServiceTask: google_chat misconfigured ({bpmn_id})",
			message="gchatMessage is empty.",
		)
		return

	recipients = []
	if gchat_type == "individual":
		recipients, problem = google_chat_recipients(instance, task_cfg)
		if problem or not recipients:
			frappe.log_error(
				title=f"BPMN ServiceTask: google_chat has no recipient ({bpmn_id})",
				message=problem or "No recipient resolved.",
			)
			return

	if gchat_type == "space" and not gchat_space_id:
		frappe.log_error(
			title=f"BPMN ServiceTask: google_chat misconfigured ({bpmn_id})",
			message="gchatType=space but gchatSpaceId is empty.",
		)
		return

	if "{{" in raw_message or "{%" in raw_message:
		title = f"BPMN ServiceTask: google_chat Jinja render failed ({bpmn_id})"
		try:
			render, _ = template_renderer(instance, title, strict=True)
			raw_message = render(raw_message)
		except Exception:
			frappe.log_error(title=title, message=frappe.get_traceback())

	sa_json = frappe.get_cached_doc("Processa Settings").get_password(
		"google_chat_service_account_json", raise_exception=False
	)
	if not sa_json:
		frappe.log_error(
			title=f"BPMN ServiceTask: google_chat credentials missing ({bpmn_id})",
			message="Processa Settings > Google Chat > Service Account JSON is empty.",
		)
		return

	try:
		from google.auth.transport.requests import Request as GoogleRequest
		from google.oauth2 import service_account

		sa_info = json.loads(sa_json)
		credentials = service_account.Credentials.from_service_account_info(sa_info, scopes=CHAT_SCOPES)
		credentials.refresh(GoogleRequest())
		access_token = credentials.token

		headers = {
			"Authorization": f"Bearer {access_token}",
			"Content-Type": "application/json",
		}
		payload = {"text": raw_message}

		if gchat_type == "individual":
			# Each recipient is sent and logged on its own so one failure does not silence the rest.
			for address in recipients:
				try:
					user_id = chat_user_id(address, headers) if "@" in address else address
					if not user_id:
						raise ValueError(
							"No single Google Chat user answers to this address. Either they "
							"have never been sent the app, or two people share their name."
						)
					dm_resp = requests.get(
						"https://chat.googleapis.com/v1/spaces:findDirectMessage",
						headers=headers,
						params={"name": f"users/{user_id}"},
						timeout=10,
					)
					if dm_resp.status_code == 200:
						space_name = dm_resp.json().get("name", "")
					else:
						setup_resp = requests.post(
							"https://chat.googleapis.com/v1/spaces:setup",
							headers=headers,
							json={
								"space": {"spaceType": "DIRECT_MESSAGE"},
								"memberships": [
									{"member": {"name": f"users/{address}", "type": "HUMAN"}}
								],
							},
							timeout=10,
						)
						setup_resp.raise_for_status()
						space_name = setup_resp.json().get("name", "")

					resp = requests.post(
						f"https://chat.googleapis.com/v1/{space_name}/messages",
						headers=headers, json=payload, timeout=10,
					)
					resp.raise_for_status()
				except Exception:
					frappe.log_error(
						title=f"BPMN ServiceTask: google_chat DM failed for {address} ({bpmn_id})",
						message=frappe.get_traceback(),
					)
		else:
			space_name = gchat_space_id.strip().rstrip("/")
			resp = requests.post(
				f"https://chat.googleapis.com/v1/{space_name}/messages",
				headers=headers, json=payload, timeout=10,
			)
			resp.raise_for_status()

	except Exception:
		frappe.log_error(
			title=f"BPMN ServiceTask: google_chat API call failed ({bpmn_id})",
			message=frappe.get_traceback(),
		)


def google_chat_recipients(instance, task_cfg: dict) -> tuple:
	"""(addresses, problem) for a direct message named by gchatRecipientBasis: User, DocField or Table Field.

	The document is always the instance's context; problem is a sentence for the log, empty when nothing is wrong.
	"""
	basis = (task_cfg.get("gchatRecipientBasis") or "User").strip()
	doctype = (task_cfg.get("gchatDoctype") or "").strip() or (instance.context_doctype or "")
	docname = instance.context_docname or ""

	if basis == "User":
		raw = (task_cfg.get("gchatEmail") or "").strip()
		if not raw:
			return [], "gchatRecipientBasis=User but gchatEmail is empty."
		return _addresses_for(split_config(raw)), ""

	if basis not in ("DocField", "Table Field"):
		return [], f"gchatRecipientBasis={basis!r} is not User, DocField or Table Field."

	if not (doctype and docname):
		return [], (
			f"gchatRecipientBasis={basis} needs a context document, and this instance has "
			f"doctype={doctype!r} docname={docname!r}."
		)

	try:
		doc = frappe.get_doc(doctype, docname)
	except Exception:
		return [], f"Could not read {doctype} {docname} to resolve the recipient."

	if basis == "DocField":
		field = (task_cfg.get("gchatDocField") or "").strip()
		if not field:
			return [], "gchatRecipientBasis=DocField but gchatDocField is empty."
		value = doc.get(field)
		if not value:
			return [], f"{doctype} {docname} has nothing in {field!r}."
		return _addresses_for([value]), ""

	table_field = (task_cfg.get("gchatTableField") or "").strip()
	row_field = (task_cfg.get("gchatTableUserField") or "").strip() or "user"
	if not table_field:
		return [], "gchatRecipientBasis=Table Field but gchatTableField is empty."

	rows = doc.get(table_field) or []
	if not rows:
		return [], f"{doctype} {docname} has no rows in {table_field!r}."
	addresses = _addresses_for([row.get(row_field) for row in rows])
	if not addresses:
		return [], f"No row of {table_field!r} names a user in {row_field!r}."
	return addresses, ""


def _addresses_for(values) -> list:
	"""Each user id or plain address as an email address, in order and without duplicates."""
	addresses, seen = [], set()
	for raw in values:
		value = str(raw or "").strip()
		if not value:
			continue
		address = frappe.db.get_value("User", value, "email") or value
		if address not in seen:
			seen.add(address)
			addresses.append(address)
	return addresses


def chat_user_id(email: str, headers: dict) -> str:
	"""The Google Chat id behind an address, or "" when it cannot be settled; Chat refuses emails under app auth."""
	key = f"gchat_user_id::{email.lower()}"
	cached = frappe.cache().get_value(key)
	if cached:
		return cached

	user_id = _directory_user_id(email) or _named_user_id(email, headers)
	if user_id:
		# No expiry: an id outlives any useful TTL.
		frappe.cache().set_value(key, user_id)
	return user_id


def _directory_user_id(email: str) -> str:
	"""Ask the Workspace directory, which answers by email and is exact."""
	settings = frappe.get_cached_doc("Processa Settings")
	subject = (settings.google_directory_account or "").strip()
	sa_json = settings.get_password("google_chat_service_account_json", raise_exception=False)
	if not (subject and sa_json):
		return ""

	from google.auth.transport.requests import Request as GoogleRequest
	from google.oauth2 import service_account

	try:
		credentials = service_account.Credentials.from_service_account_info(
			json.loads(sa_json),
			scopes=["https://www.googleapis.com/auth/admin.directory.user.readonly"],
			subject=subject,
		)
		credentials.refresh(GoogleRequest())
		resp = requests.get(
			f"https://admin.googleapis.com/admin/directory/v1/users/{email}",
			headers={"Authorization": f"Bearer {credentials.token}"},
			params={"viewType": "domain_public"},
			timeout=15,
		)
	except Exception:
		frappe.log_error(
			title="google_chat: directory lookup failed",
			message=frappe.get_traceback(),
		)
		return ""

	if resp.status_code == 200:
		return resp.json().get("id") or ""
	# 404 means the address has no Google account, which is an answer rather than a fault.
	if resp.status_code != 404:
		frappe.log_error(
			title="google_chat: directory lookup refused",
			message=f"{resp.status_code} for {email}: {resp.text[:500]}",
		)
	return ""


def _named_user_id(email: str, headers: dict) -> str:
	"""Match the user's Frappe full name against the direct messages the app is in; two holders means no answer."""
	full_name = frappe.db.get_value("User", email, "full_name")
	if not full_name:
		return ""
	holders = _chat_dm_directory(headers).get(_same_name(full_name)) or []
	return holders[0] if len(holders) == 1 else ""


def _chat_dm_directory(headers: dict) -> dict:
	"""Display name (lowercased) to the Chat ids answering to it."""
	spaces, page = [], None
	while True:
		params = {"pageSize": 1000}
		if page:
			params["pageToken"] = page
		body = requests.get(
			"https://chat.googleapis.com/v1/spaces", headers=headers, params=params, timeout=20
		).json()
		spaces += [
			s["name"] for s in body.get("spaces", []) if s.get("spaceType") == "DIRECT_MESSAGE"
		]
		page = body.get("nextPageToken")
		if not page:
			break

	def members(space):
		resp = requests.get(
			f"https://chat.googleapis.com/v1/{space}/members", headers=headers, timeout=20
		)
		return resp.json().get("memberships", []) if resp.status_code == 200 else []

	# One request per person in the domain, so they run in parallel.
	with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
		batches = list(pool.map(members, spaces))

	directory = {}
	for batch in batches:
		for membership in batch:
			member = membership.get("member", {})
			name = _same_name(member.get("displayName"))
			if member.get("type") == "HUMAN" and name:
				directory.setdefault(name, []).append(member["name"].split("/")[-1])
	return directory


def _same_name(name: str) -> str:
	"""A name with whitespace collapsed and lowercased; Frappe's full_name can carry a double space."""
	return " ".join((name or "").split()).lower()
