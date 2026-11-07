# Copyright (c) 2026, one-fm and contributors
"""Service Task serviceType="send_email": an email to the people the task names."""

import frappe

from one_bpmn.processa_engine.dispatch.common import split_config, template_renderer


def dispatch_email(instance, task, task_cfg: dict, amp_html: str = None) -> None:
	"""Email the union of emailTo, emailToDocFields, emailToTableField rows and emailToRoles members.

	Subject and body are Jinja over {doc, instance, frappe}; doc is loaded from emailDoctype when set, else the context doctype.
	"""
	render, jinja_ctx = template_renderer(
		instance, "BPMN send_email: template render failed", doctype=task_cfg.get("emailDoctype")
	)
	doc = jinja_ctx["doc"]

	recipients = split_config(task_cfg.get("emailTo"))

	if doc:
		for field_name in split_config(task_cfg.get("emailToDocFields")):
			recipients += _emails_from_doc_field(doc.get(field_name))

	table_field = (task_cfg.get("emailToTableField") or "").strip()
	if table_field and doc:
		row_field = (task_cfg.get("emailToTableUserField") or "").strip() or "user"
		for row in doc.get(table_field) or []:
			recipients += _emails_from_doc_field(row.get(row_field))

	for role_name in split_config(task_cfg.get("emailToRoles")):
		user_roles = frappe.get_all(
			"Has Role",
			filters={"role": role_name, "parenttype": "User"},
			fields=["parent"],
		)
		for ur in user_roles:
			user_email = frappe.db.get_value("User", ur.parent, "email")
			if user_email and "@" in user_email:
				recipients.append(user_email)

	recipients = list(dict.fromkeys(recipients))

	if not recipients:
		frappe.log_error(
			title="BPMN send_email: No recipients resolved",
			message=(
				f"Service Task {task_cfg} on instance {instance.name} produced "
				f"no recipient email addresses. Email will not be sent."
			),
		)
		return

	cc = task_cfg.get("emailCc", "") or None
	bcc = split_config(task_cfg.get("emailBcc")) or None

	from one_bpmn.email_builder.composer import compose_notice, sends_notice

	if sends_notice(task_cfg):
		subject, body, amp_html = compose_notice(instance, task_cfg, doc, render)
	else:
		subject = render(task_cfg.get("emailSubject", "") or f"Notification from {instance.name}")
		raw_body = task_cfg.get("emailBody", "") or subject
		from one_bpmn.processa_engine.doctype.bpmn_process_instance.assignment import _decode_html_attr

		body = render(_decode_html_attr(raw_body))

		if not amp_html:
			try:
				from one_bpmn.email_builder.composer import compose_and_send_info_email

				amp_html = compose_and_send_info_email(instance, task_cfg, subject, body)
			except Exception:
				frappe.log_error(title="BPMN send_email: AMP card failed, sending plain HTML", message=frappe.get_traceback())
				amp_html = None

	from one_bpmn.email_builder.composer import _send_email

	_send_email(
		recipients=recipients,
		subject=subject,
		html_body=body,
		amp_html=amp_html or "",
		sender_account=task_cfg.get("emailAccount", ""),
		reference_doctype=instance.context_doctype or instance.doctype,
		reference_name=instance.context_docname or instance.name,
		cc=cc,
		bcc=bcc,
	)


def _emails_from_doc_field(val) -> list:
	"""Email addresses for one recipient field: each comma-separated part is an address or a user id looked up on User."""
	if not val:
		return []

	found = []
	for part in split_config(val):
		if "@" in part:
			found.append(part)
			continue
		email = frappe.db.get_value("User", part, "email")
		if email and "@" in email:
			found.append(email)
	return found
