# Copyright (c) 2025, One BPMN and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ProcessaSettings(Document):
	def validate(self):
		self._validate_embedding_model()

	def _validate_embedding_model(self):
		"""Refuse an embedding model that cannot produce the width of the stored
		column.

		The Select only offers models that produce the right width, so this is
		the second line: a patch, a fixture or an API write can set the field
		without ever passing through the form. A model of the wrong width is not
		rejected at save time by the database either, because nothing is written
		then; every LATER memory write fails inside a try/except, logs one line
		and carries on, so semantic search stops working with nothing on screen
		to say so. That is the failure this exists to make impossible.

		Only runs when the value actually changed, so an administrator editing
		an unrelated setting is never made to wait for a model to load, and a
		machine that has lost its model cache can still be configured. The
		comparison is against what is stored, not Frappe's before-save copy,
		because a patch or a fixture can reach ``validate`` without one.

		Skipped during install and migrate, where a save of this Single would
		otherwise pull a model download into the middle of a deployment.
		"""
		from one_bpmn.agents.llm_provider.embedding import SEMANTIC_DISABLED
		from one_bpmn.one_bpmn.doctype.ai_memory.ai_memory import EMBEDDING_DIMENSIONS

		model = (self.memory_embedding_model or "").strip()
		if not model or model == SEMANTIC_DISABLED:
			return
		if frappe.flags.in_install or frappe.flags.in_migrate:
			return

		stored = (frappe.db.get_single_value("Processa Settings", "memory_embedding_model") or "").strip()
		if model == stored:
			return

		try:
			from one_bpmn.agents.llm_provider.embedding import probe_model

			dimensions = probe_model(model)
		except Exception as e:
			frappe.throw(
				_("{0} could not be loaded, so semantic memory search would silently stop working: {1}").format(
					frappe.bold(model), e
				),
				title=_("Embedding Model Unusable"),
			)

		if dimensions != EMBEDDING_DIMENSIONS:
			frappe.throw(
				_(
					"{0} produces {1} numbers per memory, but the stored column holds {2}. "
					"Every memory written with it would fail to store, leaving semantic search off. "
					"Choose a model that produces {2}, or choose Disabled."
				).format(frappe.bold(model), dimensions, EMBEDDING_DIMENSIONS),
				title=_("Embedding Model Does Not Fit"),
			)
