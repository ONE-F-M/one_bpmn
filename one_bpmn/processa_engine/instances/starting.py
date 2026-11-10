# Copyright (c) 2026, one-fm and contributors
"""Start process instances, directly or by a message, and deliver messages to running ones."""

import frappe
from frappe import _

from one_bpmn.processa_engine.agent_runtime.job_limits import AI_AGENT_JOB_TIMEOUT
from one_bpmn.utils.session import as_user


def start_process(
	model_name: str,
	context_doctype: str = None,
	context_docname: str = None,
	initial_data: str = None,
) -> dict:
	"""Create and start a BPMN Process Instance; the engine runs the automated tasks and stops at the first User Task.
	Returns the instance name, its status and its first active tasks."""
	if not model_name:
		frappe.throw(_("model_name is required"))

	if not frappe.db.exists("BPMN Process Model", model_name):
		frappe.throw(_("Process model '{0}' not found").format(model_name))

	parsed_data = {}
	if initial_data:
		parsed_data = frappe.parse_json(initial_data) if isinstance(initial_data, str) else initial_data

	instance = frappe.new_doc("BPMN Process Instance")
	instance.process_model = model_name
	instance.status = "Active"
	instance.initiated_by = frappe.session.user
	instance.started_at = frappe.utils.now_datetime()
	if context_doctype:
		instance.context_doctype = context_doctype
	if context_docname:
		instance.context_docname = context_docname
	instance.insert(ignore_permissions=True)  # engine-owned instance row

	try:
		instance.start(initial_data=parsed_data)
	except frappe.ValidationError:
		# start() already carries a safe message; a caller that catches this must not see an Active row with no state.
		frappe.db.set_value(
			"BPMN Process Instance", instance.name, "status", "Errored", update_modified=False
		)
		raise
	except Exception:
		# Failures outside the engine seam are recorded and shown as a generic message, not a traceback.
		frappe.db.set_value(
			"BPMN Process Instance", instance.name, "status", "Errored",
			update_modified=False,
		)
		frappe.log_error(
			title=f"BPMN start_process failed - {instance.name}",
			message=frappe.get_traceback(),
		)
		frappe.throw(
			_("Failed to start process '{0}'. Please contact your administrator.").format(model_name)
		)

	return {
		"instance": instance.name,
		"status": instance.status,
		"active_tasks": instance.get_active_tasks_summary(),
	}


def start_process_async(
	model_name: str,
	context_doctype: str = None,
	context_docname: str = None,
	initial_data: str = None,
) -> dict:
	"""Queue start_process as a background job that runs as the caller."""
	if not model_name:
		frappe.throw(_("model_name is required"))

	if not frappe.db.exists("BPMN Process Model", model_name):
		frappe.throw(_("Process model '{0}' not found").format(model_name))

	frappe.enqueue(
		"one_bpmn.processa_engine.instances.starting._start_process_as_user",
		# A dedicated queue keeps AI selector loops off the shared queues; it must be in the bench workers config.
		queue="bpmn_ai_agent",
		model_name=model_name,
		context_doctype=context_doctype,
		context_docname=context_docname,
		initial_data=initial_data,
		run_as_user=frappe.session.user,
		is_async=True,
		timeout=AI_AGENT_JOB_TIMEOUT,
	)

	return {"status": "queued", "message": _("Process '{0}' queued for execution").format(model_name)}


def _start_process_as_user(
	model_name: str,
	context_doctype: str = None,
	context_docname: str = None,
	initial_data: str = None,
	run_as_user: str = None,
):
	"""Run start_process as run_as_user, then restore the job's original user."""
	with as_user(run_as_user):
		start_process(
			model_name=model_name,
			context_doctype=context_doctype,
			context_docname=context_docname,
			initial_data=initial_data,
		)


def trigger_process_by_message(
	message_name: str,
	payload: str = None,
	context_doctype: str = None,
	context_docname: str = None,
) -> dict:
	"""Queue a new instance of the one active map whose Message Start Event takes message_name, then deliver the message.
	Throws when no map or more than one map listens, rather than guessing."""
	if not message_name:
		frappe.throw(_("message_name is required"))

	listeners = _models_listening_for(message_name)

	if not listeners:
		frappe.throw(
			_("No active process is listening for the message '{0}'.").format(message_name)
		)
	if len(listeners) > 1:
		frappe.throw(
			_("{0} active processes listen for the message '{1}': {2}. Exactly one must.").format(
				len(listeners), message_name, ", ".join(sorted(listeners))
			)
		)

	model_name = listeners[0]

	# A Message Start Event parks the new instance until its message arrives, so start and deliver go together.
	frappe.enqueue(
		"one_bpmn.processa_engine.instances.starting.start_and_deliver_message",
		queue="bpmn_ai_agent",
		model_name=model_name,
		message_name=message_name,
		payload=payload,
		context_doctype=context_doctype,
		context_docname=context_docname,
		run_as_user=frappe.session.user,
		is_async=True,
		timeout=AI_AGENT_JOB_TIMEOUT,
	)

	return {
		"status": "queued",
		"model": model_name,
		"message_name": message_name,
		"message": _("Process '{0}' queued for execution").format(model_name),
	}


def start_and_deliver_message(
	model_name: str,
	message_name: str,
	payload: str = None,
	context_doctype: str = None,
	context_docname: str = None,
	run_as_user: str = None,
):
	"""Create the instance, then hand it the message that starts it, as the user who asked."""
	with as_user(run_as_user):

		started = start_process(
			model_name=model_name,
			context_doctype=context_doctype,
			context_docname=context_docname,
			initial_data=payload,
		)
		instance = frappe.get_doc("BPMN Process Instance", started["instance"])
		instance.receive_message(
			message_name=message_name,
			payload=frappe.parse_json(payload) if payload else {},
		)

		# receive_message returns quietly when nothing catches the message.
		if not instance.flags.get("bpmn_message_caught"):
			frappe.log_error(
				title=f"BPMN: '{message_name}' started {model_name} but nothing caught it",
				message=(
					f"Instance {instance.name} was created for model {model_name} "
					f"but its start event did not consume message '{message_name}'. "
					"The instance is left Active and will not progress."
				),
			)
		return instance.name


def _models_listening_for(message_name: str) -> list:
	"""Active models with a Message Start Event bound to ``message_name``."""
	return message_start_index().get((message_name or "").strip(), [])


def message_start_index() -> dict:
	"""Message name to the active maps a start event of theirs takes it on.
	Only a start event's messageRef counts, so a map that merely catches the message part-way is not listed."""
	from lxml import etree as ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	index = {}

	for name, xml in frappe.get_all(
		"BPMN Process Model",
		filters={"is_active": 1},
		fields=["name", "bpmn_xml"],
		as_list=True,
	):
		if not xml or "messageEventDefinition" not in xml:
			continue
		try:
			parser = ET.XMLParser(resolve_entities=False, no_network=True)
			root = ET.fromstring(xml.encode("utf-8"), parser=parser)
		except Exception:
			# The compiler already reports a diagram that will not parse.
			continue

		names_by_id = {
			el.get("id"): (el.get("name") or "").strip()
			for el in root.iter(f"{{{BPMN_NS}}}message")
			if el.get("id") and (el.get("name") or "").strip()
		}
		started_by = {
			names_by_id[med.get("messageRef")]
			for start in root.iter(f"{{{BPMN_NS}}}startEvent")
			for med in start.iter(f"{{{BPMN_NS}}}messageEventDefinition")
			if med.get("messageRef") in names_by_id
		}
		for message in started_by:
			index.setdefault(message, []).append(name)

	return index


def send_message(
	message_name: str,
	context_doctype: str = None,
	context_docname: str = None,
	instance_name: str = None,
	payload: str = None,
) -> dict:
	"""Deliver a BPMN message to instance_name, or to the one Active instance on the context document.
	Throws when nothing waits for the message; payload is a JSON string merged into the task data."""
	if not message_name:
		frappe.throw(_("message_name is required"))

	if not instance_name:
		if not context_doctype or not context_docname:
			frappe.throw(
				_("Either instance_name or both context_doctype and context_docname are required")
			)

		instances = frappe.get_all(
			"BPMN Process Instance",
			filters={
				"context_doctype": context_doctype,
				"context_docname": context_docname,
				"status": "Active",
			},
			pluck="name",
			limit=1,
		)
		if not instances:
			frappe.throw(
				_('No active BPMN instance found for {0} "{1}"').format(
					context_doctype, context_docname
				)
			)
		instance_name = instances[0]

	instance = frappe.get_doc("BPMN Process Instance", instance_name)
	instance.check_permission("write")

	parsed_payload = {}
	if payload:
		parsed_payload = frappe.parse_json(payload) if isinstance(payload, str) else payload

	try:
		active_tasks = instance.receive_message(
			message_name=message_name,
			payload=parsed_payload,
		)
	except frappe.ValidationError:
		raise
	except Exception as exc:
		frappe.db.set_value("BPMN Process Instance", instance_name, "status", "Errored")
		frappe.log_error(
			title="BPMN send_message failed",
			message=frappe.get_traceback(),
		)
		frappe.throw(_("Failed to deliver message: {0}").format(str(exc)))

	frappe.publish_realtime(
		"bpmn_instance_updated",
		{
			"instance_name": instance_name,
			"status": instance.status,
			"context_doctype": instance.context_doctype or "",
			"context_docname": instance.context_docname or "",
		},
		after_commit=True,
		user="all",
	)

	if instance.context_doctype and instance.context_docname:
		frappe.publish_realtime(
			"doc_update",
			{
				"modified": str(frappe.utils.now_datetime()),
				"doctype": instance.context_doctype,
				"name": instance.context_docname,
			},
			doctype=instance.context_doctype,
			docname=instance.context_docname,
			after_commit=True,
		)

	return {
		"instance": instance_name,
		"status": instance.status,
		"active_tasks": active_tasks,
		"caught": bool(instance.flags.get("bpmn_message_caught")),
	}
