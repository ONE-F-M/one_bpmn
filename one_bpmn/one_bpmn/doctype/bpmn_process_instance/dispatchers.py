# Copyright (c) 2026, one-fm and contributors
# BPMN Process Instance — service task dispatch handlers
#
# These are standalone functions extracted from the BPMNProcessInstance
# controller.  Each receives the controller document as ``instance`` and reads
# only simple attributes from it (context_doctype, context_docname, name,
# initiated_by, doctype).  They are invoked from the controller's
# ``_dispatch_service_task`` router.

import json

import frappe
import frappe.utils


# ── AI Agent long-term memory integration ──────────────────────────────────
# Stable, documented format for the injected memory block. Evals and the run
# inspector reference this header — do not change it lightly.
MEMORY_BLOCK_HEADER = "Relevant memory:"


def _cfg_truthy(value) -> bool:
	"""Interpret a BPMN config value as a boolean (checkbox or string)."""
	if isinstance(value, bool):
		return value
	if isinstance(value, (int, float)):
		return bool(value)
	return str(value or "").strip().lower() in ("1", "true", "yes", "on", "enabled")


def _resolve_memory_target(task_cfg: dict, instance, bpmn_id: str):
	"""Resolve (scope, scope_key) for memory search/write from task config and
	the instance context. Returns None when the scope key can't be built (e.g.
	Entity scope with no context document) so the caller safely skips memory.

	Agent   -> agent_element (defaults to the task's bpmn_id)
	Process -> the instance's process_model
	Entity  -> {reference_doctype, reference_name} from the instance context doc
	"""
	scope = (task_cfg.get("aiMemoryScope") or "Agent").strip() or "Agent"
	if scope == "Agent":
		agent_element = task_cfg.get("aiMemoryAgentElement") or bpmn_id
		return ("Agent", agent_element) if agent_element else None
	if scope == "Process":
		process_model = getattr(instance, "process_model", None)
		return ("Process", process_model) if process_model else None
	if scope == "Entity":
		reference_doctype = getattr(instance, "context_doctype", None)
		reference_name = getattr(instance, "context_docname", None)
		if reference_doctype and reference_name:
			return ("Entity", {"reference_doctype": reference_doctype, "reference_name": reference_name})
		return None
	return None


def _format_memory_block(memories: list) -> str:
	"""Render retrieved memories as a clearly delimited block for the dynamic
	prompt layer. Stable format — see ``MEMORY_BLOCK_HEADER``.

	The provenance line is load-bearing: memories are recalled across
	conversations, and past final responses ("✅ Complete! … generated")
	presented bare read as THIS conversation's history — observed live
	(2026-08-09): the ProsAlly orchestrator concluded the requested process
	already existed, skipped its confirm tool, and every turn fell through
	to finalize's fallback question."""
	lines = [
		MEMORY_BLOCK_HEADER,
		"(Background notes recalled from PAST, separate conversations. "
		"They are context only — nothing below has happened in the current "
		"conversation, and none of it counts as work already done for the "
		"current request.)",
	]
	for m in memories:
		content = (m.get("content") or "").strip()
		if content:
			lines.append(f"- {content}")
	return "\n".join(lines)


def _extract_memory_content(output, content_field: str) -> str:
	"""Pick the content to store from the agent output. When a field is
	configured and the output is a dict, use that field; otherwise stringify."""
	if content_field and isinstance(output, dict):
		return str(output.get(content_field, "") or "")
	return str(output or "")


def _memory_output_from_trace(trace) -> str:
	"""Distillable text for a tool-protocol agent whose assistant text is empty.

	Agents instructed to "never reply in prose, always call tools" (e.g. the Docu
	orchestrator) put their user-facing answer in tool-call arguments and RESULTS
	(e.g. the Docu stage tools are zero-arg and return the draft/response as their
	result) — so ``result.output`` is legitimately blank and the note-taker would
	see nothing. Reconstruct what the agent said/did from the trace's tool calls
	instead. Most recent turn first, so the terminal tools' payloads (the final
	response) survive the distiller's input cap.
	"""
	parts = []
	for turn in reversed(trace or []):
		for call in turn.get("tool_calls") or []:
			name = call.get("name") or ""
			call_result = call.get("result") or ""
			if str(call_result).startswith("Unknown tool:"):
				continue
			args = call.get("arguments")
			rendered = ""
			if args:
				try:
					rendered = json.dumps(args, default=str)
				except (TypeError, ValueError):
					rendered = str(args)
			payload = " ".join(p for p in (rendered, str(call_result)) if p).strip()
			if payload:
				parts.append(f"{name}: {payload[:2000]}")
	return "\n".join(parts)


def _memory_write_mode(task_cfg: dict) -> str:
	"""Resolve the long-term memory write mode: "off" | "raw" | "distilled".

	Explicit ``aiMemoryWriteMode`` wins. Back-compat: a legacy ``aiMemoryAutoWrite``
	with no explicit mode now means "distilled" (extract durable facts) rather
	than the old verbatim dump; off/absent means "off".
	"""
	mode = str(task_cfg.get("aiMemoryWriteMode") or "").strip().lower()
	if mode in ("off", "raw", "distilled"):
		return mode
	return "distilled" if _cfg_truthy(task_cfg.get("aiMemoryAutoWrite")) else "off"


def _provider_for_model(model: str | None, fallback: str) -> str:
	"""The AI Provider that actually serves *model*.

	The dispatcher used to send the AGENT's provider with whatever memory model
	was configured, on the stated assumption that "the provider/backend still
	come from the task so the extraction call is always valid". That holds only
	while the memory model belongs to the same provider as the agent's own.

	Observed live: Lumina runs gpt-5-nano on an OpenAI provider and had its
	distill model set to claude-haiku-4-5. The extraction call asked the OpenAI
	endpoint for an Anthropic model, got nothing usable back, and distillation
	returned an empty list — so the agent said "I'll remember that" and NOTHING
	was ever written. Silently, because a memory failure must never break a
	turn. Agents whose memory model happened to match their provider (Docu,
	Logix) wrote memories perfectly, which is what made it look agent-specific.

	Falls back to the agent's provider when the model has no record or names no
	provider — that is the old behaviour, and it is right for a model the agent
	already runs.
	"""
	if not model:
		return fallback
	try:
		owner = frappe.db.get_value("AI Model", model, "provider")
		return owner or fallback
	except Exception:
		return fallback


def _memory_model(task_cfg: dict, key: str, fallback: str | None) -> str | None:
	"""Resolve the model for a memory write, in precedence order (WI-001793).

	``task_cfg`` already carries the linked AI Agent Configuration's values —
	``resolve_dispatch_overrides`` overlaid them before dispatch — with the
	shape's older XML attribute showing through when the agent leaves the field
	blank. After that comes the site-wide Processa Settings default, and finally
	``fallback``, the agent's own chat model, which is what ran before this
	story. Returning None is safe and expected: distillation skips with a log
	and reconciliation degrades to a plain "add".

	Resolution happens here, on the dispatch thread, because the distiller runs
	in a background RQ worker that must be handed the model as a job argument
	rather than looking it up itself.
	"""
	model = (task_cfg.get(key) or "").strip() if isinstance(task_cfg.get(key), str) else task_cfg.get(key)
	if model:
		return model

	setting = _MEMORY_MODEL_SETTINGS.get(key)
	if setting:
		try:
			default = frappe.db.get_single_value("Processa Settings", setting)
			if default:
				return default
		except Exception:
			# A missing/unreadable setting must never break a memory write.
			pass

	return fallback or None


# Shape attribute -> the Processa Settings field holding its site-wide default.
_MEMORY_MODEL_SETTINGS = {
	"aiMemoryDistillModel": "default_memory_distill_model",
	"aiMemoryReconcileModel": "default_memory_reconcile_model",
}


def _enqueue_distill(**kwargs) -> None:
	"""Run distillation off the dispatch hot path so memory never adds latency.

	Enqueued as a background job in normal operation; run inline under tests so
	assertions and FrappeTestCase rollback work without a live worker.
	"""
	if getattr(frappe.flags, "in_test", False):
		from one_bpmn.agents.memory.writeback import distill_and_write

		distill_and_write(**kwargs)
	else:
		frappe.enqueue(
			"one_bpmn.agents.memory.writeback.distill_and_write",
			queue="short",
			**kwargs,
		)


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


def _apply_value_transform(path: str, value, field_name: str, bpmn_id: str):
	"""
	Run a field's configured Value Transform over a rendered input value.

	The transform is a dotted path to ``fn(value) -> value`` declared on the
	BPMN Connector Field row, which is how provider-specific input handling stays
	out of this generic dispatcher — e.g. the Google connectors point their file
	and folder fields at ``google_common.normalize_drive_id`` so a pasted share
	link becomes a bare id. A transform that raises is logged and the original
	value is used, so a bad transform degrades rather than killing the workflow.
	"""
	path = (path or "").strip()
	if not path or value in (None, ""):
		return value
	try:
		return frappe.get_attr(path)(value)
	except Exception:
		frappe.log_error(
			title=f"BPMN ServiceTask: connector value transform failed ({bpmn_id})",
			message=f"field={field_name!r} transform={path!r}\n\n{frappe.get_traceback()}",
		)
		return value


def _resolve_connector_handler(connector_id: str, operation: str):
	"""
	Find the callable that runs a (connectorId, operation), or None.

	Connectors are configuration (BPMN Connector / Operation / Field DocTypes),
	so the configuration is the only thing consulted:

	  1. the operation's Handler Path — an explicit dotted path
	  2. execution type "HTTP Request" — the declarative executor, no Python

	There is deliberately no implicit lookup behind these. Every operation says
	how it runs, so an unconfigured one fails loudly instead of resolving to
	whatever function happened to register that name.
	"""
	from one_bpmn.one_bpmn.connectors import manifest as _manifest

	try:
		spec = _manifest.get_execution_spec(connector_id, operation)
	except Exception:
		frappe.log_error(
			title=f"BPMN ServiceTask: connector config unreadable ({connector_id}/{operation})",
			message=frappe.get_traceback(),
		)
		spec = None

	if spec:
		if spec.handler_path:
			try:
				return frappe.get_attr(spec.handler_path)
			except Exception:
				frappe.log_error(
					title=f"BPMN ServiceTask: connector handler path failed ({connector_id}/{operation})",
					message=f"handler_path={spec.handler_path!r}\n\n{frappe.get_traceback()}",
				)
				return None

		if spec.execution_type == "HTTP Request":
			from one_bpmn.one_bpmn.connectors import http_ops

			return lambda params, ctx: http_ops.execute(spec, params, ctx)

	# No third path. An operation that names neither an HTTP request nor a
	# handler is unconfigured, and saying so beats silently finding a function
	# that happens to share its name.
	return None


def dispatch_connector(instance, task, task_cfg: dict, bpmn_id: str) -> None:
	"""
	Execute a Service Task with serviceType='connector'.

	Config keys (from BPMN XML):
	    connectorId     — provider id, e.g. "google_drive"
	    operation       — operation id, e.g. "createFile"
	    connectorParams — JSON object of operation inputs (values may be Jinja2)
	    resultVariable  — task-data key to store the handler's return under
	    failOnError     — truthy → re-raise so the instance is marked Errored;
	                      otherwise errors are logged and the workflow continues.

	Input values flagged as expressions in the manifest are Jinja2-rendered
	against {doc, instance, frappe, task_data}, then passed through the field's
	configured Value Transform if it declares one (that is how, for example, a
	Google Drive field accepts either a share link or a bare id — nothing about
	any specific provider is known here). The handler's dict return is written to
	task.data[resultVariable] so downstream tasks/gateways can use it.
	"""
	import json as _json

	from one_bpmn.one_bpmn.connectors import manifest as _manifest

	connector_id = (task_cfg.get("connectorId") or "").strip()
	operation = (task_cfg.get("operation") or "").strip()
	result_var = (task_cfg.get("resultVariable") or "").strip()
	fail_on_error = _cfg_truthy(task_cfg.get("failOnError"))

	# Role gate. Hiding a restricted connector in the modeler is convenience;
	# this is the control. A diagram authored before the restriction — or by
	# someone who had the role and has since lost it — must not still run it.
	# Checked against the user the instance is running as, which for a chat or
	# form-triggered process is the person who caused it.
	if not _manifest.user_may_use_connector(connector_id):
		frappe.log_error(
			title=f"BPMN ServiceTask: connector not permitted ({bpmn_id})",
			message=(
				f"{frappe.session.user} lacks a role allowed to use connector "
				f"{connector_id!r} (operation {operation!r})."
			),
		)
		if fail_on_error:
			frappe.throw(f"Not permitted to use connector {connector_id}")
		return

	handler = _resolve_connector_handler(connector_id, operation)
	if not handler:
		frappe.log_error(
			title=f"BPMN ServiceTask: connector unknown ({bpmn_id})",
			message=(
				f"No executor for connectorId={connector_id!r} operation={operation!r}. "
				f"Either it is not a BPMN Connector Operation, it is disabled, or its "
				f"row names neither an HTTP request nor a Handler Path."
			),
		)
		if fail_on_error:
			frappe.throw(f"Unknown connector {connector_id}/{operation}")
		return

	raw_params = task_cfg.get("connectorParams") or "{}"
	try:
		params = _json.loads(raw_params) if isinstance(raw_params, str) else dict(raw_params or {})
		if not isinstance(params, dict):
			raise ValueError("connectorParams must be a JSON object")
	except Exception:
		frappe.log_error(
			title=f"BPMN ServiceTask: connector params invalid ({bpmn_id})",
			message=f"connectorParams is not a JSON object: {raw_params!r}",
		)
		if fail_on_error:
			raise
		return

	# ── Resolve field values: Jinja render (expressions) + Value Transform ──
	doc = (
		frappe.get_doc(instance.context_doctype, instance.context_docname)
		if (instance.context_doctype and instance.context_docname)
		else frappe._dict()
	)
	render_ctx = {"doc": doc, "instance": instance, "frappe": frappe, "task_data": dict(task.data)}
	specs = _manifest.field_specs(connector_id, operation)
	transforms = _manifest.field_transforms(connector_id, operation)

	resolved = {}
	for key, value in params.items():
		spec = specs.get(key, {})
		val = value
		expression = spec.get("expression", True)  # default: allow expressions
		# connectorParams arrives from an XML attribute, so entity artifacts
		# (e.g. &#39; for ' introduced by moddle/serialization round-trips) can
		# survive into expression text and break Jinja. Undo them first.
		if isinstance(val, str) and expression:
			import html as _html
			val = _html.unescape(val)
		if isinstance(val, str) and expression and ("{{" in val or "{%" in val):
			try:
				val = frappe.render_template(val, render_ctx)
			except Exception:
				frappe.log_error(
					title=f"BPMN ServiceTask: connector Jinja render failed ({bpmn_id})",
					message=f"field={key!r}\n\n{frappe.get_traceback()}",
				)
		val = _apply_value_transform(transforms.get(key), val, key, bpmn_id)
		resolved[key] = val

	ctx = {"instance": instance, "task": task, "doc": doc, "task_data": dict(task.data)}
	output = None
	try:
		output = handler(resolved, ctx)
	except Exception:
		frappe.log_error(
			title=f"BPMN ServiceTask: connector {connector_id}/{operation} failed ({bpmn_id})",
			message=frappe.get_traceback(),
		)
		if fail_on_error:
			raise

	if result_var:
		task.data[result_var] = output


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


def _emails_from_doc_field(val) -> list:
	"""Turn one recipient field's value into email addresses.

	A recipient field holds either an address or a USER, and the two cannot be
	treated the same. ``owner``, ``modified_by`` and any Link to User hold a user
	id, which is *usually* the address but is not guaranteed to be: the obvious
	case is ``Administrator``, and a site can carry users whose id and email
	differ.

	This used to accept a value only when it contained "@", so those users were
	dropped in silence — the task logged "no recipients resolved" and sent
	nothing while the configuration looked perfectly correct. A user field that
	cannot deliver is worse than one that is not offered, so anything without an
	"@" is looked up as a user before being given up on.

	Returns a list because a field may hold several comma-separated addresses,
	and because "no usable recipient" is then an empty list rather than a special
	case for the caller to remember.
	"""
	if not val:
		return []

	found = []
	for part in str(val).split(","):
		part = part.strip()
		if not part:
			continue
		if "@" in part:
			found.append(part)
			continue
		# Not an address — try it as a user id. A value that is neither (a Link to
		# some other doctype, say) simply resolves to nothing and is skipped.
		email = frappe.db.get_value("User", part, "email")
		if email and "@" in email:
			found.append(email)
	return found


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

	# 2. Document field values (fields on doc naming a recipient)
	raw_fields = task_cfg.get("emailToDocFields", "")
	if raw_fields and doc:
		for field_name in raw_fields.split(","):
			field_name = field_name.strip()
			if not field_name:
				continue
			recipients += _emails_from_doc_field(doc.get(field_name))

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


def dispatch_send_notification(instance, task, task_cfg: dict, bpmn_id: str) -> None:
	"""
	Execute a BPMN Send Task (WI-001352 gap closure, 2026-07-04).

	Send tasks carry spiffworkflow:notificationName — the name of a Frappe
	Notification record (event=Method so it only fires when told to). This
	renders and sends that notification against the instance's context doc.

	Evidence convention: on success, ``{bpmn_id}_sent = 1`` is written into
	the task's containing scope (the ad-hoc subprocess data for inner tasks)
	so AI Task Selector prompts can gate follow-up steps on it — the same
	observable-evidence pattern registry tools use via *_toolCallResult. On
	failure, ``{bpmn_id}_send_error`` carries the reason instead: the flow
	deliberately does NOT pretend the email went out, and the selector's
	next decision sees the failure in its evidence.

	Never raises — a broken notification must not wedge the engine.
	"""
	scope = getattr(task.workflow, "data", None)
	try:
		notification_name = (task_cfg.get("notificationName") or "").strip()
		if not notification_name:
			return
		if not (instance.context_doctype and instance.context_docname):
			raise ValueError("send task has no context document to render against")

		notification = frappe.get_doc("Notification", notification_name)
		doc = frappe.get_doc(instance.context_doctype, instance.context_docname)
		notification.send(doc)

		if isinstance(scope, dict):
			scope[f"{bpmn_id}_sent"] = 1
	except Exception as exc:
		if isinstance(scope, dict):
			scope[f"{bpmn_id}_send_error"] = str(exc)
		frappe.log_error(
			title=f"BPMN send task failed: {bpmn_id} on {instance.name}",
			message=frappe.get_traceback(),
		)


def resume_ai_agent(instance, task, task_cfg: dict, bpmn_id: str, human_result=None, run_name: str = None) -> bool:
	"""Resume a suspended AI Agent Task with the human's output.

	Reloads the checkpointed conversation, injects *human_result* as the
	pending human tool call's result, and re-enters the step loop. Exactly-once:
	the underlying claim flips the run out of "Suspended" atomically, so a
	second call (job redelivery, double submit) returns False and does nothing.

	Returns True when a resume actually ran.
	"""
	from one_bpmn.agents import checkpoint as _checkpoint

	run_name = run_name or _checkpoint.get_suspended_run(instance.name, bpmn_id)
	if not run_name:
		return False
	if human_result is not None:
		_checkpoint.store_human_result(run_name, human_result)
	before = frappe.db.get_value("AI Agent Run", run_name, "status")
	if before != "Suspended":
		return False
	dispatch_ai_agent(instance, task, task_cfg, bpmn_id, resume_run=run_name)
	return True


def _checkpointed_tool_results(resume_payload: dict) -> list:
	"""Tool results of the segments BEFORE the final resume, in call order:
	every completed turn's results from the checkpointed transcript, the
	suspended turn's deferred automatic results, then the human's answer."""
	from one_bpmn.agents.checkpoint import _human_result_str

	suspension = resume_payload.get("suspension") or {}
	out = []

	def _add(name, content):
		if name and not str(content or "").startswith("Unknown tool:"):
			out.append({"tool": name, "result": content or ""})

	for entry in suspension.get("transcript") or []:
		if entry.get("role") == "tool_results":
			for r in entry.get("results") or []:
				_add(r.get("name"), r.get("content"))
	for r in suspension.get("deferred_results") or []:
		_add(r.get("name"), r.get("content"))
	pending = suspension.get("pending_call") or {}
	_add(pending.get("name"), _human_result_str(resume_payload.get("pending_result")))
	return out


def dispatch_ai_agent(instance, task, task_cfg: dict, bpmn_id: str, resume_run: str = None) -> None:
	"""
	Execute an AI Agent Task via the executor package.

	Reads spiffworkflow:ai* configuration from task_cfg, Jinja-renders the
	prompts, calls the configured executor backend, and writes results into
	task.data.  On failure, sets error variables and logs to Frappe Error Log
	— the task STILL completes normally (no instance "Errored" state).

	Durable HITL: when the model calls a HUMAN tool the executor returns
	SUSPENDED — the conversation is checkpointed on the AI Agent Run, a
	waiting marker is left on task.data, and the task does NOT complete.
	``resume_run`` re-enters a checkpointed run after the person answered:
	prompts are NOT re-rendered (the transcript holds the rendered originals)
	and the claim is idempotent — an already-claimed run is a no-op.

	Observability (AI-009): on every call the instrumentation layer creates
	an AI Agent Run, records Steps, and finalizes the Run. Instrumentation
	failures are caught and logged — they never block the executor call.
	A suspended run stays open (status="Suspended") instead of finalizing.
	"""
	from frappe.utils import cint

	from one_bpmn.agents.executor import (
		DEFAULT_MAX_OUTPUT_TOKENS,
		DEFAULT_TIMEOUT_SECONDS,
		ErrorCode,
		ExecutorConfig,
		ExecutorContext,
		get_executor,
	)
	from one_bpmn.agents.executor.direct_api import DirectApiExecutor  # noqa
	from one_bpmn.agents.executor.antigravity import AntigravityExecutor  # noqa
	from one_bpmn.agents import checkpoint as _checkpoint

	resume_payload = None
	if resume_run:
		resume_payload = _checkpoint.claim_for_resume(resume_run)
		if resume_payload is None:
			return  # already resumed (redelivery / double submit) — no-op

	# WI-001637 (live link): a linked AI Agent Configuration is authoritative at
	# dispatch for agent-level fields (prompt, provider, model, temperature,
	# max tokens) — the shape's copies are the editing view and the fallback
	# when the config is missing.
	#
	# The resume path used to skip this overlay entirely, reasoning that the
	# checkpointed transcript already holds the prompts. True of the prompts,
	# and false of everything else in it: the overlay is also where the PROVIDER
	# and MODEL come from for any shape that carries no copies of its own.
	# Without them a resumed run reached the executor with provider_name="" and
	# died on "AI Provider '' not found" — so a human step on such an
	# agent could be completed and never continued. The prompt is the one key
	# held back, because the checkpoint's copy is authoritative for a
	# conversation already in flight.
	if task_cfg.get("aiAgentConfig"):
		from one_bpmn.agents.agent_config_resolver import resolve_dispatch_overrides
		_overrides = resolve_dispatch_overrides(task_cfg["aiAgentConfig"])
		if resume_payload:
			_overrides = {k: v for k, v in _overrides.items() if k != "aiSystemPrompt"}
		task_cfg = {**task_cfg, **_overrides}

	doc = frappe._dict()
	if instance.context_doctype and instance.context_docname:
		try:
			doc = frappe.get_doc(instance.context_doctype, instance.context_docname)
		except Exception:
			pass

	jinja_ctx = {"doc": doc, "instance": instance, "frappe": frappe}
	if hasattr(task, "data") and isinstance(task.data, dict):
		jinja_ctx.update(task.data)

	def render(text):
		if not text:
			return ""
		try:
			return frappe.render_template(text, jinja_ctx)
		except Exception:
			return text

	if resume_payload:
		# The conversation continues — the checkpointed system prompt must be
		# reused verbatim. The static layer is frozen for the whole run, so a
		# resumed segment sees exactly the context the first segment saw.
		system_prompt = resume_payload.get("system_prompt") or ""
		user_prompt = ""
	else:
		# ── Static context layer (WI-001639) ──────────────────────────────
		# Instructions -> Examples -> Guard Rails, assembled once and frozen
		# for the rest of the run. Examples and guard rails come from the
		# linked AI Agent Configuration; a shape with no linked config renders
		# its own prompt alone, exactly as before.
		from one_bpmn.agents.context_assembler import build_static_context, load_agent_behaviour

		instructions = render(task_cfg.get("aiSystemPrompt", ""))
		agent_config = {}
		if task_cfg.get("aiAgentConfig"):
			try:
				agent_config = load_agent_behaviour(task_cfg["aiAgentConfig"])
			except Exception:
				# Behaviour rows are additive: a failure here must degrade to
				# the plain prompt, never take the agent down.
				frappe.log_error(
					title=f"BPMN AI Agent Task: static context load failed ({bpmn_id})",
					message=frappe.get_traceback(),
				)
		system_prompt = build_static_context(
			system_prompt=instructions,
			examples=agent_config.get("examples"),
			guardrails=agent_config.get("guardrails"),
			skills=agent_config.get("enabled_skills"),
		)
		user_prompt = render(task_cfg.get("aiUserPrompt", ""))

	# ── Long-term memory: search + inject (config-gated; safe when off) ──
	# When aiLongTermMemory is enabled, recall memories for the task's scope
	# using the rendered user prompt as the query.
	#
	# WI-001639: the retrieved block goes into the DYNAMIC layer (ahead of the
	# user's text), not onto the system prompt. Memory is searched per turn, so
	# appending it to the system prompt made the "immutable" layer differ on
	# every call — the drift this story exists to remove — and invalidated the
	# provider's system-prompt cache breakpoint each time.
	# Failures never block the call.
	memory_target = None
	if not resume_payload and _cfg_truthy(task_cfg.get("aiLongTermMemory")):
		try:
			memory_target = _resolve_memory_target(task_cfg, instance, bpmn_id)
			if memory_target and user_prompt:
				from one_bpmn.agents.context_assembler import build_dynamic_preamble
				from one_bpmn.agents.memory.tools import memory_search
				scope, scope_key = memory_target
				limit = int(task_cfg.get("aiMemoryLimit", 5) or 5)
				memories = memory_search(
					scope, scope_key, user_prompt, limit=limit, ignore_permissions=True
				)
				if memories:
					user_prompt = build_dynamic_preamble(
						memory_block=_format_memory_block(memories),
						user_prompt=user_prompt,
					)
		except Exception:
			frappe.log_error(
				title=f"BPMN AI Agent Task: memory_search failed ({bpmn_id})",
				message=frappe.get_traceback(),
			)

	# ── Tools: the shapes of the referenced ad-hoc sub-process (Camunda "tools
	# are the shapes"). aiToolShapes was embedded at compile time (WI-001421);
	# each becomes a function-tool the LLM can call, whose result feeds back into
	# the loop. Empty/absent → a plain LLM call (tools stays None).

	tool_specs = []
	tool_shapes = task_cfg.get("aiToolShapes")
	if tool_shapes:
		from one_bpmn.agents.shape_tools import compile_shape_tools
		tool_specs = compile_shape_tools(tool_shapes, instance) or []

	# WI-001425: AI Skills Tool Injection
	from one_bpmn.api.skill_tools import get_skill_tools
	agent_name = task_cfg.get("aiAgentConfig")
	if agent_name:
		skill_tool_specs = get_skill_tools(agent_name, instance)
		if skill_tool_specs:
			tool_specs.extend(skill_tool_specs)
			
	# Inject tools for dynamically loaded skills!
	if instance:
		active_skill_names = frappe.cache().get_value(f"active_skill_names_{instance.name}") or []
		if active_skill_names:
			import json
			from one_bpmn.agents.llm_provider.base import ToolSpec
			
			def make_dynamic_tool_fn(script_name, tool_name):
				def fn(**kwargs):
					from one_bpmn.agents.shape_tools import _synthetic_task, _run_server_script
					task = _synthetic_task(tool_name, kwargs)
					try:
						_run_server_script(instance, script_name, task, tool_name)
						produced = {k: v for k, v in task.data.items() if k not in kwargs}
						return json.dumps(produced or {"ok": True}, default=str)
					except Exception as e:
						return json.dumps({"error": str(e)})
				return fn

			for skill_name in active_skill_names:
				allowed_tools = frappe.get_all("AI Skill Allowed Tool", filters={"parent": skill_name}, fields=["tool"])
				for allowed in allowed_tools:
					tool_name = allowed.tool
					# Check if we already have it to avoid duplicates
					if any(t.name == tool_name for t in tool_specs):
						continue
						
					tool_doc = frappe.db.get_value("AI Agent Tool", tool_name, ["description", "json_schema", "script"], as_dict=True)
					if tool_doc:
						try:
							schema = json.loads(tool_doc.json_schema)
							parameters = schema.get("properties", {})
							required = schema.get("required", [])
						except Exception:
							parameters = {}
							required = []
							
						tool_specs.append(ToolSpec(
							fn=make_dynamic_tool_fn(tool_doc.script, tool_name),
							name=tool_name,
							description=tool_doc.description or tool_name,
							parameters=parameters,
							required=required
						))

			# WI-001425 (US4): a skill narrows the tool pool, it never widens it.
			# A skill with no Allowed Tools rows "changes nothing" - only skills
			# that actually declare an allow-list restrict the turn. The LLM
			# adapters call ToolSpec.fn directly by name, so swapping it here is
			# sufficient to intercept.
			restrictive_allowed_names = set()
			has_restrictive_skill = False
			for skill_name in active_skill_names:
				skill_allowed = frappe.get_all("AI Skill Allowed Tool", filters={"parent": skill_name}, pluck="tool")
				if skill_allowed:
					has_restrictive_skill = True
					restrictive_allowed_names.update(skill_allowed)

			def make_blocked_fn(tool_name):
				def blocked_fn(**kwargs):
					return "Error: Tool not allowed by active skill."
				return blocked_fn

			if has_restrictive_skill:
				allowed_tool_names = restrictive_allowed_names | {"load_skill", "load_skill_resource"}
				for t in tool_specs:
					if t.name not in allowed_tool_names:
						t.fn = make_blocked_fn(t.name)

	if not tool_specs:
		tool_specs = None


	config = ExecutorConfig(
		backend          = task_cfg.get("aiBackend", "direct_api"),
		provider_name    = task_cfg.get("aiProvider", ""),
		# The config actually resolved for this dispatch — create_ai_run's primary attribution source.
		agent_config_name = task_cfg.get("aiAgentConfig", ""),
		model            = task_cfg.get("aiModel", ""),
		system_prompt    = system_prompt,
		user_prompt      = user_prompt,
		temperature      = float(task_cfg.get("aiTemperature", 0.7) or 0.7),
		top_p            = float(task_cfg.get("aiTopP", 1.0) or 1.0),
		# cint FIRST, then fall back: a shape attribute arrives as a string, and
		# "0" is truthy — `"0" or DEFAULT` would yield a zero budget. cint also
		# absorbs "", "  " and junk, which int() would raise on.
		max_tokens       = cint(task_cfg.get("aiMaxTokens")) or DEFAULT_MAX_OUTPUT_TOKENS,
		# Defer to the shared default rather than repeating a number here. The
		# hardcoded 30 that used to sit in this line silently overrode it, so
		# raising the default had no effect on any AI task in any process map.
		timeout_seconds  = cint(task_cfg.get("aiTimeout")) or DEFAULT_TIMEOUT_SECONDS,
		response_format  = task_cfg.get("aiResponseFormat", "text") or "text",
		response_schema  = task_cfg.get("aiResponseSchema") or None,
		max_retries      = int(task_cfg.get("aiMaxRetries", 2) or 2),
		tools            = tool_specs,
		# "Maximum model calls" (Camunda Limits); caps the tool-calling loop.
		max_tool_calls   = int(task_cfg.get("aiMaxToolCalls", 10) or 10),
		resume_state     = _checkpoint.build_resume_state(resume_payload) if resume_payload else None,
	)

	context = ExecutorContext(
		context_doctype = instance.context_doctype or "",
		context_docname = instance.context_docname or "",
		instance_name   = instance.name or "",
		initiated_by    = instance.initiated_by or frappe.session.user or "",
		jinja_context   = jinja_ctx,
	)

	# ── Observability: create Run (or continue the suspended one) ─────
	run = None
	if resume_payload:
		try:
			run = frappe.get_doc("AI Agent Run", resume_run)
			# The human's answer is a real tool result — record it as a step
			# BEFORE the resumed turns so the Run reads chronologically.
			from one_bpmn.agents.observability import record_ai_step
			pending = (resume_payload.get("suspension") or {}).get("pending_call") or {}
			human_result = _checkpoint.build_resume_state(resume_payload)["human_result"]
			record_ai_step(
				run,
				# step_index is 1-based: with N steps recorded, the next is N+1
				frappe.db.count("AI Agent Step", {"run": run.name}) + 1,
				"tool",
				human_result,
				tool_calls=[{
					"name": pending.get("name") or "",
					"tool_source": "diagram_task",
					"arguments": pending.get("arguments") or {},
					"result": human_result,
					"status": "Success",
				}],
			)
		except Exception:
			frappe.log_error(
				title=f"AI Observability: resume run load error ({bpmn_id})",
				message=frappe.get_traceback(),
			)
	else:
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

	# WI-001645: publish which agent is running so the tool-policy interceptor
	# can apply that agent's tool grant — including for tools a Server Script
	# constructs for its own sub-agent call, which never see this frame.
	from one_bpmn.security.tool_policy import reset_current_agent, set_current_agent

	_policy_token = set_current_agent(task_cfg.get("aiAgentConfig"))

	# WI-002053: and publish it as the DELEGATING agent, so a delegation made
	# from one of this agent's tool shapes is attributed to the agent rather
	# than to the map it happens to be running inside.
	#
	# a2a_client_ops._delegating_agent() already looks for this attribute, but
	# nothing ever set it, so it fell through to "the agent whose process_model
	# this instance is". That works for an agent running its OWN map and fails
	# silently for an orchestrator invoked as a Call Activity: the instance is
	# then Software Development's, which is no agent's map, so the delegating
	# agent resolved to None — and with None, guardrails_for() returns DEFAULTS
	# instead of the agent's configured limits, and may_delegate_to() returns
	# True without consulting restrict_delegates at all. The limits and the
	# allow-list were both quietly absent on exactly the production path.
	_prev_delegating_agent = getattr(instance, "_a2a_delegating_agent", None)
	instance._a2a_delegating_agent = task_cfg.get("aiAgentConfig")
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
	finally:
		# Must clear on BOTH paths — a leaked agent id would apply this agent's
		# tool grant to whatever runs next in this worker.
		reset_current_agent(_policy_token)
		# Restored rather than deleted: an agent task nested inside another
		# agent's map must hand identity back, not blank it.
		instance._a2a_delegating_agent = _prev_delegating_agent
	_exec_latency_ms = int((_time.time() - _exec_start) * 1000)

	# ── Durable HITL: token totals are cumulative across suspensions ───
	if resume_payload and result.token_usage:
		result.token_usage.prompt_tokens += int(resume_payload.get("prompt_tokens_so_far") or 0)
		result.token_usage.completion_tokens += int(resume_payload.get("completion_tokens_so_far") or 0)
		# WI-001643: the cache breakdown must accumulate alongside the prompt
		# total it is a breakdown OF — otherwise the final segment's small cache
		# figures would be costed against every earlier segment's prompt tokens.
		result.token_usage.cache_read_tokens += int(
			resume_payload.get("cache_read_tokens_so_far") or 0
		)
		result.token_usage.cache_write_tokens += int(
			resume_payload.get("cache_write_tokens_so_far") or 0
		)
		result.token_usage.total_tokens = (
			result.token_usage.prompt_tokens + result.token_usage.completion_tokens
		)

	# ── Observability: record Steps + finalize ─────────────────────────
	try:
		from one_bpmn.agents.observability import record_ai_step, finalize_ai_run

		if run and not getattr(run, "stub", False):
			if tool_specs:
				# Tool-calling run: system+user prompts are config; the trace
				# carries one turn per LLM call. Record it with the shared
				# recorder — one Step per turn, one ai_agent_tool_call row per
				# call, tool_source = diagram_task (the shapes are the tools).
				# On resume, system/user steps were recorded at dispatch time —
				# only the resumed segment's turns are appended.
				from one_bpmn.agents.observability import record_selector_turns
				if not resume_payload:
					record_ai_step(run, 1, "system", system_prompt)
					record_ai_step(run, 2, "user", user_prompt)
				source_map = {t.name: "diagram_task" for t in tool_specs}
				record_selector_turns(run, result.trace or [], source_map)
			else:
				record_ai_step(run, 1, "system", system_prompt)

				usage = result.token_usage if result.error_code == ErrorCode.SUCCESS else None
				# Attribute prompt_tokens (input cost) to the user step,
				# completion_tokens (output cost) to the assistant step.
				record_ai_step(
					run, 2, "user", user_prompt,
					prompt_tokens=usage.prompt_tokens if usage else 0,
					# The cache breakdown rides with the prompt tokens it splits,
					# so the user step is costed at the real blend of rates
					# rather than all-input (WI-001643).
					cache_read_tokens=getattr(usage, "cache_read_tokens", 0) if usage else 0,
					cache_write_tokens=getattr(usage, "cache_write_tokens", 0) if usage else 0,
				)
				if result.error_code == ErrorCode.SUCCESS:
					record_ai_step(
						run, 3, "assistant",
						str(result.output or ""),
						completion_tokens=usage.completion_tokens if usage else 0,
						latency_ms=_exec_latency_ms,
					)

		# A suspension is not an outcome — the run stays open ("Suspended",
		# set by save_checkpoint below) until the final answer or a failure.
		if result.error_code != ErrorCode.SUSPENDED:
			# WI-001823: a map may declare what "done" means for this shape by
			# naming the reply key that proves it — Logix finishes when it has a
			# script, ProsAlly when it has a diagram. Left unset, completion
			# falls back to the generic error/turn-cap/output signals.
			finalize_ai_run(run, result, goal_key=(task_cfg.get("aiGoalOutputKey") or "").strip() or None)

		# Commit observability data so AI runs + steps survive even if a
		# downstream aiStopOnError raise rolls back the outer transaction.
		# Never inside tests: a mid-test commit also persists the test's
		# fixture docs, defeating FrappeTestCase rollback and leaking
		# orphan "Active" instances into the shared dev DB.
		if not frappe.flags.in_test:
			frappe.db.commit()
	except Exception:
		frappe.log_error(
			title=f"AI Observability: instrumentation error ({bpmn_id})",
			message=frappe.get_traceback(),
		)

	# ── Stopped at its turn cap, and this agent was delegated to ───────
	# WI-002053. hit_turn_cap already exists and goal_completion already reads
	# it as Not Achieved, but nobody was ever told. A worker that ran out of
	# turns returns whatever partial text it had, which at a glance is
	# indistinguishable from finishing — so the caller accepted an unfinished
	# answer and the process moved on.
	#
	# Only escalated when this instance IS a delegated worker: its context
	# document is the A2A Task that asked for the work. An agent hitting its cap
	# in an ordinary process is a different conversation and not this story's.
	if getattr(result, "hit_turn_cap", False) and instance.context_doctype == "A2A Task":
		try:
			from one_bpmn.agents.a2a import delegation

			delegation.stopped_at_limit(
				a2a_task=instance.context_docname,
				reason="turn_cap",
				limit_value=cint(task_cfg.get("aiMaxToolCalls")),
				reached_value=cint(task_cfg.get("aiMaxToolCalls")),
				detail=(
					"The agent used every tool-calling turn it was allowed and never "
					"produced a final answer, so anything it did return is partial."
				),
				instance=instance.name,
				worker_agent=task_cfg.get("aiAgentConfig"),
			)
		except Exception:
			frappe.log_error(
				title=f"AI Agent Task: turn-cap escalation failed ({bpmn_id})",
				message=frappe.get_traceback(),
			)

	# ── Results ────────────────────────────────────────────────────────
	if result.error_code == ErrorCode.SUSPENDED:
		# The model called a human tool. Checkpoint the conversation on the
		# Run (status="Suspended") and leave a waiting marker on task.data —
		# the engine wiring parks the service task and spawns the human task
		# off this marker. No output/error variables, no retry consumed, no
		# aiStopOnError: waiting for a person is not a failure.
		run = _checkpoint.save_checkpoint(
			run,
			instance,
			bpmn_id,
			result.suspension or {},
			system_prompt=system_prompt,
			wf_task_id=str(getattr(task, "id", "") or ""),
			human_row_id="",
			prior_prompt_tokens=int((resume_payload or {}).get("prompt_tokens_so_far") or 0),
			prior_completion_tokens=int((resume_payload or {}).get("completion_tokens_so_far") or 0),
			prior_cache_read_tokens=int((resume_payload or {}).get("cache_read_tokens_so_far") or 0),
			prior_cache_write_tokens=int((resume_payload or {}).get("cache_write_tokens_so_far") or 0),
		)
		pending = (result.suspension or {}).get("pending_call") or {}
		pending_name = pending.get("name") or ""
		# The shape's diagram label rides along for the human task row name.
		label = ""
		try:
			for shape in json.loads(task_cfg.get("aiToolShapes") or "[]"):
				if isinstance(shape, dict) and shape.get("bpmn_id") == pending_name:
					label = shape.get("label") or ""
					break
		except Exception:
			pass
		# One marker, because the engine's parking gates all key off it: this AI
		# task is STARTED and cannot produce its own result yet. `waits_on` says
		# who owes it — a person (the original case, and the default) or another
		# agent this one delegated to from inside a tool call (WI-001933). Only
		# the human case spawns a task for someone to do.
		waiting_marker = {
			"run": run.name,
			"tool": pending_name,
			"label": label,
			"arguments": pending.get("arguments") or {},
		}
		deferred_wait = (result.suspension or {}).get("deferred_wait") or {}
		if deferred_wait.get("a2a_task"):
			waiting_marker["waits_on"] = "a2a"
			waiting_marker["a2a_task"] = deferred_wait["a2a_task"]
			waiting_marker["label"] = label or deferred_wait.get("label") or pending_name
		task.data["_bpmn_ai_waiting_human"] = waiting_marker
		if not frappe.flags.in_test:
			frappe.db.commit()
		return

	if result.error_code == ErrorCode.SUCCESS:
		# Completing a resumed run: drop the waiting marker the suspension left
		if isinstance(task.data, dict):
			task.data.pop("_bpmn_ai_waiting_human", None)
		output_var = task_cfg.get("aiOutputVariable") or f"{bpmn_id}_output"
		task.data[output_var] = result.output
		if result.token_usage:
			task.data[f"{bpmn_id}_token_usage"] = {
				"prompt_tokens":     result.token_usage.prompt_tokens,
				"completion_tokens": result.token_usage.completion_tokens,
				"total_tokens":      result.token_usage.total_tokens,
			}

		# Tool-call evidence: expose the results the shape-tools returned so
		# downstream steps can route on them. Per-tool {tool}_toolCallResult and
		# an aggregate aiToolCallResults var (Camunda's "Tool call results").
		# On a resumed run the trace only covers the final segment — the
		# earlier segments' results (and the human's answer) are reconstructed
		# from the checkpointed transcript so downstream evidence is complete.
		if tool_specs and (result.trace or resume_payload):
			all_results = []
			if resume_payload:
				all_results.extend(_checkpointed_tool_results(resume_payload))
			for turn in result.trace or []:
				for call in turn.get("tool_calls") or []:
					call_result = call.get("result") or ""
					tool_name = call.get("name") or ""
					if not tool_name or str(call_result).startswith("Unknown tool:"):
						continue
					all_results.append({"tool": tool_name, "result": call_result})
			for entry in all_results:
				task.data[f"{entry['tool']}_toolCallResult"] = entry["result"]
			results_var = task_cfg.get("aiToolCallResults") or f"{bpmn_id}_toolCallResults"
			task.data[results_var] = all_results

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
		# ── Long-term memory: write (config-gated) ──────────────────────
		# "distilled" (default) extracts durable, deduplicated facts from the
		# run via a background job; "raw" stores the output verbatim (legacy);
		# "off" writes nothing. Failures never block the task.
		write_mode = _memory_write_mode(task_cfg)
		if write_mode != "off":
			try:
				write_target = memory_target or _resolve_memory_target(task_cfg, instance, bpmn_id)
				if write_target:
					scope, scope_key = write_target
					src = run.name if run and not getattr(run, "stub", False) else None
					if write_mode == "raw":
						content = _extract_memory_content(result.output, task_cfg.get("aiMemoryContentField", ""))
						if content:
							from one_bpmn.agents.memory.tools import memory_write
							memory_write(
								scope,
								scope_key,
								content,
								dedup_key=(task_cfg.get("aiMemoryDedupKey") or None),
								source_run=src,
								ignore_permissions=True,
							)
					else:  # distilled
						# Distill and reconcile with the models the admin chose
						# (agent -> Processa Settings -> the agent's own model),
						# resolved here on the dispatch thread and handed to the
						# background job. The provider/backend still come from
						# the task so the extraction call is always valid.
						# Tool-protocol agents leave result.output empty (their
						# answer lives in tool arguments/results) — distill the
						# interaction instead: the user message (where standing
						# rules are stated) plus the trace's tool activity. The
						# user part leads so a durable rule survives the
						# distiller's input cap even when the tool payloads are
						# long; without any tool activity there was no agent
						# interaction, so memory is skipped as before.
						memory_src = result.output
						if not str(memory_src or "").strip():
							trace_text = _memory_output_from_trace(result.trace)
							if trace_text:
								memory_src = (
									f"[User message]\n{str(user_prompt or '')[:3000]}\n\n"
									f"[Agent tool activity]\n{trace_text}"
								)
						_distill_model = _memory_model(
							task_cfg, "aiMemoryDistillModel", config.model
						)
						_reconcile_model = _memory_model(
							task_cfg, "aiMemoryReconcileModel", config.model
						)
						_enqueue_distill(
							agent_output=memory_src,
							agent=(task_cfg.get("aiMemoryAgentElement") or bpmn_id),
							scope=scope,
							scope_key=scope_key,
							# The provider that serves the DISTILL model, not the
							# agent's — they are the same for an agent using its
							# own model and different the moment somebody picks a
							# memory model from another provider.
							provider_name=_provider_for_model(
								_distill_model, config.provider_name
							),
							backend=config.backend,
							model=_distill_model,
							reconcile_model=_reconcile_model,
							reconcile_provider=_provider_for_model(
								_reconcile_model, config.provider_name
							),
							source_run=src,
						)
			except Exception:
				frappe.log_error(
					title=f"BPMN AI Agent Task: memory write failed ({bpmn_id})",
					message=frappe.get_traceback(),
				)

		# ── Conversation store: append user + assistant turns (optional) ─
		# Primarily for the multi-turn loop; when a backend is configured we
		# record this single call's turns. process_variable uses the live task.
		cs_backend = task_cfg.get("aiConversationStore") or ""
		if cs_backend:
			try:
				from one_bpmn.agents.memory.conversation_store import get_conversation_store
				store = get_conversation_store(cs_backend, task=task)
				store.append(instance.name, bpmn_id, {"role": "user", "content": user_prompt})
				store.append(instance.name, bpmn_id, {"role": "assistant", "content": str(result.output or "")})
			except Exception:
				frappe.log_error(
					title=f"BPMN AI Agent Task: conversation store append failed ({bpmn_id})",
					message=frappe.get_traceback(),
				)
	else:
		error_code_name = result.error_code.value
		# The run FAILED, so it is no longer waiting for anybody. Clearing the
		# marker matters most on a resume: the marker survives from the original
		# suspension, and leaving it made the caller re-spawn the human task off
		# it — a second row bound to a run that is now Errored, not Suspended, so
		# completing it answered "No suspended AI agent is waiting on this task"
		# and the flow could never move. Observed live.
		if isinstance(task.data, dict):
			task.data.pop("_bpmn_ai_waiting_human", None)
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

		# Without aiStopOnError the flow continues past the failed task, so
		# the declared output variable must still exist (as None) — otherwise
		# a downstream gateway condition referencing it dies on a NameError
		# instead of routing to its default branch.
		output_var = task_cfg.get("aiOutputVariable") or f"{bpmn_id}_output"
		task.data.setdefault(output_var, None)

		# If the BPMN task is configured to stop on error, raise so the
		# engine loop in _run_engine_steps halts and the instance is
		# marked Errored (same pattern as apply_workflow).
		if task_cfg.get("aiStopOnError"):
			raise Exception(
				f"AI Agent Task '{bpmn_id}' failed: "
				f"{error_code_name} — {result.error_message}"
			)
