# Copyright (c) 2026, one-fm and contributors
"""Service Task serviceType="push_notification": a mobile push through Firebase."""

import frappe
import requests
from frappe import _
from frappe.utils import get_url_to_form, sbool

from one_bpmn.processa_engine.dispatch.common import split_config, template_renderer


def dispatch_push_notification(instance, task, task_cfg: dict, bpmn_id: str) -> None:
	"""Push pushTitle / pushMessage to the union of pushToUsers, pushToRoles, pushToDocFields and pushToTableField rows.

	Counts land in task.data["<bpmn_id>_push"].
	"""
	from one_bpmn.one_bpmn.push_notification import FcmSender, tokens_for

	render, jinja_ctx = template_renderer(
		instance, f"BPMN push_notification: template render failed ({bpmn_id})", strict=True
	)
	doc = jinja_ctx["doc"]

	users = push_recipients(doc, task_cfg)
	if not users:
		frappe.log_error(
			title=f"BPMN push_notification: No recipients resolved ({bpmn_id})",
			message=f"Service Task {task_cfg} on instance {instance.name} resolved no users.",
		)
		return

	default_title = _("Notification from {0}").format(instance.name)
	title = render(task_cfg.get("pushTitle")) or default_title
	body = render(task_cfg.get("pushMessage")) or title
	data = {"url": "/notification"}
	if sbool(task_cfg.get("pushLinkToDocument")) and doc.get("name"):
		data.update(doctype=doc.doctype, docname=doc.name, link=get_url_to_form(doc.doctype, doc.name))
	fall_back = sbool(task_cfg.get("pushFallbackInApp"))

	sender = None
	counts = {"sent": 0, "fell_back": 0, "failed": 0}
	failures = []
	for user in users:
		tokens = tokens_for(user)
		if not tokens:
			if fall_back:
				_push_in_app(user, title, body, doc)
				counts["fell_back"] += 1
			else:
				counts["failed"] += 1
				failures.append(f"{user}: no device token")
			continue
		sender = sender or FcmSender()
		reasons = [_push_one(sender, token, title, body, data) for token in tokens]
		if all(reasons):
			counts["failed"] += 1
			failures.append(f"{user}: {'; '.join(reasons)}")
		else:
			counts["sent"] += 1

	task.data[f"{bpmn_id}_push"] = counts
	if failures:
		frappe.log_error(
			title=f"BPMN push_notification: {counts['failed']} failed, {counts['sent']} sent ({bpmn_id})",
			message="\n".join(failures),
		)


def push_recipients(doc, task_cfg: dict) -> list:
	"""Users a push task names, in order and without duplicates."""
	from one_bpmn.one_bpmn.push_notification import users_from, users_in

	users = users_from(task_cfg.get("pushToUsers"))
	for role in split_config(task_cfg.get("pushToRoles")):
		users += frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent")
	if doc:
		for path in split_config(task_cfg.get("pushToDocFields")):
			users += users_in(doc, path)
		row_path = (task_cfg.get("pushToTableUserField") or "").strip() or "user"
		for row in doc.get((task_cfg.get("pushToTableField") or "").strip()) or []:
			users += users_in(row, row_path)
	return list(dict.fromkeys(users))


def _push_one(sender, token: str, title: str, body: str, data: dict) -> str:
	"""Send to one device; a network error counts as Firebase's reason."""
	try:
		return sender.send(token, title, body, data)
	except requests.RequestException as e:
		return str(e)


def _push_in_app(user: str, title: str, body: str, doc) -> None:
	"""Leave an in-app Notification Log for a user with no device."""
	from frappe.desk.doctype.notification_log.notification_log import make_notification_logs

	make_notification_logs(
		frappe._dict(
			type="Alert",
			subject=title,
			email_content=body,
			document_type=doc.get("doctype"),
			document_name=doc.get("name"),
		),
		[frappe.db.get_value("User", user, "email")],
	)
