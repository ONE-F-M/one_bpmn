# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_to_date, cint, now_datetime

# Size of the embedding VECTOR column. Must match the embedding model
# (one_bpmn.agents.llm_provider.embedding); all-MiniLM-L6-v2 is 384.
EMBEDDING_DIMENSIONS = 384


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

		A ``user_directed`` memory (the user explicitly asked the agent to
		remember it) is never swept here — a global retention setting turned
		on for cleanup elsewhere must not silently delete a standing
		convention nobody asked to expire.
		"""
		days = cint(days)
		if days <= 0:
			return
		cutoff = add_to_date(now_datetime(), days=-days)
		# frappe.delete_doc (not a raw frappe.db.delete) so each pruned row still
		# gets its automatic Deleted Document audit record — a raw SQL delete
		# bypasses that entirely.
		filters = {"modified": ("<", cutoff), "user_directed": 0}
		for name in frappe.get_all("AI Memory", filters=filters, pluck="name"):
			frappe.delete_doc("AI Memory", name, ignore_permissions=True)

	def validate(self):
		self._normalize_scope_keys()
		if self.is_new():
			self._dedup_overwrite()

	def _normalize_scope_keys(self):
		"""Clear the scope keys that don't belong to the chosen scope, then
		enforce that the key(s) required by ``memory_scope`` are present.

		Clearing irrelevant keys keeps records clean and makes dedup matching
		precise even when a record's scope changes. ``process_model`` is the one
		exception: on an Agent-scoped row it isn't a scope key (the row is still
		looked up by ``agent_element`` alone) but optional provenance — which
		process run produced this fact — so it is only cleared for Entity scope,
		where a memory isn't tied to a single process run.
		"""
		if self.memory_scope != "Agent":
			self.agent_element = None
		if self.memory_scope == "Entity":
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
			# ignore_permissions + force (skip the link-checker), but NOT
			# delete_permanently: leaving that off lets Frappe's normal delete
			# path capture the superseded row in the Deleted Document table
			# before removing it, so an overwrite still leaves an audit trail.
			frappe.delete_doc(
				"AI Memory",
				name,
				ignore_permissions=True,
				force=True,
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
	add_embedding_column()


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


def add_embedding_column():
	"""Add the ``embedding`` VECTOR column on MariaDB 11.7+.

	The column is deliberately NOT declared in ``ai_memory.json``: Frappe has no
	VECTOR fieldtype and would rewrite the column type on every migrate. Frappe
	ignores table columns it does not know about (``Meta.get_valid_columns``),
	so the column is invisible to ``get_doc``/``as_dict`` and only the raw SQL in
	``agents.memory.tools`` touches it.

	On an older MariaDB the ALTER fails, the warning is logged and semantic
	search stays off; keyword retrieval is unaffected. Idempotent, so the
	backfill job can call it too.
	"""
	table = "tabAI Memory"
	try:
		if not frappe.db.has_column("AI Memory", "embedding"):
			frappe.db.sql_ddl(f"ALTER TABLE `{table}` ADD COLUMN `embedding` VECTOR({EMBEDDING_DIMENSIONS}) NULL")
			# has_column reads a cached column list; drop it so the new column
			# is seen by the next search or write without waiting for a restart.
			frappe.cache.hdel("table_columns", table)
	except Exception as e:
		frappe.logger("one_bpmn").warning(
			f"AI Memory: could not add the embedding VECTOR column (MariaDB 11.7+ required); "
			f"semantic search is off, keyword search continues. {e}"
		)
