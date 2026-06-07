# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

import json as _json

import frappe
from frappe import _


# ============================================
# Notification API
# Creates Notification documents from the BPMN Send Task dialog.
# New notifications are disabled by default (enabled when deployed).
# ============================================


@frappe.whitelist()
def create_notification(
	notification_name: str,
	channel: str,
	document_type: str,
	event: str = "New",
	subject: str = None,
	message: str = None,
	message_type: str = "Markdown",
	condition: str = None,
	module: str = None,
	# Email-specific
	sender: str = None,
	sender_email: str = None,
	attach_print: int = 0,
	print_format: str = None,
	send_system_notification: int = 0,
	# Slack-specific
	slack_webhook_url: str = None,
	# WhatsApp-specific  (Twilio integration)
	twilio_number: str = None,
	# Trigger fields
	method: str = None,
	date_changed: str = None,
	days_in_advance: int = 0,
	value_changed: str = None,
	# Recipients
	send_to_all_assignees: int = 0,
	recipients: str = None,  # JSON string of recipient rows
	# After Alert
	set_property_after_alert: str = None,
	property_value: str = None,
) -> dict:
	"""
	Create a Notification document from the BPMN Send Task dialog.

	The notification is created with enabled=0 (disabled by default).
	It should be enabled when the process is deployed.

	Args:
		notification_name: Human-readable name for the notification
		channel: Email / Slack / System Notification / SMS / WhatsApp
		document_type: The DocType this notification is linked to
		event: Trigger event (New/Save/Submit/Cancel/Days After/Days Before/Value Change/Method/Custom)
		subject: Notification subject line (Jinja template)
		message: Message body (Jinja template)
		message_type: Markdown / HTML / Plain Text
		condition: Python condition expression
		module: Module for export
		sender: Email Account link (Email channel)
		sender_email: Sender email address (Email channel)
		attach_print: Whether to attach print (Email channel)
		print_format: Print Format link (Email channel)
		send_system_notification: Also send system notification flag
		slack_webhook_url: Slack Webhook URL link (Slack channel)
		twilio_number: Communication Medium link (WhatsApp channel)
		method: Trigger method name (Method event)
		date_changed: Date field name (Days After/Before events)
		days_in_advance: Number of days (Days After/Before events)
		value_changed: Field name (Value Change event)
		send_to_all_assignees: Send to all document assignees
		recipients: JSON array of recipient row objects
		set_property_after_alert: Field to set after alert fires
		property_value: Value to set

	Returns:
		dict with name and channel
	"""
	if not notification_name or not channel or not document_type:
		frappe.throw(_("Notification name, channel, and document type are required"))

	if not frappe.has_permission("Notification", "create") and "System Manager" not in frappe.get_roles():
		frappe.throw(
			_("You need the System Manager role to create Notifications."),
			frappe.PermissionError,
		)

	doc = frappe.new_doc("Notification")
	doc.__newname = notification_name
	doc.subject = subject or notification_name
	doc.channel = channel
	doc.document_type = document_type
	doc.event = event or "New"
	doc.enabled = 0  # Disabled by default — enabled when deployed
	doc.message_type = message_type or "Markdown"

	if message:
		doc.message = message
	if condition:
		doc.condition = condition
	if module:
		doc.module = module

	# Email-specific fields
	if sender:
		doc.sender = sender
	if sender_email:
		doc.sender_email = sender_email
	if int(attach_print or 0):
		doc.attach_print = 1
	if print_format:
		doc.print_format = print_format
	if int(send_system_notification or 0):
		doc.send_system_notification = 1

	# Slack-specific
	if slack_webhook_url:
		doc.slack_webhook_url = slack_webhook_url

	# WhatsApp-specific (Twilio)
	if twilio_number:
		doc.twilio_number = twilio_number

	# Trigger fields
	if method:
		doc.method = method
	if date_changed:
		doc.date_changed = date_changed
	if days_in_advance:
		doc.days_in_advance = int(days_in_advance)
	if value_changed:
		doc.value_changed = value_changed

	# After Alert
	if set_property_after_alert:
		doc.set_property_after_alert = set_property_after_alert
	if property_value:
		doc.property_value = property_value

	# Recipients
	if int(send_to_all_assignees or 0):
		doc.send_to_all_assignees = 1

	if recipients:
		if isinstance(recipients, str):
			try:
				rows = _json.loads(recipients)
			except (ValueError, _json.JSONDecodeError):
				frappe.throw("Recipients must be a valid JSON array of objects.", frappe.ValidationError)
		else:
			rows = recipients

		if not isinstance(rows, list):
			frappe.throw("Recipients must be a list of objects.", frappe.ValidationError)

		for row in rows:
			if not isinstance(row, dict):
				frappe.throw("Each recipient entry must be an object.", frappe.ValidationError)
			doc.append(
				"recipients",
				{
					"receiver_by_document_field": row.get("receiver_by_document_field", ""),
					"receiver_by_role": row.get("receiver_by_role", ""),
					"cc": row.get("cc", ""),
					"bcc": row.get("bcc", ""),
					"condition": row.get("condition", ""),
				},
			)

	# Elevate to bypass permission checks in the Notification controller.
	# The role guard above already ensures only authorised users reach here.
	original_user = frappe.session.user
	try:
		frappe.set_user("Administrator")
		doc.insert(ignore_permissions=True)
	finally:
		frappe.set_user(original_user)

	return {"name": doc.name, "channel": doc.channel}
