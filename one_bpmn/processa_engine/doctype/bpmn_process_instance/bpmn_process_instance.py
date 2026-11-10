# Copyright (c) 2026, one-fm and contributors

import frappe
from frappe import _
from frappe.model.document import Document

from one_bpmn.processa_engine import runtime


class BPMNProcessInstance(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from one_bpmn.processa_engine.doctype.bpmn_active_task.bpmn_active_task import BPMNActiveTask

		active_tasks: DF.Table[BPMNActiveTask]
		buffered_messages: DF.JSON | None
		completed_at: DF.Datetime | None
		context_docname: DF.DynamicLink | None
		context_doctype: DF.Link | None
		engine_in_progress: DF.Check
		initiated_by: DF.Link | None
		migrated_from: DF.Link | None
		parent_instance: DF.Link | None
		parent_task_id: DF.Data | None
		process_model: DF.Link
		serialized_spec: DF.JSON | None
		started_at: DF.Datetime | None
		status: DF.Literal["Queued", "Active", "Completed", "Errored", "Cancelled", "Suspended"]
		waiting_for_ai: DF.Check
		waiting_for_human: DF.Data | None
		workflow_state: DF.JSON | None
	# end: auto-generated types

	"""A running execution of a BPMN Process Model. The runtime package does the work; these methods call it."""

	def start(self, initial_data: dict | None = None):
		"""Build the workflow from the model's compiled spec and run it to the first wait."""
		runtime.start.start(self, initial_data)

	def advance(self, task_id: str, data: dict | None = None) -> list:
		"""Complete a READY User Task with the user's data and run on; returns the waiting tasks."""
		return runtime.advance.advance(self, task_id, data)

	def receive_message(self, message_name: str, payload: dict | None = None) -> list:
		"""Deliver a BPMN message to the wait that catches it; returns the waiting tasks."""
		return runtime.messages.receive_message(self, message_name, payload)

	def resume_parked_ai(self, kind: str, task_id: str):
		"""Run one parked AI unit inside its bpmn_ai_agent job and carry the flow on."""
		runtime.parked_ai.resume_parked_ai(self, kind, task_id)

	def retry_failed_step(self):
		"""Run an Errored instance again from its last saved state."""
		runtime.advance.retry_failed_step(self)

	def get_parked_ai_units(self) -> list:
		"""The AI units currently parked on this instance."""
		return runtime.parked_ai.get_parked_ai_units(self)

	def get_active_tasks_summary(self) -> list:
		"""The waiting User Tasks as dicts, for API responses and the Processa frontend."""
		return runtime.active_tasks.get_active_tasks_summary(self)

	def complete_ai_human_task(self, task_id: str, data: dict | None = None) -> None:
		"""Complete a suspended agent's human task and resume the agent."""
		runtime.human_tasks.complete_ai_human_task(self, task_id, data)

	def complete_a2a_human_task(self, task_id: str, data: dict | None = None) -> None:
		"""Send a person's answer back to the remote agent that asked."""
		runtime.remote_waits.complete_a2a_human_task(self, task_id, data)

	def log_operator_action(self, action: str, reason: str) -> None:
		"""Record an operator's cancel, suspend, resume or retry with who did it and why."""
		# log_task drops a repeat of the same task_id and action, so every operator action gets its own id.
		runtime.common.log_task(
			self,
			task_id=f"instance-{action.lower()}::{frappe.generate_hash(length=10)}",
			task_name=_("Instance {0}").format(action.lower()),
			action=action,
			data={"reason": reason},
		)

	def _dispatch_service_task(self, task, task_cfg_override: dict | None = None):
		"""shape_tools.execute_shape dispatches through the instance, so its tests can hand in a stand-in."""
		return runtime.dispatch.dispatch_service_task(self, task, task_cfg_override)
