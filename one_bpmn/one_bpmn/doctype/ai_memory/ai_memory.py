# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_to_date, cint, now_datetime


class AIMemory(Document):
	@staticmethod
	def clear_old_logs(days=None):
		"""LogType interface used by Frappe's Log Settings.

		Implementing this is what lets AI Memory be registered via
		``default_log_clearing_doctypes`` and pruned through the standard Log
		Settings UI/scheduler — no custom cleanup job.

		``days <= 0`` (the default configured in hooks) means retain
		indefinitely, so nothing is deleted until an administrator sets a
		positive retention in Log Settings.
		"""
		days = cint(days)
		if days <= 0:
			return
		cutoff = add_to_date(now_datetime(), days=-days)
		frappe.db.delete("AI Memory", {"modified": ("<", cutoff)})

	def validate(self):
		self._normalize_scope_keys()
		if self.is_new():
			self._dedup_overwrite()

	def _normalize_scope_keys(self):
		"""Clear the scope keys that don't belong to the chosen scope, then
		enforce that the key(s) required by ``memory_scope`` are present.

		Clearing irrelevant keys keeps records clean and makes dedup matching
		precise even when a record's scope changes.
		"""
		if self.memory_scope != "Agent":
			self.agent_element = None
		if self.memory_scope != "Process":
			self.process_model = None
		if self.memory_scope != "Entity":
			self.reference_doctype = None
			self.reference_name = None

		if self.memory_scope == "Agent":
			if not self.agent_element:
				frappe.throw(_("An Agent-scoped memory requires an Agent Element."))
		elif self.memory_scope == "Process":
			if not self.process_model:
				frappe.throw(_("A Process-scoped memory requires a Process."))
		elif self.memory_scope == "Entity":
			if not (self.reference_doctype and self.reference_name):
				frappe.throw(
					_("An Entity-scoped memory requires a Reference Doctype and Reference Name.")
				)

	def _dedup_overwrite(self):
		"""When ``dedup_key`` is set, a new memory sharing the same scope, scope
		keys and dedup_key replaces any existing one instead of accumulating a
		duplicate. Implemented as delete-then-insert so the surviving record
		carries the latest content (and a fresh retention clock).
		"""
		if not self.dedup_key:
			return

		# Only the keys relevant to this scope are populated (the rest were
		# cleared in _normalize_scope_keys), so matching on scope + the relevant
		# key(s) + dedup_key is both correct and avoids NULL-filter pitfalls.
		filters = {"memory_scope": self.memory_scope, "dedup_key": self.dedup_key}
		if self.memory_scope == "Agent":
			filters["agent_element"] = self.agent_element
		elif self.memory_scope == "Process":
			filters["process_model"] = self.process_model
		elif self.memory_scope == "Entity":
			filters["reference_doctype"] = self.reference_doctype
			filters["reference_name"] = self.reference_name

		for name in frappe.get_all("AI Memory", filters=filters, pluck="name"):
			if name == self.name:
				continue
			frappe.delete_doc(
				"AI Memory",
				name,
				ignore_permissions=True,
				force=True,
				delete_permanently=True,
			)


def on_doctype_update():
	"""Create the indexes that back the common keyword-retrieval query shapes.

	The ``indexes`` key in the DocType JSON is documentation only — Frappe never
	reads it — so the composite indexes must be created here. ``add_index`` is
	idempotent (it checks ``has_index`` and uses ``IF NOT EXISTS``).
	"""
	frappe.db.add_index("AI Memory", ["memory_scope", "agent_element"])
	frappe.db.add_index("AI Memory", ["reference_doctype", "reference_name"])
	_add_content_fulltext_index()


def _add_content_fulltext_index():
	"""Add a MariaDB FULLTEXT index on ``content`` when the engine supports it.

	If it can't be created, keyword retrieval falls back to ``like`` filters
	(the documented fallback).
	"""
	table = "tabAI Memory"
	index_name = "content_fulltext"
	try:
		if not frappe.db.has_index(table, index_name):
			frappe.db.sql_ddl(
				f"ALTER TABLE `{table}` ADD FULLTEXT INDEX `{index_name}` (`content`)"
			)
	except Exception as e:
		frappe.logger("one_bpmn").warning(
			f"AI Memory: could not create FULLTEXT index on content; "
			f"keyword search will use `like` filters. {e}"
		)
