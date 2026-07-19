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
	"""Process a Logix AI chat message, persisting history in Chat Conversation."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required"))

	try:
		from one_bpmn.utils.chat_persistence import create_conversation

		# Create a new conversation on the first message. Inserting the Chat
		# Conversation triggers its process map, which spawns the orchestrating
		# BPMN instance (parked at "Waiting for User Message").
		if not conversation_name:
			label = element_name or "Script Task"
			conversation_name = create_conversation(
				agent_mode="Logix",
				title=f"Logix: {label}",
				user=frappe.session.user,
			)

		# Gather the editor inputs the Logix agent needs (the original script body
		# is used for MODIFY diffs). These are delivered to the map as context.
		original_content = ""
		if current_script:
			try:
				original_content = frappe.get_doc("Server Script", current_script).script or ""
			except Exception:
				pass

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

		# Hand the turn to the process map — it saves the user message, runs the
		# agent (Call Agent) and saves the reply. We only deliver + return.
		bpmn_result = _delegate_to_bpmn_instance(
			conversation_name,
			message,
			context={
				"element_name": element_name or "",
				"current_script": current_script or "",
				"original_script_content": original_content,
				"process_context": process_context or {},
			},
		)
		if bpmn_result is None:
			return {
				"intent": "ERROR",
				"response": "The Logix process orchestration isn't running for this conversation. Please reopen the chat.",
				"conversation_name": conversation_name,
			}

		bpmn_result["conversation_name"] = conversation_name
		return bpmn_result

	except Exception:
		frappe.log_error(title="Logix Agent error", message=frappe.get_traceback())
		return {"intent": "ERROR", "response": "An unexpected error occurred. Please try again."}


@frappe.whitelist()
def run_logix_test_case(script_name: str, inputs: str = "{}") -> dict:
	"""Execute a Server Script with test inputs and return a plain-English pass/fail result."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required"))

	try:
		import json as _json
		test_inputs = _json.loads(inputs) if isinstance(inputs, str) else (inputs or {})

		doc = frappe.get_doc("Server Script", script_name)
		if doc.script_type != "API":
			return {"passed": False, "result": None, "summary": "This script is not an API-type script and cannot be run as a test."}

		# Save and replace frappe.form_dict with test inputs
		original_form_dict = dict(frappe.form_dict)
		frappe.form_dict.clear()
		frappe.form_dict.update(test_inputs)

		# Clear any previous message so we can detect what the script sets
		frappe.response.pop("message", None)

		try:
			doc.execute_method()
			result = frappe.response.get("message")
			summary = "It worked — the script ran without any problems."
			if result and isinstance(result, dict) and result:
				# Describe the result in plain English without exposing key names
				count = len(result)
				summary = f"It worked — the script completed and sent back {count} piece{'s' if count != 1 else ''} of information."
			return {"passed": True, "result": result, "summary": summary}

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
			frappe.form_dict.clear()
			frappe.form_dict.update(original_form_dict)

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
	"""Process a ProsAlly chat message, persisting history in Chat Conversation."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required"))

	try:
		from one_bpmn.utils.chat_persistence import create_conversation

		# Create a new conversation on the first message. Inserting the Chat
		# Conversation triggers its process map, which spawns the orchestrating
		# BPMN instance (parked at "Waiting for User Message").
		if not conversation_name:
			label = process_name or diagram_name or "Process"
			conversation_name = create_conversation(
				agent_mode="ProsAlly",
				title=f"ProsAlly: {label}",
				user=frappe.session.user,
			)

		# Hand the turn to the process map — it saves the user message, runs the
		# agent (Call Agent) and saves the reply. We only deliver + return.
		bpmn_result = _delegate_to_bpmn_instance(
			conversation_name,
			message,
			context={
				"process_name": process_name or "",
				"diagram_name": diagram_name or "",
				"confirmed_action": confirmed_action or "",
				"current_xml": current_xml or "",
			},
		)
		if bpmn_result is None:
			return {
				"intent": "ERROR",
				"response": "The ProsAlly process orchestration isn't running for this conversation. Please reopen the chat.",
				"conversation_name": conversation_name,
			}

		bpmn_result["conversation_name"] = conversation_name
		return bpmn_result

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
