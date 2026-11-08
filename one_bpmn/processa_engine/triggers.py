# Copyright (c) 2026, one-fm and contributors
"""Universal Frappe doc_events handler that starts and advances BPMN process instances.

Also guards native submit and cancel on Processa-controlled documents, deletes linked instances on trash, and starts instances from messages."""

import frappe
from frappe.utils import now_datetime

# one_bpmn's own doctypes; Processa Legacy Migration is left out because its After Insert event starts a process.
_INTERNAL_DOCTYPES = frozenset(
	{
		"BPMN Process Model",
		"BPMN Process Instance",
		"BPMN Active Task",
		"BPMN Activity Log",
		"BPMN Process DocType",
		"Legacy Migration Error Log",
	}
)

_FRAPPE_TO_TRIGGER_EVENT = {
	"after_insert": "After Insert",
	"on_update": "On Update",
	"after_save": "After Save",
	"on_submit": "On Submit",
	"on_cancel": "On Cancel",
	"on_update_after_submit": "On Update After Submit",
	"validate": "Validate",
	"before_save": "Before Save",
	"before_submit": "Before Submit",
	"before_cancel": "Before Cancel",
}

# Frappe event to the User Task action it completes when the document changes outside the engine.
_FRAPPE_EVENT_TO_TASK_ACTION = {
	"on_submit": "Submit",
	"on_cancel": "Cancel"
}

# Suffix joined to the space-stripped DocType name to form the BPMN message, e.g. ToDo_Edit_Action.
_FRAPPE_EVENT_TO_MESSAGE_SUFFIX = {
	"on_update":   "Edit_Action",
	"after_save":  "Edit_Action",
}

_SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"
_BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"


def on_doc_event(doc, method: str):
	"""Start, advance and notify BPMN Process Instances for a Frappe document event.

	Wired to every doctype through hooks.py."""
	if getattr(frappe.flags, "in_migrate", False) \
	   or getattr(frappe.flags, "in_install", False) \
	   or getattr(frappe.flags, "in_patch", False) \
	   or getattr(frappe.flags, "in_setup_wizard", False):
		return

	if doc.doctype in _INTERNAL_DOCTYPES:
		return

	trigger_event = _FRAPPE_TO_TRIGGER_EVENT.get(method)
	if not trigger_event:
		return

	models = _find_matching_models(doc.doctype, trigger_event)
	for model_name in models:
		try:
			_maybe_start_instance(doc, model_name)
		except Exception:
			frappe.log_error(
				title=f"BPMN trigger failed for {doc.doctype} / {model_name}",
				message=frappe.get_traceback(),
			)

	task_action = _FRAPPE_EVENT_TO_TASK_ACTION.get(method)
	if task_action:
		_maybe_advance_instances(doc, task_action)

	message_suffix = _FRAPPE_EVENT_TO_MESSAGE_SUFFIX.get(method)
	if message_suffix:
		_maybe_send_message(doc, message_suffix)


def _maybe_send_message(doc, message_suffix: str):
	"""
	Deliver a BPMN message to active instances when a document is edited.
	Builds message name as {DocType}_{suffix} and never blocks the save.
	"""

	# An instance started in this request is still in its creation flow, not waiting for edits.
	bpmn_created = frappe.flags.get("_bpmn_instances_just_started") or set()
	doc_id = f"{doc.doctype}:{doc.name}"
	if doc_id in bpmn_created:
		return

	# Frappe fires on_update and after_save back to back; deliver once per request.
	if not frappe.flags._bpmn_message_sent:
		frappe.flags._bpmn_message_sent = set()

	doc_key = f"{doc.doctype}:{doc.name}:{message_suffix}"
	if doc_key in frappe.flags._bpmn_message_sent:
		return
	frappe.flags._bpmn_message_sent.add(doc_key)

	# Must match a <bpmn:message name="..."> in the diagram.
	doctype_clean = doc.doctype.replace(" ", "")
	message_name = f"{doctype_clean}_{message_suffix}"

	try:
		active_instances = frappe.get_all(
			"BPMN Process Instance",
			filters={
				"context_doctype": doc.doctype,
				"context_docname": doc.name,
				"status": "Active",
			},
			pluck="name",
		)
	except Exception:
		return

	# By on_update the DB holds the new value, so pass the old one; .get() since not every doctype has status.
	prev_doc = getattr(doc, "_doc_before_save", None)
	payload = {
		"triggered_by": frappe.session.user,
		"trigger_event": message_suffix,
	}
	if prev_doc:
		payload["_old_status"] = prev_doc.get("status")

	caught = False
	for instance_name in active_instances:
		try:
			instance = frappe.get_doc("BPMN Process Instance", instance_name)
			instance.receive_message(
				message_name=message_name,
				payload=payload,
			)
			caught = caught or bool(instance.flags.get("bpmn_message_caught"))
		except frappe.ValidationError:
			# Raised when no task waits for this message, which is normal for an active instance.
			pass
		except Exception:
			# Never block the document save.
			frappe.log_error(
				title=f"BPMN message delivery failed: {message_name} → {instance_name}",
				message=frappe.get_traceback(),
			)

	if not caught:
		_start_by_message(doc, message_name, payload)


# Follows the {DocType}{Action}_Action naming the diagrams already use.
PROCESS_MODEL_DEPLOYED_MESSAGE = "BPMNProcessModel_Deployed_Action"


def send_process_model_deployed_message(model) -> list:
	"""Deliver PROCESS_MODEL_DEPLOYED_MESSAGE to the Active instances of the model's process_implementation.
	Called from the deploy path because BPMN Process Model is internal and never reaches on_doc_event.
	Returns the instances that caught it; an empty list is normal and never fails the deploy."""
	implementation = (model.get("process_implementation") or "").strip()
	if not implementation:
		return []

	try:
		waiting = frappe.get_all(
			"BPMN Process Instance",
			filters={
				"context_doctype": "Process Implementation",
				"context_docname": implementation,
				"status": "Active",
			},
			pluck="name",
		)
	except Exception:
		# A lookup failure must not turn a good deploy into a failed one.
		frappe.log_error(
			title="BPMN deployed-message lookup failed",
			message=frappe.get_traceback(),
		)
		return []

	if not waiting:
		return []

	payload = {
		"process_model": model.name,
		"process_name": model.get("process_name"),
		"process_implementation": implementation,
		"version": model.get("version"),
		"deployed_by": model.get("deployed_by") or frappe.session.user,
		"deployed_at": str(model.get("deployed_at") or now_datetime()),
	}

	delivered = []
	for instance_name in waiting:
		try:
			instance = frappe.get_doc("BPMN Process Instance", instance_name)
			instance.receive_message(
				message_name=PROCESS_MODEL_DEPLOYED_MESSAGE,
				payload=payload,
			)
			# receive_message does not raise on an uncaught message, so this flag is the only signal.
			if instance.flags.get("bpmn_message_caught"):
				delivered.append(instance_name)
		except frappe.ValidationError:
			# The instance finished or was cancelled between the query and the delivery.
			pass
		except Exception:
			frappe.log_error(
				title=(
					f"BPMN message delivery failed: "
					f"{PROCESS_MODEL_DEPLOYED_MESSAGE} → {instance_name}"
				),
				message=frappe.get_traceback(),
			)

	return delivered


def _find_matching_models(doctype: str, trigger_event: str) -> list:
	"""Return active BPMN Process Models triggered by this doctype and event.

	Candidates come from BPMN Start Event Config and BPMN Process DocType rows."""
	child_matches = frappe.get_all(
		"BPMN Start Event Config",
		filters={
			"trigger_type": "DocType Event",
			"trigger_doctype": doctype,
			"trigger_event": trigger_event,
			"parenttype": "BPMN Process Model",
		},
		fields=["parent"],
	)
	candidate_names = [r.parent for r in child_matches if r.parent]

	multi_doc_matches = frappe.get_all(
		"BPMN Process DocType",
		filters={
			"doctype_name": doctype,
			"parenttype": "BPMN Process Model",
		},
		fields=["parent"],
	)
	candidate_names.extend([r.parent for r in multi_doc_matches if r.parent])

	if not candidate_names:
		return []

	active_models = frappe.get_all(
		"BPMN Process Model",
		filters={
			"name": ["in", list(set(candidate_names))],
			"is_active": 1,
		},
		pluck="name",
	)

	return active_models


def _maybe_start_instance(doc, model_name: str):
	"""
	Evaluate conditions for one model against the current document.
	Starts a new BPMN Process Instance only if all checks pass.
	"""
	model = frappe.get_doc("BPMN Process Model", model_name)

	if not model.serialized_spec:
		return

	# triggerWorkflowState matches either workflow_state or a custom status field.
	required_state = _get_trigger_workflow_state(model.bpmn_xml)
	if required_state:
		doc_state = getattr(doc, "workflow_state", None) or getattr(doc, "status", None)
		if doc_state != required_state:
			return

	# Same expression SpiffWorkflow evaluates at start; a condition that cannot be evaluated still spawns.
	start_condition = _get_conditional_start_condition(model.bpmn_xml)
	if start_condition and start_condition.strip().lower() not in ("true", "1", ""):
		from one_bpmn.processa_engine.engine import json_safe_doc_fields

		# Same fields the started instance sees, so a start condition and a gateway agree.
		eval_locals = json_safe_doc_fields(doc)
		try:
			if not frappe.safe_eval(start_condition, eval_locals=eval_locals):
				return
		except Exception:
			frappe.log_error(
				title=f"BPMN trigger: start-condition eval failed ({model_name})",
				message=f"condition={start_condition!r}\n{frappe.get_traceback()}",
			)

	field_cond = _get_trigger_field_condition(model.bpmn_xml)
	if field_cond:
		field_name, field_value = field_cond
		if str(getattr(doc, field_name, None) or "") != str(field_value):
			return

	existing = frappe.db.exists(
		"BPMN Process Instance",
		{
			"process_model": model_name,
			"context_doctype": doc.doctype,
			"context_docname": doc.name,
			"status": ["in", ["Queued", "Active"]],
		},
	)
	if existing:
		return

	# The first engine pass runs inline; AI tasks it reaches are parked so the save never waits on an LLM.
	instance = frappe.new_doc("BPMN Process Instance")
	instance.process_model = model_name
	instance.context_doctype = doc.doctype
	instance.context_docname = doc.name
	# The start below only runs start() on a Queued row; start() sets Active once workflow_state exists.
	instance.status = "Queued"
	instance.initiated_by = frappe.session.user
	instance.started_at = now_datetime()
	instance.insert(ignore_permissions=True)  # the engine owns instance rows

	# Set before start(), whose script tasks may save the doc and send Edit_Action.
	if not frappe.flags._bpmn_instances_just_started:
		frappe.flags._bpmn_instances_just_started = set()
	frappe.flags._bpmn_instances_just_started.add(f"{doc.doctype}:{doc.name}")

	start_queued_instance(instance.name, run_as_user=frappe.session.user)


def start_queued_instance(instance_name: str, run_as_user: str = None):
	"""Run the first engine pass of a Queued instance, inline in the save request.

	Standalone so a job can still start a stranded Queued instance."""
	instance = frappe.get_doc("BPMN Process Instance", instance_name, for_update=True)
	if instance.status != "Queued":
		return  # already started or cancelled elsewhere
	# set_user wipes session.data, which a web request then writes back under the cookie sid; switch only when needed.
	if run_as_user and run_as_user != frappe.session.user:
		frappe.set_user(run_as_user)

	# Script tasks inside start() may save the context doc and self-deliver Edit_Action.
	if not frappe.flags._bpmn_instances_just_started:
		frappe.flags._bpmn_instances_just_started = set()
	frappe.flags._bpmn_instances_just_started.add(
		f"{instance.context_doctype}:{instance.context_docname}"
	)

	instance.status = "Active"
	try:
		instance.start(
			initial_data={
				"triggered_by": run_as_user or frappe.session.user,
				"trigger_doctype": instance.context_doctype,
				"trigger_docname": instance.context_docname,
			}
		)
	except Exception:
		frappe.db.set_value("BPMN Process Instance", instance_name, "status", "Errored")
		frappe.log_error(
			title=f"BPMN queued start failed: {instance_name}",
			message=frappe.get_traceback(),
		)
	finally:
		frappe.publish_realtime(
			"bpmn_instance_updated",
			{
				"instance_name": instance_name,
				"status": frappe.db.get_value("BPMN Process Instance", instance_name, "status"),
				"context_doctype": instance.context_doctype or "",
				"context_docname": instance.context_docname or "",
			},
			after_commit=True,
			user="all",
		)



def _maybe_advance_instances(doc, task_action: str):
	"""Complete the Waiting User Task that accepts task_action on each Active instance of doc.

	Runs when the document changes outside the engine; failures are logged and never block the save."""
	# A save raised by the engine's own service task would advance the running instance a second time from its stale persisted state.
	if frappe.flags.bpmn_engine_action:
		return
	try:
		active_instances = frappe.get_all(
			"BPMN Process Instance",
			filters={
				"context_doctype": doc.doctype,
				"context_docname": doc.name,
				"status": "Active",
			},
			pluck="name",
		)
	except Exception:
		return

	for instance_name in active_instances:
		try:
			_advance_instance_on_doc_event(instance_name, task_action)
		except Exception:
			frappe.log_error(
				title=f"BPMN auto-advance failed for instance {instance_name}",
				message=frappe.get_traceback(),
			)


def _advance_instance_on_doc_event(instance_name: str, task_action: str):
	"""Complete the first Waiting User Task that accepts task_action and run the engine forward.

	A row's task_actions is a JSON array of {"action": ...} objects or a legacy CSV string."""
	instance = frappe.get_doc("BPMN Process Instance", instance_name)

	matching_row = None
	for row in instance.active_tasks:
		if row.status != "Waiting":
			continue
		raw = (row.task_actions or "").strip()
		if raw.startswith("["):
			import json as _json
			try:
				parsed = _json.loads(raw)
				actions = [
					a.get("action", "").strip()
					for a in (parsed if isinstance(parsed, list) else [])
					if isinstance(a, dict) and a.get("action", "").strip()
				]
			except (TypeError, ValueError):
				# Malformed JSON falls back to CSV parsing so the row can still match.
				frappe.log_error(
					title="BPMN trigger: malformed task_actions JSON",
					message=f"task_actions={raw!r} on instance {instance_name}",
				)
				actions = [a.strip() for a in raw.split(",") if a.strip()]
		else:
			actions = [a.strip() for a in raw.split(",") if a.strip()]
		if task_action in actions:
			matching_row = row
			break

	if not matching_row:
		return

	# Downstream service tasks that re-submit the doc no-op because _apply_docstatus_directly skips submitted docs.
	instance.advance(task_id=matching_row.task_id, data={"action": task_action})


def _get_trigger_workflow_state(bpmn_xml: str):
	"""Return spiffworkflow:triggerWorkflowState from the first start event that sets it, or None."""
	if not bpmn_xml or not bpmn_xml.strip():
		return None
	try:
		from lxml import etree

		root = etree.fromstring(bpmn_xml.strip().encode("utf-8"))
		attr_key = f"{{{_SPIFF_NS}}}triggerWorkflowState"
		for start in root.iter(f"{{{_BPMN_NS}}}startEvent"):
			state = start.get(attr_key)
			if state:
				return state
	except Exception:
		pass
	return None


def _get_trigger_field_condition(bpmn_xml: str):
	"""Return (triggerFieldName, triggerFieldValue) from the first element that declares them, or None.

	Scopes a DocType-event trigger so several models on the same DocType and event do not all fire."""
	if not bpmn_xml or not bpmn_xml.strip():
		return None
	try:
		from lxml import etree

		root = etree.fromstring(bpmn_xml.strip().encode("utf-8"))
		fn_key = f"{{{_SPIFF_NS}}}triggerFieldName"
		fv_key = f"{{{_SPIFF_NS}}}triggerFieldValue"
		for el in root.iter():
			field_name = el.get(fn_key)
			if field_name:
				return (field_name, el.get(fv_key) or "")
	except Exception:
		pass
	return None


def _get_conditional_start_condition(bpmn_xml: str):
	"""Return the <bpmn:condition> text of the first conditional start event, or None."""
	if not bpmn_xml or not bpmn_xml.strip():
		return None
	try:
		from lxml import etree

		root = etree.fromstring(bpmn_xml.strip().encode("utf-8"))
		for start in root.iter(f"{{{_BPMN_NS}}}startEvent"):
			ced = start.find(f"{{{_BPMN_NS}}}conditionalEventDefinition")
			if ced is None:
				continue
			cond = ced.find(f"{{{_BPMN_NS}}}condition")
			if cond is not None and cond.text and cond.text.strip():
				return cond.text.strip()
	except Exception:
		pass
	return None


def guard_bpmn_document(doc, method: str):
	"""Block native submit, cancel and workflow transitions on a document an Active BPMN Process Instance controls.

	The engine's own service tasks pass through via frappe.flags.bpmn_engine_action."""
	if doc.doctype in _INTERNAL_DOCTYPES:
		return

	if getattr(frappe.flags, "bpmn_engine_action", False):
		return

	if method == "before_cancel":
		from one_bpmn.processa_engine.instances.cancellation import refuse_direct_cancel

		refuse_direct_cancel(doc)

	active_instance = frappe.db.get_value(
		"BPMN Process Instance",
		{
			"context_doctype": doc.doctype,
			"context_docname": doc.name,
			"status": "Active",
		},
		"name",
	)

	_action_labels = {
		"before_submit": "submit",
		"before_cancel": "cancel",
		"before_workflow_action": "change the workflow state of",
	}
	action_verb = _action_labels.get(method, "modify")

	if not active_instance:
		_block_native_action_on_processa_doctype(doc, action_verb)
		return

	frappe.throw(
		frappe._(
			"Cannot {0} <b>{1} {2}</b> directly. "
			"This document is controlled by a BPMN process (<b>{3}</b>). "
			"Use the <b>Actions</b> menu to proceed."
		).format(action_verb, doc.doctype, doc.name, active_instance),
		title=frappe._("Action Blocked - BPMN Process Active"),
	)


def _block_native_action_on_processa_doctype(doc, action_verb: str) -> None:
	"""Refuse a native submit or cancel on a DocType Processa runs, whether or not an instance is live."""
	from one_bpmn.processa_engine.instances.listing import get_processa_controlled_doctypes

	if frappe.flags.in_patch or doc.doctype not in get_processa_controlled_doctypes():
		return

	frappe.throw(
		frappe._(
			"Cannot {0} <b>{1} {2}</b> directly. {1} is run by Processa. Use the Processa action buttons."
		).format(action_verb, doc.doctype, doc.name),
		title=frappe._("Action Blocked - Processa DocType"),
	)


def delete_linked_bpmn_instances(doc, method: str):
	"""On trash, deliver a Delete message to Active instances; those that take it are cancelled and unlinked.

	Every other linked instance is deleted along with its BPMN Activity Log rows."""
	if doc.doctype in _INTERNAL_DOCTYPES:
		return

	instances = frappe.get_all(
		"BPMN Process Instance",
		filters={
			"context_doctype": doc.doctype,
			"context_docname": doc.name,
		},
		fields=["name", "status"],
	)

	delete_message = f"{doc.doctype.replace(' ', '')}_Delete_Action"
	delete_payload = {
		"deleted_by": frappe.session.user,
		"deleted_doctype": doc.doctype,
		"deleted_docname": doc.name,
	}
	if not instances and not message_start_models(delete_message):
		return

	# Restored afterwards so an outer engine operation deleting this document keeps its flag.
	previous_flag = getattr(frappe.flags, "bpmn_engine_action", False)
	frappe.flags.bpmn_engine_action = True

	try:
		handled = set()
		caught = False

		for inst in instances:
			if inst.status == "Active":
				try:
					instance_doc = frappe.get_doc("BPMN Process Instance", inst.name)
					instance_doc.receive_message(
						message_name=delete_message,
						payload=delete_payload,
					)
					caught = caught or bool(instance_doc.flags.get("bpmn_message_caught"))
					# The instance ran its own delete flow, so keep it.
					handled.add(inst.name)
				except frappe.ValidationError:
					# The diagram has no delete catch event, so the instance is deleted below.
					pass
				except Exception:
					# Unknown instance state: keep it, since an orphan is recoverable and a delete is not.
					handled.add(inst.name)
					frappe.log_error(
						title=f"BPMN delete message failed for {inst.name}",
						message=frappe.get_traceback(),
					)

		if not caught:
			handled.update(_start_by_message(doc, delete_message, delete_payload))

		# Cancel and unlink kept instances so nothing advances them and the link check allows the delete.
		for inst_name in handled:
			try:
				current_status = frappe.db.get_value(
					"BPMN Process Instance", inst_name, "status"
				)
				updates = {"context_doctype": None, "context_docname": None}
				# A finished delete flow keeps its Completed or Errored status.
				if current_status == "Active":
					updates["status"] = "Cancelled"
					# Cancel Waiting task rows so they leave get_active_tasks_summary and list_process_instances.
					waiting_tasks = frappe.get_all(
						"BPMN Active Task",
						filters={"parent": inst_name, "status": "Waiting"},
						pluck="name",
					)
					for task_name in waiting_tasks:
						frappe.db.set_value(
							"BPMN Active Task", task_name,
							"status", "Cancelled",
							update_modified=False,
						)
				frappe.db.set_value(
					"BPMN Process Instance", inst_name,
					updates,
					update_modified=False,
				)
				# Task rows name the document too, and Frappe's dynamic link check reads child rows.
				frappe.db.set_value(
					"BPMN Active Task",
					{"parent": inst_name, "target_doctype": doc.doctype, "target_docname": doc.name},
					{"target_doctype": None, "target_docname": None},
					update_modified=False,
				)
			except Exception:
				frappe.log_error(
					title=f"Failed to unlink BPMN instance {inst_name}",
					message=frappe.get_traceback(),
				)

		doomed = [i.name for i in instances if i.name not in handled]
		if not doomed:
			return

		# BPMN Activity Log links to the instance, so its rows go first or the link check blocks the delete.
		frappe.db.delete("BPMN Activity Log", {"instance": ["in", doomed]})

		for inst_name in doomed:
			# System cascade behind a trash the user was allowed to do; a permission failure would leave an orphan.
			try:
				frappe.delete_doc(
					"BPMN Process Instance", inst_name, ignore_permissions=True  # cascade behind a permitted trash
				)
			except Exception:
				try:
					frappe.delete_doc(
						"BPMN Process Instance", inst_name,
						ignore_permissions=True, force=True,  # cascade behind a permitted trash
					)
				except Exception:
					frappe.log_error(
						title=f"Failed to delete BPMN instance {inst_name} linked to deleted {doc.doctype} {doc.name}",
						message=frappe.get_traceback(),
					)
	finally:
		frappe.flags.bpmn_engine_action = previous_flag


# Seconds a deploy can take to reach document edits; the index is rebuilt after that.
MESSAGE_START_INDEX_TTL = 60
MESSAGE_START_INDEX_KEY = "bpmn_message_start_index"


def _start_by_message(doc, message_name: str, payload: dict) -> list:
	"""Run the one active map whose start event takes message_name; return the instances it left linked to doc."""
	models = message_start_models(message_name)
	if len(models) > 1:
		frappe.log_error(
			title=f"BPMN: {len(models)} active maps start on {message_name}",
			message=f"Exactly one must listen for it. Listening: {', '.join(sorted(models))}",
		)
		return []
	if not models:
		return []
	model_name = models[0]
	# Its running instance is busy with an earlier edit; a second one would repeat the work.
	if frappe.db.exists(
		"BPMN Process Instance",
		{
			"process_model": model_name,
			"context_doctype": doc.doctype,
			"context_docname": doc.name,
			"status": "Active",
		},
	):
		return []
	from one_bpmn.processa_engine.instances.starting import start_and_deliver_message

	try:
		return [
			start_and_deliver_message(
				model_name=model_name,
				message_name=message_name,
				payload=frappe.as_json(payload),
				context_doctype=doc.doctype,
				context_docname=doc.name,
				run_as_user=frappe.session.user,
			)
		]
	except Exception:
		# A failed map must not block the save or delete that triggered it; the instance keeps the record.
		frappe.log_error(
			title=f"BPMN: {message_name} could not start {model_name} for {doc.name}",
			message=frappe.get_traceback(),
		)
	return frappe.get_all(
		"BPMN Process Instance",
		filters={"process_model": model_name, "context_doctype": doc.doctype, "context_docname": doc.name},
		pluck="name",
	)


def message_start_models(message_name: str) -> list:
	"""Active maps started by message_name, from an index rebuilt at most once a minute."""
	index = frappe.cache.get_value(MESSAGE_START_INDEX_KEY)
	if index is None:
		from one_bpmn.processa_engine.instances.starting import message_start_index

		index = message_start_index()
		frappe.cache.set_value(MESSAGE_START_INDEX_KEY, index, expires_in_sec=MESSAGE_START_INDEX_TTL)
	return index.get(message_name, [])
