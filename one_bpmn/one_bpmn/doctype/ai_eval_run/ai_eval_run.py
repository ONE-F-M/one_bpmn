# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class AIEvalRun(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from one_bpmn.one_bpmn.doctype.ai_eval_result.ai_eval_result import AIEvalResult

		backend: DF.Literal["live", "replay"]
		ended_at: DF.Datetime | None
		failed_cases: DF.Int
		passed_cases: DF.Int
		results: DF.Table[AIEvalResult]
		started_at: DF.Datetime
		status: DF.Literal["Running", "Passed", "Failed", "Error"]
		suite: DF.Link
		total_cases: DF.Int
	# end: auto-generated types

	def validate(self):
		self._validate_case_counts()

	def _validate_case_counts(self):
		"""Ensure passed + failed does not exceed total cases."""
		total = cint(self.total_cases)
		passed = cint(self.passed_cases)
		failed = cint(self.failed_cases)

		if total and (passed + failed) > total:
			frappe.throw(
				_("Passed ({0}) + Failed ({1}) cannot exceed Total Cases ({2}).").format(
					passed, failed, total
				),
				title=_("Invalid Case Counts"),
			)
