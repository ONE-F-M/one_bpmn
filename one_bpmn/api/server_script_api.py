# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

import json
import re

import frappe
from frappe import _


# ============================================
# Server Script API
# Uses ignore_permissions so Process Owners without the Script Manager role
# can still list/create Server Scripts via the BPMN editor.
# Creation is guarded to System Manager or Script Manager only.
# ============================================


def _derive_api_method(script_name: str) -> str:
	"""Convert a script name to a valid Frappe API method identifier."""
	method = script_name.lower()
	method = re.sub(r"[^a-z0-9\s_]", "", method)
	method = re.sub(r"\s+", "_", method)
	method = re.sub(r"_+", "_", method).strip("_")
	return method or "script"


def _delegate_to_bpmn_instance(conversation_name: str, message: str, context: dict):
	"""Hand a chat turn to the BPMN Process Instance driving this conversation.

	The process map performs ALL the work: its ``Save User Message`` task persists
	the user message, ``Call Agent`` runs the agent, ``Save Response`` persists the
	reply. This function only delivers the ``ChatConversation_Message_Action``
	trigger (carrying the user text + editor context) to the instance parked at its
	"Waiting for User Message" gateway, then reads back the reply the map produced
	so it can be returned over HTTP.

	Returns ``None`` when no instance is driving the conversation (or it is not
	currently waiting) — the orchestration is the only execution path, so callers
	surface an error rather than running the agent themselves.
	"""
	import json

	inst = frappe.db.get_value(
		"BPMN Process Instance",
		{
			"context_doctype": "Chat Conversation",
			"context_docname": conversation_name,
			"status": ["in", ["Active", "Queued"]],
		},
		["name", "status"],
		as_dict=True,
	)
	if not inst:
		return None
	inst_name = inst.name

	# A brand-new conversation spawns its BPMN instance via a doc-event hook that
	# enqueues the first engine pass on the bpmn_ai_agent worker (async). The very
	# first chat turn arrives in THIS request — before the worker has promoted the
	# instance from "Queued" to "Active" — so the wait gateway isn't armed yet and
	# the message can't be delivered. Start it inline here to close that race. This
	# is idempotent with the background job: start_queued_instance() locks the row
	# (for_update) and no-ops when the status is no longer "Queued", so whichever
	# runs first wins and the other returns immediately.
	if inst.status == "Queued":
		try:
			from one_bpmn.one_bpmn.trigger import start_queued_instance

			start_queued_instance(inst_name)
		except Exception:
			frappe.log_error(title="BPMN inline start failed", message=frappe.get_traceback())
		if frappe.db.get_value("BPMN Process Instance", inst_name, "status") != "Active":
			# Start failed (Errored) or is still being started elsewhere — the
			# caller surfaces the "reopen the chat" message rather than guessing.
			return None

	payload = {
		"user_text": message,
		"sender": frappe.session.user,
	}
	payload.update({k: v for k, v in (context or {}).items() if v not in (None, "")})

	# Run the agent INLINE for this turn instead of parking it on the
	# bpmn_ai_agent worker. The chat endpoint is an explicit waiter: the
	# frontend expects the reply in this HTTP response, so the "Run <Agent>"
	# AI task must execute (and "Save Response" must persist the bot message)
	# before the read-back below. Without this the agent parks async, the
	# read-back finds no fresh bot message, and the caller wrongly surfaces
	# "reopen the chat" even though the instance is running normally.
	prev_parking_flag = getattr(frappe.flags, "bpmn_disable_ai_parking", False)
	frappe.flags.bpmn_disable_ai_parking = True
	try:
		instance = frappe.get_doc("BPMN Process Instance", inst_name)
		instance.receive_message("ChatConversation_Message_Action", payload=payload)
	except frappe.ValidationError:
		# Instance is not currently waiting for a message.
		return None
	except Exception:
		frappe.log_error(title="BPMN chat delegation failed", message=frappe.get_traceback())
		return None
	finally:
		frappe.flags.bpmn_disable_ai_parking = prev_parking_flag

	# Read back the bot message the instance produced during Call Agent → Save Response.
	rows = frappe.get_all(
		"Chat Message",
		filters={"conversation": conversation_name, "message_type": "Bot"},
		fields=["text", "metadata"],
		order_by="creation desc",
		limit=1,
	)
	if not rows:
		return None

	meta = {}
	if rows[0].get("metadata"):
		try:
			meta = json.loads(rows[0]["metadata"])
		except Exception:
			meta = {}

	agent_result = meta.get("agent_result")
	result = dict(agent_result) if isinstance(agent_result, dict) else {}
	result.setdefault("response", rows[0]["text"])
	result.setdefault("intent", meta.get("intent"))
	result["bpmn_driven"] = True
	return result


def delegate_chat_turn(conversation_name: str, message: str, context: dict = None):
	"""Public entry point for other apps (e.g. the Lumina Desk page in onefm_mcp)
	to hand a chat turn to the BPMN Process Instance driving a conversation.

	Delivers ``ChatConversation_Message_Action`` to the instance parked at its
	"Waiting for User Message" gateway and returns the result the map produced
	(``response`` plus ``bpmn_driven=True``). Returns ``None`` when no instance
	is driving the conversation, so callers can fall back to their own pipeline.

	Pass ``context["message_name"]`` when the caller already persisted the user
	Chat Message — the map's "Save User Message" task then reuses it instead of
	inserting a duplicate.
	"""
	return _delegate_to_bpmn_instance(conversation_name, message, context or {})


@frappe.whitelist()
def create_server_script(
	script_name: str,
	script_type: str,
	script: str,
	reference_doctype: str = None,
	doctype_event: str = None,
	api_method: str = None,
	allow_guest: int = 0,
	event_frequency: str = None,
	cron_format: str = None,
	module: str = None,
) -> dict:
	if not script_name or not script_type or not script:
		frappe.throw(_("Script name, type, and content are required"))

	if not frappe.has_permission("Server Script", "create") and "System Manager" not in frappe.get_roles():
		frappe.throw(
			_("You need the Script Manager or System Manager role to create Server Scripts."),
			frappe.PermissionError,
		)

	doc = frappe.new_doc("Server Script")
	doc.__newname = script_name
	doc.script_type = script_type
	doc.script = script
	doc.disabled = 0  # enabled by default
	if reference_doctype:
		doc.reference_doctype = reference_doctype
	if doctype_event:
		doc.doctype_event = doctype_event
	# For API scripts, always set an api_method so Processa can reach it via REST
	if script_type == "API":
		resolved_method = api_method or _derive_api_method(script_name)
		doc.api_method = resolved_method
	elif api_method:
		doc.api_method = api_method
	if allow_guest:
		doc.allow_guest = int(allow_guest)
	if event_frequency:
		doc.event_frequency = event_frequency
	if cron_format:
		doc.cron_format = cron_format
	if module:
		doc.module = module

	original_user = frappe.session.user
	try:
		frappe.set_user("Administrator")
		if frappe.db.exists("Server Script", script_name):
			# Script already exists — update in place instead of re-inserting
			doc = frappe.get_doc("Server Script", script_name)
			doc.script_type = script_type
			doc.script = script
			doc.disabled = 0
			if reference_doctype is not None:
				doc.reference_doctype = reference_doctype
			if doctype_event is not None:
				doc.doctype_event = doctype_event
			if script_type == "API":
				resolved_method = api_method or _derive_api_method(script_name)
				doc.api_method = resolved_method
			elif api_method is not None:
				doc.api_method = api_method
			if allow_guest is not None:
				doc.allow_guest = int(allow_guest)
			if event_frequency is not None:
				doc.event_frequency = event_frequency
			if cron_format is not None:
				doc.cron_format = cron_format
			if module is not None:
				doc.module = module
			doc.save(ignore_permissions=True)
		else:
			doc.insert(ignore_permissions=True)
	finally:
		frappe.set_user(original_user)

	method = getattr(doc, "api_method", None) or ""
	return {
		"name":        doc.name,
		"script_type": doc.script_type,
		"api_method":  method,
		"api_url":     f"/api/method/{method}" if method else "",
	}


@frappe.whitelist()
def update_server_script(
	script_name: str,
	script: str,
	script_type: str = None,
	reference_doctype: str = None,
	doctype_event: str = None,
	api_method: str = None,
	allow_guest: int = None,
	event_frequency: str = None,
	cron_format: str = None,
	module: str = None,
) -> dict:
	"""Replace the script body (and optionally metadata) of an existing Server Script."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required"))

	if not frappe.has_permission("Server Script", "write") and "System Manager" not in frappe.get_roles():
		frappe.throw(
			_("You need the Script Manager or System Manager role to update Server Scripts."),
			frappe.PermissionError,
		)

	try:
		doc = frappe.get_doc("Server Script", script_name)
		doc.script = script
		if script_type:
			doc.script_type = script_type
		if reference_doctype is not None:
			doc.reference_doctype = reference_doctype
		if doctype_event is not None:
			doc.doctype_event = doctype_event
		if api_method is not None:
			doc.api_method = api_method
		if allow_guest is not None:
			doc.allow_guest = int(allow_guest)
		if event_frequency is not None:
			doc.event_frequency = event_frequency
		if cron_format is not None:
			doc.cron_format = cron_format
		if module is not None:
			doc.module = module
		original_user = frappe.session.user
		try:
			frappe.set_user("Administrator")
			doc.save(ignore_permissions=True)
		finally:
			frappe.set_user(original_user)
		method = doc.api_method or ""
		return {
			"name":        doc.name,
			"script_type": doc.script_type,
			"api_method":  method,
			"api_url":     f"/api/method/{method}" if method else "",
		}
	except frappe.DoesNotExistError:
		frappe.throw(_("Server Script '{0}' not found.").format(script_name))
	except Exception:
		frappe.log_error(title="Update Server Script Error", message=frappe.get_traceback())
		frappe.throw(_("Failed to update Server Script."))


@frappe.whitelist()
def check_server_script_exists(script_name: str) -> dict:
	"""Check if a Server Script document with the given name exists."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required"))
	return {"exists": bool(frappe.db.exists("Server Script", script_name))}


@frappe.whitelist()
def process_logix_message(
	message: str,
	session_id: str,
	conversation_name: str = None,
	chat_history: str = None,
	element_name: str = None,
	current_script: str = None,
	process_context: dict = None,
) -> dict:
	"""Route a Logix chat turn through the generic agent path (WI-001539).

	Logix chat is no longer orchestrated here: this endpoint is a thin alias
	that opens the conversation with ``create_agent_conversation`` and hands the
	turn to ``invoke_agent("logix_agent", …)``, exactly like every other
	configured agent. Its only remaining job is the editor's request/response
	contract — the parameters the LogixCanvas panel sends and the
	``{intent, response, conversation_name}`` reply it consumes. Because the
	``logix`` configuration links the Logix process map, ``invoke_agent`` selects
	the ``bpmn_map`` runner and the map still performs all the work (Save User
	Message → Call Agent → Save Response), so behavior is unchanged.

	The Server Script CRUD + test-runner endpoints in this module are Logix
	*tooling*, not chat, and are intentionally left untouched.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required"))

	try:
		from one_bpmn.api.agent_invocation import invoke_agent
		from one_bpmn.utils.chat_persistence import create_agent_conversation

		# Open the conversation on the first turn. Inserting the Chat Conversation
		# (stamped with the agent's chat mode label — "Logix") arms the process
		# map's conditional start trigger, which spawns the orchestrating BPMN
		# instance parked at "Waiting for User Message". Created here (rather than
		# letting invoke_agent create it) to preserve the "Logix: <label>" title.
		if not conversation_name:
			label = element_name or "Script Task"
			conversation_name = create_agent_conversation(
				"logix_agent", title=f"Logix: {label}", user=frappe.session.user
			)

		# Gather the editor inputs the Logix agent needs (the original script body
		# is used for MODIFY diffs). These are delivered to the map as context.
		# A linked script that cannot be READ must NOT be silently swallowed — that
		# leaves the agent with no code and it fabricates a fresh, unrelated one.
		# Surface the real reason to the user instead. (frappe.get_doc does not
		# enforce read permission, so check it explicitly; Server Script read is
		# limited to Script Manager — System Manager is allowed too, matching the
		# create/update endpoints above.)
		original_content = ""
		if current_script:
			if not (
				frappe.has_permission("Server Script", "read", doc=current_script)
				or "System Manager" in frappe.get_roles()
			):
				frappe.log_error(
					title="Logix: no permission to read linked Server Script",
					message=f"user={frappe.session.user} script={current_script}",
				)
				return {
					"intent": "ERROR",
					"response": _(
						"A script named '{0}' is linked here, but you don't have permission to read it, "
						"so I can't safely modify it. You likely need the Script Manager role (or an admin's "
						"help) to let Logix access it."
					).format(current_script),
					"conversation_name": conversation_name,
				}
			try:
				original_content = frappe.get_doc("Server Script", current_script).script or ""
			except frappe.DoesNotExistError:
				frappe.log_error(
					title="Logix: linked Server Script not found",
					message=f"script={current_script}",
				)
				return {
					"intent": "ERROR",
					"response": _(
						"I couldn't find the linked script '{0}' — it may not be saved yet. "
						"Please save it first, then ask me to modify it."
					).format(current_script),
					"conversation_name": conversation_name,
				}
			except Exception:
				frappe.log_error(
					title="Logix: failed to load linked Server Script",
					message=frappe.get_traceback(),
				)
				return {
					"intent": "ERROR",
					"response": _(
						"I couldn't load the existing script to modify it. Please try again; if it keeps "
						"happening, ask an admin to check the Error Log."
					),
					"conversation_name": conversation_name,
				}

		# Normalise shape_kind server-side. The editor labels the element, but the
		# authoritative rule is the parent shape's type: an element inside an
		# ad-hoc sub-process is an Agent Tool (shape_tools synthetic-task contract),
		# anything else is a Script Task (engine contract). Re-derive from
		# parent_type when available so a stale client label can't mislabel the
		# script contract Logix writes to.
		process_context = process_context or {}
		if isinstance(process_context, str):
			try:
				process_context = json.loads(process_context)
			except Exception:
				process_context = {}
		parent_type = (process_context.get("parent_type") or "").strip()
		if parent_type:
			process_context["shape_kind"] = (
				"agent_tool" if parent_type == "AdHocSubProcess" else "script_task"
			)
		elif process_context.get("shape_kind") not in ("agent_tool", "script_task"):
			process_context["shape_kind"] = "script_task"

		try:
			result = invoke_agent(
				"logix_agent",
				message,
				conversation=conversation_name,
				context={
					"element_name": element_name or "",
					"current_script": current_script or "",
					"original_script_content": original_content,
					"process_context": process_context,
				},
			)
		except frappe.ValidationError:
			# No instance is driving this conversation (map never armed or the
			# instance died) — the generic runner throws; surface the same
			# reopen guidance the editor showed before, over a 200 response.
			return {
				"intent": "ERROR",
				"response": "The Logix process orchestration isn't running for this conversation. Please reopen the chat.",
				"conversation_name": conversation_name,
			}

		# The editor keys on ``conversation_name``; invoke_agent returns ``conversation``.
		result["conversation_name"] = result.get("conversation") or conversation_name
		return result

	except Exception:
		frappe.log_error(title="Logix Agent error", message=frappe.get_traceback())
		return {"intent": "ERROR", "response": "An unexpected error occurred. Please try again."}


@frappe.whitelist()
def run_logix_test_case(script_name: str, inputs: str = "{}") -> dict:
	"""Execute a Server Script the way the BPMN engine runs a Script Task and
	return a plain-English pass/fail result.

	Logix scripts are written against the engine's injected-variable contract
	(doc / task_data / result; form_dict always empty — see
	fix_logix_script_task_injected_vars), so the earlier execute_method()
	replay failed EVERY check with a NameError on `doc` before the script's
	logic ever ran. The namespace below mirrors engine._run_server_script;
	the one deliberate difference is the savepoint — a check is a dry run,
	so its writes are rolled back instead of landing a real record per click.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required"))

	try:
		import json as _json
		test_inputs = _json.loads(inputs) if isinstance(inputs, str) else (inputs or {})
		if not isinstance(test_inputs, dict):
			test_inputs = {}

		script_doc = frappe.get_doc("Server Script", script_name)
		if script_doc.script_type != "API":
			return {"passed": False, "result": None, "summary": "This script is not an API-type script and cannot be run as a test."}

		from one_bpmn.one_bpmn.engine import _check_script_permissions

		_check_script_permissions(script_doc.script, script_name)

		context_doctype = str(test_inputs.get("context_doctype") or "")
		context_docname = str(test_inputs.get("context_docname") or "")
		doc_obj = frappe._dict()
		if context_doctype and context_docname:
			try:
				doc_obj = frappe.get_doc(context_doctype, context_docname)
			except Exception:
				doc_obj = frappe._dict()
		# A case may carry sample field values instead of a real record —
		# inputs["doc"] becomes the context document, so negative paths
		# ("employee missing") are testable without seeding the site.
		if isinstance(test_inputs.get("doc"), dict):
			doc_obj = frappe._dict(test_inputs["doc"])

		task_data = {k: v for k, v in test_inputs.items() if k != "doc"}
		result_dict = {}
		# ONE namespace for globals and locals, same as the engine — separate
		# dicts break scripts whose top-level functions call each other.
		exec_ns = {"frappe": frappe, "__builtins__": __builtins__}
		exec_ns.update(task_data)
		exec_ns.update(
			{
				"frappe": frappe,
				"task_data": dict(task_data),
				"context_doctype": context_doctype,
				"context_docname": context_docname,
				"result": result_dict,
				"doc": doc_obj,
			}
		)

		frappe.db.savepoint("logix_check")
		try:
			exec(script_doc.script, exec_ns)  # noqa: S102
			summary = "It worked — the script ran without any problems."
			if result_dict:
				# Describe the result in plain English without exposing key names
				count = len(result_dict)
				summary = f"It worked — the script completed and sent back {count} piece{'s' if count != 1 else ''} of information."
			return {"passed": True, "result": result_dict, "summary": summary}

		except Exception as exc:
			error_msg = str(exc)
			# frappe.throw() raises ValidationError — this is often an *expected* negative result
			is_validation = "ValidationError" in type(exc).__name__ or hasattr(exc, "http_status_code")
			if is_validation:
				return {
					"passed": False,
					"result": None,
					"summary": f"The script stopped and said: \"{error_msg}\"",
				}
			return {
				"passed": False,
				"result": None,
				"summary": "Something went wrong while running the script. You can ask Logix \"why did this test fail?\" for help.",
			}
		finally:
			# Dry run: whatever the script inserted or updated is undone.
			frappe.db.rollback(save_point="logix_check")

	except Exception:
		frappe.log_error(title="Logix Test Runner error", message=frappe.get_traceback())
		return {"passed": False, "result": None, "summary": "Could not run the test right now. Please try again in a moment."}


@frappe.whitelist()
def prosally_chat(
	message: str,
	session_id: str,
	conversation_name: str = None,
	chat_history: str = None,
	process_name: str = "",
	diagram_name: str = "",
	confirmed_action: str = "",
	current_xml: str = "",
) -> dict:
	"""Route a ProsAlly chat turn through the generic agent path (WI-001539).

	ProsAlly chat is no longer orchestrated here: this endpoint is a thin alias
	that opens the conversation with ``create_agent_conversation`` and hands the
	turn to ``invoke_agent("prosally_agent", …)``, exactly like every other
	configured agent (and like ``process_logix_message``). Its only remaining job
	is the ProsAlly panel's request/response contract — the editor state it sends
	and the ``{intent, response, conversation_name, bpmn_xml, …}`` reply it
	consumes. Because the ``prosally`` configuration links the ProsAlly process
	map, ``invoke_agent`` selects the ``bpmn_map`` runner and the map still
	performs all the work (Save User Message → Call Agent → Save Response), so
	behavior is unchanged. All ProsAlly tools live in the map's ad-hoc Tools
	sub-process; no backend agent code remains.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required"))

	try:
		from one_bpmn.api.agent_invocation import invoke_agent
		from one_bpmn.utils.chat_persistence import create_agent_conversation

		# Open the conversation on the first turn. Inserting the Chat Conversation
		# (stamped with the agent's chat mode label — "ProsAlly") arms the process
		# map's conditional start trigger, which spawns the orchestrating BPMN
		# instance parked at "Waiting for User Message". Created here (rather than
		# letting invoke_agent create it) to preserve the "ProsAlly: <label>" title.
		if not conversation_name:
			label = process_name or diagram_name or "Process"
			conversation_name = create_agent_conversation(
				"prosally_agent", title=f"ProsAlly: {label}", user=frappe.session.user
			)

		try:
			result = invoke_agent(
				"prosally_agent",
				message,
				conversation=conversation_name,
				context={
					"process_name": process_name or "",
					"diagram_name": diagram_name or "",
					"confirmed_action": confirmed_action or "",
					"current_xml": current_xml or "",
				},
			)
		except frappe.ValidationError:
			# No instance is driving this conversation (map never armed or the
			# instance died) — the generic runner throws; surface the same reopen
			# guidance the panel showed before, over a 200 response.
			return {
				"intent": "ERROR",
				"response": "The ProsAlly process orchestration isn't running for this conversation. Please reopen the chat.",
				"conversation_name": conversation_name,
			}

		# The panel keys on ``conversation_name``; invoke_agent returns ``conversation``.
		result["conversation_name"] = result.get("conversation") or conversation_name
		return result

	except Exception:
		frappe.log_error(title="ProsAlly Agent error", message=frappe.get_traceback())
		return {"intent": "ERROR", "response": "An unexpected error occurred. Please try again."}


@frappe.whitelist()
def end_chat_conversation(conversation_name: str) -> dict:
	"""Close a Logix/ProsAlly chat conversation when its panel is closed.

	Marks the Chat Conversation as Closed and, if a BPMN Process Instance is
	driving it, delivers ``ChatConversation_Close_Action`` so the diagram runs
	its close branch (Cleanup → Conversation Ended) and the instance completes.

	Safe to call repeatedly / with an unknown name — it never raises.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required"))

	if not conversation_name:
		return {"ok": False}

	try:
		from one_bpmn.utils.chat_persistence import close_conversation
		close_conversation(conversation_name)
		return {"ok": True, "conversation_name": conversation_name}
	except Exception:
		frappe.log_error(title="end_chat_conversation error", message=frappe.get_traceback())
		return {"ok": False}


@frappe.whitelist()
def toggle_server_script(script_name: str, disabled: int) -> dict:
	"""Toggle the disabled status of a Server Script record."""
	if not script_name:
		frappe.throw(_("Script name is required"))

	# Permission check: Script Manager or System Manager
	if not frappe.has_permission("Server Script", "write") and "System Manager" not in frappe.get_roles():
		frappe.throw(
			_("You need the Script Manager or System Manager role to toggle Server Scripts."),
			frappe.PermissionError,
		)

	# Use set_value to bypass ServerScript validation logic which checks for
	# exactly the 'Script Manager' role. The has_permission check above
	# already proves the current user is authorized (e.g. System Manager).
	frappe.db.set_value(
		"Server Script",
		script_name,
		"disabled",
		int(disabled),
		update_modified=True
	)

	return {"name": script_name, "disabled": int(disabled)}


# ── Shared-endpoint integration (WI-001677) ──────────────────────────────────
def build_logix_turn_context(context: dict) -> dict:
	"""Load the linked script's content for a Logix turn (context builder for
	the AG-UI endpoint). The legacy process_logix_message did this inline —
	permission-checked — before invoking; through the shared endpoint the
	panel sends only the script NAME, and without the content the map's
	prompt renders empty and the model asks the user to paste their script
	(observed live, 2026-08-08).

	The reply contract is appended on EVERY turn, linked script or not: the
	agent's seeded system prompt does not carry it, and the CREATE-from-
	scratch turn (no script linked yet) is exactly where the model must know
	to answer in JSON — an early return here left it replying in prose, so
	no onefm.script_diff card and no Apply button (observed live,
	2026-08-09)."""
	out = dict(context or {})
	script = out.get("current_script") or ""
	content = None
	if script:
		if not frappe.db.exists("Server Script", script):
			out["current_script"] = ""
		elif not frappe.has_permission("Server Script", "read", doc=script):
			frappe.log_error(
				title="Logix: script read denied for turn context",
				message=f"user={frappe.session.user} script={script}",
			)
			out["current_script"] = ""
		else:
			content = frappe.get_doc("Server Script", script).script or ""
			out["original_script_content"] = content

	# Two map generations exist: the purpose-built Logix map renders the
	# original_script_content variable directly, while a generic
	# chat-template clone renders only {{ dialog_context }}. Folding the
	# script and the reply contract into dialog_context serves both — the
	# purpose-built map just sees it twice, harmlessly.
	parts = []
	if content is not None:
		parts.append("CURRENT SERVER SCRIPT ('%s'):\n```python\n%s\n```" % (script, content))
	parts.append(
		"LOGIX REPLY CONTRACT: respond ONLY with a JSON object: "
		'{"intent": "CREATE"|"MODIFY"|"DISAMBIGUATE"|"GENERAL", '
		'"response": "<short human explanation>", '
		'"modified_script": "<the full updated script when intent is CREATE or MODIFY>", '
		'"suggested_name": "<script name for CREATE>", '
		'"options": ["..."] }. '
		"Never claim you saved or applied anything — the designer applies your "
		"proposal from a review card in the UI."
	)
	existing = out.get("dialog_context") or ""
	out["dialog_context"] = (existing + "\n\n" + "\n\n".join(parts)).strip()
	return out


def shape_logix_reply(result: dict) -> dict:
	"""Lift the Logix JSON contract out of a text reply (reply shaper).

	The purpose-built map returns structured keys already — then this is a
	no-op. A generic-template map returns the contract as text; parse it so
	the translator can emit onefm.script_diff and no JSON reaches a bubble."""
	if result.get("modified_script") or result.get("intent"):
		return result
	from one_bpmn.api.ai_assistant import _extract_json

	raw = result.get("response") or ""
	parsed = _extract_json(raw if isinstance(raw, str) else "")
	if not isinstance(parsed, dict) or not (parsed.get("intent") or parsed.get("modified_script")):
		return result
	shaped = dict(result)
	shaped["response"] = str(parsed.get("response") or "").strip() or raw
	for key in ("intent", "modified_script", "suggested_name", "options", "apply_target"):
		if parsed.get(key):
			shaped[key] = parsed[key]
	return shaped


def build_prosally_turn_context(context: dict) -> dict:
	"""Fold the live canvas XML and the ProsAlly reply contract into
	dialog_context (context builder, WI-001675) — same dual-generation
	strategy as Logix: the purpose-built map renders its own variables, a
	generic chat-template clone renders only {{ dialog_context }}."""
	out = dict(context or {})
	current_xml = out.get("current_xml") or ""
	contract = (
		("CURRENT PROCESS DIAGRAM (BPMN XML):\n```xml\n%s\n```\n\n" % current_xml if current_xml else "")
		+ "PROSALLY REPLY CONTRACT: respond ONLY with a JSON object: "
		'{"intent": "BPMN_GENERATED"|"BPMN_MODIFIED"|"CONFIRM_REMOVAL"|"CONFIRM"|"GENERAL", '
		'"response": "<short human explanation>", '
		'"bpmn_xml": "<the FULL updated BPMN XML when intent is BPMN_GENERATED or BPMN_MODIFIED>", '
		'"pending_xml": "<the full XML awaiting approval when intent is CONFIRM_REMOVAL>", '
		'"options": ["..."], "action_intent": "<the action a CONFIRM approves>" }. '
		"Never claim you changed the canvas — the designer reviews your "
		"proposal on a preview card and applies it from there."
	)
	existing = out.get("dialog_context") or ""
	out["dialog_context"] = (existing + "\n\n" + contract).strip()
	return out


def shape_prosally_reply(result: dict) -> dict:
	"""Lift the ProsAlly JSON contract out of a text reply (reply shaper);
	no-op when the purpose-built map already returned structured keys."""
	if result.get("bpmn_xml") or result.get("pending_xml") or result.get("intent"):
		return result
	from one_bpmn.api.ai_assistant import _extract_json

	raw = result.get("response") or ""
	parsed = _extract_json(raw if isinstance(raw, str) else "")
	if not isinstance(parsed, dict) or not (
		parsed.get("intent") or parsed.get("bpmn_xml") or parsed.get("pending_xml")
	):
		return result
	shaped = dict(result)
	shaped["response"] = str(parsed.get("response") or "").strip() or raw
	for key in ("intent", "bpmn_xml", "pending_xml", "options", "action_intent"):
		if parsed.get(key):
			shaped[key] = parsed[key]
	return shaped


def _register_agui_hooks():
	from one_bpmn.agents.agui_stream import (
		register_context_builder,
		register_reply_shaper,
	)

	register_context_builder("logix_agent", build_logix_turn_context)
	register_reply_shaper("logix_agent", shape_logix_reply)
	register_context_builder("prosally_agent", build_prosally_turn_context)
	register_reply_shaper("prosally_agent", shape_prosally_reply)


_register_agui_hooks()
