# Copyright (c) 2026, one-fm and contributors
# BPMN Process Instance — service task dispatch handlers
#
# These are standalone functions extracted from the BPMNProcessInstance
# controller.  Each receives the controller document as ``instance`` and reads
# only simple attributes from it (context_doctype, context_docname, name,
# initiated_by, doctype).  They are invoked from the controller's
# ``_dispatch_service_task`` router.

import frappe
import frappe.utils


def dispatch_update_field(instance, task, task_cfg: dict, bpmn_id: str) -> None:
	"""
	Update one or more fields on a document in a single service task.

	Reads ``updateFieldRows`` — a JSON array of ``{field, value}`` objects —
	and applies them in a single ``frappe.db.set_value`` call.  Every value
	is Jinja2-rendered before being written.

	Backward-compatible: if ``updateFieldRows`` is absent, falls back to the
	legacy single-field ``updateFieldName`` / ``updateFieldValue`` keys so
	existing diagrams continue to work unchanged.

	Service task configuration keys (from BPMN XML):
	    updateFieldDoctype  — DocType to update (falls back to context_doctype)
	    updateFieldRows     — JSON: [{"field": "status", "value": "Approved"}, ...]
	    updateFieldName     — (legacy) single field name
	    updateFieldValue    — (legacy) single field value
	"""
	import json as _json

	doctype = task_cfg.get("updateFieldDoctype") or instance.context_doctype
	docname = instance.context_docname

	if not (doctype and docname):
		frappe.log_error(
			title=f"BPMN ServiceTask: update_field misconfigured ({bpmn_id})",
			message=f"Task {bpmn_id} is missing doctype={doctype!r} or docname={docname!r}.",
		)
		return

	rows_json = task_cfg.get("updateFieldRows", "")
	if rows_json:
		try:
			rows = _json.loads(rows_json)
			if not isinstance(rows, list):
				frappe.log_error(
					title=f"BPMN ServiceTask: update_field misconfigured ({bpmn_id})",
					message=(
						f"updateFieldRows decoded to {type(rows).__name__}, expected list. "
						f"Raw value: {rows_json!r}"
					),
				)
				return
		except Exception:
			frappe.log_error(
				title=f"BPMN ServiceTask: update_field invalid JSON ({bpmn_id})",
				message=f"updateFieldRows is not valid JSON: {rows_json!r}",
			)
			return
	else:
		legacy_field = task_cfg.get("updateFieldName", "")
		legacy_value = task_cfg.get("updateFieldValue", "")
		if not legacy_field:
			frappe.log_error(
				title=f"BPMN ServiceTask: update_field misconfigured ({bpmn_id})",
				message=f"Task {bpmn_id} has no updateFieldRows and no updateFieldName.",
			)
			return
		rows = [{"field": legacy_field, "value": legacy_value}]

	if not rows:
		return

	try:
		doc = frappe.get_doc(doctype, docname)
	except Exception:
		frappe.log_error(
			title=f"BPMN ServiceTask: update_field doc load failed ({bpmn_id})",
			message=frappe.get_traceback(),
		)
		return

	updates = {}
	for row in rows:
		if not isinstance(row, dict):
			continue
		fieldname = (row.get("field") or "").strip()
		raw_value = row.get("value", "")
		if not fieldname:
			continue
		if "{{" in str(raw_value) or "{%" in str(raw_value):
			try:
				raw_value = frappe.render_template(
					raw_value,
					{"doc": doc, "instance": instance, "frappe": frappe},
				)
			except Exception:
				frappe.log_error(
					title=f"BPMN ServiceTask: update_field Jinja render failed ({bpmn_id})",
					message=frappe.get_traceback(),
				)
		updates[fieldname] = raw_value

	if not updates:
		return

	actor = frappe.session.user or instance.initiated_by or "Administrator"
	# Include modified_by in the single DB write so the audit trail
	# attributes the change to the user whose action triggered this task.
	update_payload = {**updates, "modified_by": actor}

	try:
		old_flag = getattr(frappe.flags, "bpmn_engine_action", False)
		frappe.flags.bpmn_engine_action = True
		try:
			frappe.db.set_value(doctype, docname, update_payload, update_modified=False)
		finally:
			frappe.flags.bpmn_engine_action = old_flag

	except Exception:
		frappe.log_error(
			title=f"BPMN ServiceTask: update_field failed ({bpmn_id})",
			message=frappe.get_traceback(),
		)
		raise

	frappe.publish_realtime(
		"doc_update",
		{"modified": str(frappe.utils.now_datetime()), "modified_by": actor},
		doctype=doctype,
		docname=docname,
		after_commit=True,
	)


def dispatch_google_chat(instance, task, task_cfg: dict, bpmn_id: str) -> None:
	"""
	Send a Google Chat message from a Service Task with serviceType='google_chat'.

	Supports two delivery targets:
	    individual — send a direct message to a user by email address
	    space      — post a message to a Google Chat space by space ID

	Configuration keys (from BPMN XML):
	    gchatType    — "individual" or "space"
	    gchatEmail   — recipient email (individual mode)
	    gchatSpaceId — space ID e.g. "spaces/XXXXXXX" (space mode)
	    gchatMessage — message body; Jinja2 supported

	Credentials: the site must have a Google service account JSON key stored in
	site_config.json under "google_chat_service_account_json" (the full JSON content
	as a string or dict).  The service account must have the Google Chat API scope
	https://www.googleapis.com/auth/chat.bot and be a member of the target space.

	Failures are non-fatal: the workflow continues and the error is logged.
	"""
	gchat_type = task_cfg.get("gchatType", "").strip()
	gchat_email = (task_cfg.get("gchatEmail") or "").strip()
	gchat_space_id = (task_cfg.get("gchatSpaceId") or "").strip()
	raw_message = (task_cfg.get("gchatMessage") or "").strip()

	# Validate gchatType is one of the supported values
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

	if gchat_type == "individual" and not gchat_email:
		frappe.log_error(
			title=f"BPMN ServiceTask: google_chat misconfigured ({bpmn_id})",
			message="gchatType=individual but gchatEmail is empty.",
		)
		return

	if gchat_type == "space" and not gchat_space_id:
		frappe.log_error(
			title=f"BPMN ServiceTask: google_chat misconfigured ({bpmn_id})",
			message="gchatType=space but gchatSpaceId is empty.",
		)
		return

	# Render Jinja2 in the message body
	if "{{" in raw_message or "{%" in raw_message:
		try:
			doc = (
				frappe.get_doc(instance.context_doctype, instance.context_docname)
				if (instance.context_doctype and instance.context_docname)
				else frappe._dict()
			)
			raw_message = frappe.render_template(
				raw_message,
				{"doc": doc, "instance": instance, "frappe": frappe},
			)
		except Exception:
			frappe.log_error(
				title=f"BPMN ServiceTask: google_chat Jinja render failed ({bpmn_id})",
				message=frappe.get_traceback(),
			)

	# Load service account credentials from site config
	sa_json = frappe.conf.get("google_chat_service_account_json")
	if not sa_json:
		frappe.log_error(
			title=f"BPMN ServiceTask: google_chat credentials missing ({bpmn_id})",
			message="'google_chat_service_account_json' not found in site_config.json.",
		)
		return

	try:
		import json as _json
		import requests
		from google.oauth2 import service_account
		from google.auth.transport.requests import Request as GoogleRequest

		SCOPES = ["https://www.googleapis.com/auth/chat.bot"]
		sa_info = sa_json if isinstance(sa_json, dict) else _json.loads(sa_json)
		credentials = service_account.Credentials.from_service_account_info(sa_info, scopes=SCOPES)
		credentials.refresh(GoogleRequest())
		access_token = credentials.token

		headers = {
			"Authorization": f"Bearer {access_token}",
			"Content-Type": "application/json",
		}
		payload = {"text": raw_message}

		if gchat_type == "individual":
			# Create or find a DM space with the user, then post
			dm_url = "https://chat.googleapis.com/v1/spaces:findDirectMessage"
			params = {"name": f"users/{gchat_email}"}
			dm_resp = requests.get(dm_url, headers=headers, params=params, timeout=10)
			if dm_resp.status_code == 200:
				space_name = dm_resp.json().get("name", "")
			else:
				# Fall back to setup DM space
				setup_resp = requests.post(
					"https://chat.googleapis.com/v1/spaces:setup",
					headers=headers,
					json={
						"space": {"spaceType": "DIRECT_MESSAGE"},
						"memberships": [{"member": {"name": f"users/{gchat_email}", "type": "HUMAN"}}],
					},
					timeout=10,
				)
				setup_resp.raise_for_status()
				space_name = setup_resp.json().get("name", "")

			msg_url = f"https://chat.googleapis.com/v1/{space_name}/messages"
		else:
			space_name = gchat_space_id.strip().rstrip("/")
			msg_url = f"https://chat.googleapis.com/v1/{space_name}/messages"

		resp = requests.post(msg_url, headers=headers, json=payload, timeout=10)
		resp.raise_for_status()

	except Exception:
		frappe.log_error(
			title=f"BPMN ServiceTask: google_chat API call failed ({bpmn_id})",
			message=frappe.get_traceback(),
		)


def dispatch_push_notification(instance, task, task_cfg: dict, bpmn_id: str) -> None:
	"""
	Send push notifications from a Service Task with serviceType='push_notification'.

	Recipient resolution (union of all three sources):
	  - pushToUsers      : comma-separated Frappe User IDs (email)
	  - pushToDocFields  : field names on the context doc that hold User IDs
	  - pushToRoles      : roles — all users holding those roles receive the push

	Title and Message support Jinja2 via frappe.render_template():
	  {{ doc.field_name }}    — context document fields
	  {{ instance.name }}     — BPMN instance name

	Uses one_fm.utils.send_push_notification() which sends via Firebase Cloud
	Messaging.  Falls back gracefully if one_fm is not installed.

	Failures are non-fatal: the workflow continues and the error is logged.
	"""

	# ── Resolve the template context document ─────────────────────────
	doc = frappe._dict()
	if instance.context_doctype and instance.context_docname:
		try:
			doc = frappe.get_doc(instance.context_doctype, instance.context_docname)
		except Exception:
			pass

	# ── Jinja helper ──────────────────────────────────────────────────
	jinja_ctx = {
		"doc": doc,
		"instance": instance,
		"frappe": frappe,
	}

	def render(text):
		if not text:
			return ""
		try:
			return frappe.render_template(text, jinja_ctx)
		except Exception:
			return text  # return raw on template error

	# ── Build recipient user list ─────────────────────────────────────
	recipient_users = []

	# 1. Direct user IDs (comma-separated Frappe User emails)
	raw_users = task_cfg.get("pushToUsers", "")
	if raw_users:
		recipient_users += [u.strip() for u in raw_users.split(",") if u.strip()]

	# 2. Document field values (fields on doc that hold User IDs)
	raw_fields = task_cfg.get("pushToDocFields", "")
	if raw_fields and doc:
		for field_name in raw_fields.split(","):
			field_name = field_name.strip()
			if not field_name:
				continue
			val = doc.get(field_name, "")
			if val:
				recipient_users.append(str(val).strip())

	# 3. Role members — fetch all users with the configured roles
	raw_roles = task_cfg.get("pushToRoles", "")
	if raw_roles:
		for role_name in raw_roles.split(","):
			role_name = role_name.strip()
			if not role_name:
				continue
			user_roles = frappe.get_all(
				"Has Role",
				filters={"role": role_name, "parenttype": "User"},
				fields=["parent"],
			)
			for ur in user_roles:
				if ur.parent:
					recipient_users.append(ur.parent)

	# De-duplicate preserving order
	seen = set()
	recipient_users = [u for u in recipient_users if u not in seen and not seen.add(u)]

	if not recipient_users:
		frappe.log_error(
			title=f"BPMN push_notification: No recipients resolved ({bpmn_id})",
			message=(
				f"Service Task {task_cfg} on instance {instance.name} produced "
				f"no recipient users. Push notification will not be sent."
			),
		)
		return

	# ── Resolve User → Employee mapping ───────────────────────────────
	# one_fm's send_push_notification requires an Employee ID, not a User email.
	employee_map = {}
	for user_id in recipient_users:
		emp_id = frappe.db.get_value("Employee", {"user_id": user_id, "status": "Active"}, "name")
		if emp_id:
			employee_map[user_id] = emp_id

	if not employee_map:
		frappe.log_error(
			title=f"BPMN push_notification: No employees resolved ({bpmn_id})",
			message=(
				f"None of the {len(recipient_users)} recipient users have "
				f"linked active Employee records. Push notification will not be sent."
			),
		)
		return

	# ── Render title + message ────────────────────────────────────────
	title = render(task_cfg.get("pushTitle", "")) or f"Notification from {instance.name}"
	message = render(task_cfg.get("pushMessage", "")) or title

	# ── Import push notification sender ───────────────────────────────
	try:
		from one_fm.utils import send_push_notification
	except ImportError:
		frappe.log_error(
			title=f"BPMN push_notification: one_fm not installed ({bpmn_id})",
			message=(
				"Cannot send push notifications — one_fm app is not installed. "
				"The send_push_notification function is required."
			),
		)
		return

	# ── Send to each employee ─────────────────────────────────────────
	sent_count = 0
	failed = []  # (emp_id, reason)
	for user_id, emp_id in employee_map.items():
		try:
			result = send_push_notification(emp_id, title, message)
			if result:
				sent_count += 1
			else:
				failed.append((emp_id, "returned False"))
		except Exception:
			failed.append((emp_id, "exception"))
			frappe.log_error(
				title=f"BPMN push_notification: exception for {emp_id} ({bpmn_id})",
				message=frappe.get_traceback(),
			)

	# ── Single summary log when there are failures ────────────────────
	if failed:
		fail_details = ", ".join(f"{eid} ({reason})" for eid, reason in failed)
		frappe.log_error(
			title=f"BPMN push_notification: {len(failed)} failed, {sent_count} sent ({bpmn_id})",
			message=(
				f"Push notification summary for task {bpmn_id}:\n"
				f"  Sent: {sent_count}, Failed: {len(failed)}\n"
				f"  Failed employees: {fail_details}\n\n"
				f"For 'returned False' failures, check earlier Error Log entries "
				f"from send_push_notification for the specific reason."
			),
		)


def dispatch_email(instance, task, task_cfg: dict, amp_html: str = None) -> None:
	"""
	Send an email notification from a Service Task with serviceType='send_email'.

	Recipient resolution (union of all three sources):
	  - emailTo          : direct comma-separated email addresses
	  - emailToDocFields : field names on the context doc that hold email addresses
	  - emailToRoles     : roles — all users holding those roles receive the email

	Subject and Body support Jinja2 via frappe.render_template():
	  {{ doc.field_name }}    — context document fields
	  {{ instance.name }}     — BPMN instance name
	  {{ frappe.session }}    — session info

	If emailDoctype is set, an alternate doc is loaded from that doctype
	(using context_docname) for the template context.  Defaults to the
	main context document.
	"""

	# ── Resolve the template context document ─────────────────────────
	ctx_doctype = task_cfg.get("emailDoctype") or instance.context_doctype
	ctx_docname = instance.context_docname

	doc = frappe._dict()
	if ctx_doctype and ctx_docname:
		try:
			doc = frappe.get_doc(ctx_doctype, ctx_docname)
		except Exception:
			pass

	# ── Jinja helper ──────────────────────────────────────────────────
	jinja_ctx = {
		"doc": doc,
		"instance": instance,
		"frappe": frappe,
	}

	def render(text):
		if not text:
			return ""
		try:
			return frappe.render_template(text, jinja_ctx)
		except Exception:
			return text  # return raw on template error

	# ── Build recipient list ──────────────────────────────────────────
	recipients = []

	# 1. Direct email addresses
	raw_to = task_cfg.get("emailTo", "")
	if raw_to:
		recipients += [e.strip() for e in raw_to.split(",") if e.strip()]

	# 2. Document field values (fields on doc that contain email addresses)
	raw_fields = task_cfg.get("emailToDocFields", "")
	if raw_fields and doc:
		for field_name in raw_fields.split(","):
			field_name = field_name.strip()
			if not field_name:
				continue
			val = doc.get(field_name, "")
			if val and "@" in str(val):
				recipients.append(str(val).strip())

	# 3. Role members — fetch all users with the configured roles
	raw_roles = task_cfg.get("emailToRoles", "")
	if raw_roles:
		for role_name in raw_roles.split(","):
			role_name = role_name.strip()
			if not role_name:
				continue
			user_roles = frappe.get_all(
				"Has Role",
				filters={"role": role_name, "parenttype": "User"},
				fields=["parent"],
			)
			for ur in user_roles:
				user_email = frappe.db.get_value("User", ur.parent, "email")
				if user_email and "@" in user_email:
					recipients.append(user_email)

	# De-duplicate preserving order
	seen = set()
	recipients = [r for r in recipients if r not in seen and not seen.add(r)]

	if not recipients:
		frappe.log_error(
			title="BPMN send_email: No recipients resolved",
			message=(
				f"Service Task {task_cfg} on instance {instance.name} produced "
				f"no recipient email addresses. Email will not be sent."
			),
		)
		return

	# ── Render subject + body ─────────────────────────────────────────
	subject = render(task_cfg.get("emailSubject", "") or f"Notification from {instance.name}")
	_raw_body = task_cfg.get("emailBody", "") or subject
	# emailBody may be base64-encoded (HTML stored in XML attribute)
	from one_bpmn.one_bpmn.doctype.bpmn_process_instance.assignment import _decode_html_attr
	body = render(_decode_html_attr(_raw_body))
	cc = task_cfg.get("emailCc", "") or None

	# ── Resolve sender from configured Email Account ──────────────
	sender = None
	email_account = task_cfg.get("emailAccount", "")
	if email_account:
		sender = frappe.db.get_value("Email Account", email_account, "email_id")

	# ── Send via one_fm.processor.sendemail if available ─────────
	# Uses the same branded template and notification preference
	# checks as the rest of the one_fm app (checks if user has
	# notifications enabled, email notifications enabled, and
	# preferred company email).
	# Falls back to frappe.sendmail if one_fm isn't installed.

	# Render AMP info card via the composer (Story 5)
	if not amp_html:
		try:
			from one_bpmn.email_builder.composer import compose_and_send_info_email

			amp_html = compose_and_send_info_email(
				instance, task_cfg, subject, body
			)
		except Exception:
			amp_html = None  # Graceful fallback — send plain HTML

	# Set AMP flag before sending — picked up by our Email Queue before_insert hook
	if amp_html:
		frappe.flags.amp_html = amp_html

	try:
		from one_fm.processor import sendemail as onefm_sendemail

		onefm_sendemail(
			recipients=recipients,
			subject=subject,
			sender=sender,
			header=[subject],
			message=body,
			cc=cc,
			reference_doctype=instance.context_doctype or instance.doctype,
			reference_name=instance.context_docname or instance.name,
		)
	except ImportError:
		frappe.sendmail(
			recipients=recipients,
			sender=sender,
			subject=subject,
			message=body,
			cc=cc.split(",") if cc else [],
			reference_doctype=instance.context_doctype or instance.doctype,
			reference_name=instance.context_docname or instance.name,
			now=False,
		)


def dispatch_ai_agent(instance, task, task_cfg: dict, bpmn_id: str) -> None:
	"""
	Execute an AI Agent Task via the executor package.

	Reads spiffworkflow:ai* configuration from task_cfg, Jinja-renders the
	prompts, calls the configured executor backend, and writes results into
	task.data.  On failure, sets error variables and logs to Frappe Error Log
	— the task STILL completes normally (no instance "Errored" state).

	Observability (AI-009): on every call the instrumentation layer creates
	an AI Agent Run, records Steps, and finalizes the Run. Instrumentation
	failures are caught and logged — they never block the executor call.
	"""
	from one_bpmn.agents.executor import ExecutorConfig, ExecutorContext, ErrorCode, get_executor
	from one_bpmn.agents.executor.direct_api import DirectApiExecutor  # noqa
	from one_bpmn.agents.executor.antigravity import AntigravityExecutor  # noqa

	doc = frappe._dict()
	if instance.context_doctype and instance.context_docname:
		try:
			doc = frappe.get_doc(instance.context_doctype, instance.context_docname)
		except Exception:
			pass

	jinja_ctx = {"doc": doc, "instance": instance, "frappe": frappe}

	def render(text):
		if not text:
			return ""
		try:
			return frappe.render_template(text, jinja_ctx)
		except Exception:
			return text

	system_prompt = render(task_cfg.get("aiSystemPrompt", ""))
	user_prompt   = render(task_cfg.get("aiUserPrompt", ""))

	config = ExecutorConfig(
		backend          = task_cfg.get("aiBackend", "direct_api"),
		provider_name    = task_cfg.get("aiProvider", ""),
		model            = task_cfg.get("aiModel", ""),
		system_prompt    = system_prompt,
		user_prompt      = user_prompt,
		temperature      = float(task_cfg.get("aiTemperature", 0.7) or 0.7),
		top_p            = float(task_cfg.get("aiTopP", 1.0) or 1.0),
		max_tokens       = int(task_cfg.get("aiMaxTokens", 1024) or 1024),
		timeout_seconds  = int(task_cfg.get("aiTimeout", 30) or 30),
		response_format  = task_cfg.get("aiResponseFormat", "text") or "text",
		response_schema  = task_cfg.get("aiResponseSchema") or None,
		max_retries      = int(task_cfg.get("aiMaxRetries", 2) or 2),
	)

	context = ExecutorContext(
		context_doctype = instance.context_doctype or "",
		context_docname = instance.context_docname or "",
		instance_name   = instance.name or "",
		initiated_by    = instance.initiated_by or frappe.session.user or "",
		jinja_context   = jinja_ctx,
	)

	# ── Observability: create Run ─────────────────────────────────────
	run = None
	try:
		from one_bpmn.agents.observability import create_ai_run
		from one_bpmn.one_bpmn.engine import get_task_display_name as _get_label
		run = create_ai_run(
			instance, bpmn_id, "task", config,
			bpmn_label=_get_label(task),
			process_model=instance.process_model or "",
		)
	except Exception:
		frappe.log_error(
			title=f"AI Observability: create_ai_run error ({bpmn_id})",
			message=frappe.get_traceback(),
		)

	# ── Executor ───────────────────────────────────────────────────────
	import time as _time
	_exec_start = _time.time()
	try:
		executor_cls = get_executor(config.backend)
		result = executor_cls().run(config, context)
	except Exception as exc:
		frappe.log_error(
			title=f"BPMN AI Agent Task: unexpected error ({bpmn_id})",
			message=frappe.get_traceback(),
		)
		task.data[f"{bpmn_id}_error_code"] = "UNEXPECTED_ERROR"
		task.data[f"{bpmn_id}_error_message"] = "See Frappe Error Log for details."
		# Observability: finalize on exception
		try:
			from one_bpmn.agents.observability import finalize_ai_run_on_exception
			finalize_ai_run_on_exception(run, exc)
		except Exception:
			pass
		return
	_exec_latency_ms = int((_time.time() - _exec_start) * 1000)

	# ── Observability: record Steps + finalize ─────────────────────────
	try:
		from one_bpmn.agents.observability import record_ai_step, finalize_ai_run

		if run and not getattr(run, "stub", False):
			record_ai_step(run, 0, "system", system_prompt)

			usage = result.token_usage if result.error_code == ErrorCode.SUCCESS else None
			# Attribute prompt_tokens (input cost) to the user step,
			# completion_tokens (output cost) to the assistant step.
			record_ai_step(
				run, 1, "user", user_prompt,
				prompt_tokens=usage.prompt_tokens if usage else 0,
			)

		if result.error_code == ErrorCode.SUCCESS:
			if run and not getattr(run, "stub", False):
				record_ai_step(
					run, 2, "assistant",
					str(result.output or ""),
					completion_tokens=usage.completion_tokens if usage else 0,
					latency_ms=_exec_latency_ms,
				)
			finalize_ai_run(run, result)
		else:
			finalize_ai_run(run, result)

		# Commit observability data so AI runs + steps survive even if a
		# downstream aiStopOnError raise rolls back the outer transaction.
		frappe.db.commit()
	except Exception:
		frappe.log_error(
			title=f"AI Observability: instrumentation error ({bpmn_id})",
			message=frappe.get_traceback(),
		)

	# ── Results ────────────────────────────────────────────────────────
	if result.error_code == ErrorCode.SUCCESS:
		output_var = task_cfg.get("aiOutputVariable") or f"{bpmn_id}_output"
		task.data[output_var] = result.output
		if result.token_usage:
			task.data[f"{bpmn_id}_token_usage"] = {
				"prompt_tokens":     result.token_usage.prompt_tokens,
				"completion_tokens": result.token_usage.completion_tokens,
				"total_tokens":      result.token_usage.total_tokens,
			}

		# Write-back (only on success)
		write_back_field = task_cfg.get("aiWriteBackField", "")
		if write_back_field and instance.context_doctype and instance.context_docname:
			try:
				frappe.db.set_value(
					instance.context_doctype,
					instance.context_docname,
					write_back_field,
					result.output,
				)
			except Exception:
				frappe.log_error(
					title=f"BPMN AI Agent Task: write-back failed ({bpmn_id})",
					message=frappe.get_traceback(),
				)
	else:
		error_code_name = result.error_code.value
		frappe.log_error(
			title=f"BPMN AI Agent Task: {error_code_name} ({bpmn_id})",
			message=(
				f"bpmn_id: {bpmn_id}\n"
				f"provider: {config.provider_name}\n"
				f"model: {config.model}\n"
				f"error: {result.error_message}"
			),
		)
		task.data[f"{bpmn_id}_error_code"]    = error_code_name
		task.data[f"{bpmn_id}_error_message"] = result.error_message

		# If the BPMN task is configured to stop on error, raise so the
		# engine loop in _run_engine_steps halts and the instance is
		# marked Errored (same pattern as apply_workflow).
		if task_cfg.get("aiStopOnError"):
			raise Exception(
				f"AI Agent Task '{bpmn_id}' failed: "
				f"{error_code_name} — {result.error_message}"
			)
