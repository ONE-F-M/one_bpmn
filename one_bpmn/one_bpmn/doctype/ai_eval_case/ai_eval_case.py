# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class AIEvalCase(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from one_bpmn.one_bpmn.doctype.ai_eval_assertion.ai_eval_assertion import AIEvalAssertion

		assertions: DF.Table[AIEvalAssertion]
		backend: DF.Literal["direct_api", "antigravity"]
		bpmn_id: DF.Data | None
		expected_output: DF.LongText | None
		input_context: DF.JSON | None
		input_system_prompt: DF.LongText | None
		input_user_prompt: DF.LongText
		model: DF.Data
		process_model: DF.Link | None
		provider: DF.Link
		source_run: DF.Link | None
		suite: DF.Link | None
		title: DF.Data
	# end: auto-generated types

	def validate(self):
		self._validate_assertions()

	def _validate_assertions(self):
		"""Validate assertion rules — llm_judge assertions need judge config."""
		for idx, row in enumerate(self.assertions or [], start=1):
			if row.assertion_type == "llm_judge":
				if not row.judge_provider:
					frappe.throw(
						_("Row {0}: Judge Provider is required for llm_judge assertions.").format(idx),
						title=_("Missing Judge Provider"),
					)
				if not row.judge_model:
					frappe.throw(
						_("Row {0}: Judge Model is required for llm_judge assertions.").format(idx),
						title=_("Missing Judge Model"),
					)
				threshold = row.pass_threshold or 4
				if threshold < 1 or threshold > 5:
					frappe.throw(
						_("Row {0}: Pass Threshold must be between 1 and 5.").format(idx),
						title=_("Invalid Pass Threshold"),
					)
