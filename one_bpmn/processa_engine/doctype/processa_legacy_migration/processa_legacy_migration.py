# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

import json
from collections import Counter

import frappe
from frappe import _
from frappe.model.document import Document

from one_bpmn.processa_engine.legacy_migration import OPEN_INSTANCE_STATUSES, state_field


class ProcessaLegacyMigration(Document):
	"""Configuration and progress record for moving open records from an old process map to a new one."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from one_bpmn.processa_engine.doctype.legacy_migration_error_log.legacy_migration_error_log import (
			LegacyMigrationErrorLog,
		)
		from one_bpmn.processa_engine.doctype.legacy_migration_state_map.legacy_migration_state_map import (
			LegacyMigrationStateMap,
		)

		batches_done: DF.Int
		completed_at: DF.Datetime | None
		error_logs: DF.Table[LegacyMigrationErrorLog]
		failed_count: DF.Int
		from_model: DF.Link
		migrated_count: DF.Int
		run_by: DF.Link | None
		started_at: DF.Datetime | None
		state_map: DF.Table[LegacyMigrationStateMap]
		status: DF.Literal["Draft", "Queued", "Running", "Completed", "Failed"]
		target_doctype: DF.Link
		to_model: DF.Link
		total_batches: DF.Int
		total_records: DF.Int
		workflow_state: DF.Link | None
	# end: auto-generated types

	def validate(self):
		if self.status not in ("Draft", "Failed"):
			return
		# The PLM's own map saves it to move its workflow state; a setup change is still checked.
		if frappe.flags.bpmn_engine_action:
			if self._setup_unchanged():
				return
		# A blank map or DocType is left to Frappe's mandatory check, which runs after validate.
		if not all((self.from_model, self.to_model, self.target_doctype)):
			return
		from_model = frappe.get_doc("BPMN Process Model", self.from_model)
		to_model = frappe.get_doc("BPMN Process Model", self.to_model)
		self.check_process_ownership(from_model, to_model)
		self._check_maps(from_model, to_model)
		state_field = self._state_field()
		self._check_state_map(to_model)
		self._check_open_states_mapped(state_field)

	def _setup_unchanged(self) -> bool:
		before = self.get_doc_before_save()
		if not before:
			return False

		def pairs(doc):
			return [(d.old_state, d.new_state) for d in doc.state_map]

		fields = ("from_model", "to_model", "target_doctype")
		if any(before.get(f) != self.get(f) for f in fields):
			return False
		return pairs(before) == pairs(self)

	def check_process_ownership(self, from_model, to_model, user: str | None = None):
		"""Throw PermissionError unless *user* (default the session user) owns both maps' processes.

		A System Manager passes."""
		user = user or frappe.session.user
		if "System Manager" in frappe.get_roles(user):
			return
		for model in (from_model, to_model):
			if frappe.db.get_value("Process", model.process_name, "process_owner") != user:
				frappe.throw(
					_("You are not the Process Owner of {0}, the process of {1}.").format(
						model.process_name, model.name
					),
					frappe.PermissionError,
				)

	def _check_maps(self, from_model, to_model):
		if from_model.name == to_model.name:
			frappe.throw(_("Old Process Map and New Process Map must be different."))
		if not to_model.serialized_spec:
			frappe.throw(_("New Process Map {0} is not currently deployed.").format(to_model.name))
		for model in (from_model, to_model):
			doctypes = _model_doctypes(model)
			if self.target_doctype not in doctypes:
				frappe.throw(
					_("{0} runs on {1}, not on {2}.").format(
						model.name, ", ".join(sorted(doctypes)) or _("no DocType"), self.target_doctype
					)
				)

	def _state_field(self) -> str:
		fieldname = state_field(self.target_doctype)
		if fieldname:
			return fieldname
		frappe.throw(_("{0} has neither a workflow_state nor a status field.").format(self.target_doctype))

	def _check_state_map(self, to_model):
		old_states = [d.old_state for d in self.state_map]
		for state, count in Counter(old_states).items():
			if count > 1:
				frappe.throw(_("Old State {0} is mapped more than once.").format(state))

		spec = json.loads(to_model.serialized_spec)
		set_states = {cfg.get("workflowState") for cfg in spec.get("service_task_extensions", {}).values()}
		for d in self.state_map:
			if d.new_state not in set_states:
				frappe.throw(
					_("No Set Workflow State step in {0} sets {1}.").format(to_model.name, d.new_state)
				)

	def _check_open_states_mapped(self, state_field: str):
		docnames = frappe.get_all(
			"BPMN Process Instance",
			filters={
				"process_model": self.from_model,
				"context_doctype": self.target_doctype,
				"status": ["in", OPEN_INSTANCE_STATUSES],
			},
			pluck="context_docname",
		)
		states = (
			frappe.get_all(self.target_doctype, filters={"name": ["in", docnames]}, pluck=state_field)
			if docnames
			else []
		)
		counts = Counter(states)
		for d in self.state_map:
			d.record_count = counts[d.old_state]

		mapped = {d.old_state for d in self.state_map}
		missing = [
			f"{state or _('(empty)')} ({count})" for state, count in counts.items() if state not in mapped
		]
		if missing:
			frappe.throw(
				_("Open records on {0} are in states with no State Mapping row: {1}").format(
					self.from_model, ", ".join(missing)
				)
			)


def _model_doctypes(model) -> set:
	"""DocTypes a process model runs on: its target DocTypes, else its start events' trigger DocTypes."""
	doctypes = {d.doctype_name for d in model.target_doctypes}
	return doctypes or {e.trigger_doctype for e in model.start_events if e.trigger_doctype}
