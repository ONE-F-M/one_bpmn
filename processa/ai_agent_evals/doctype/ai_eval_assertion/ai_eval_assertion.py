# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class AIEvalAssertion(Document):
    # begin: auto-generated types
    # This code is auto-generated. Do not modify anything in this block.

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from frappe.types import DF

        assertion_type: DF.Literal["schema_valid", "contains", "regex", "equals", "llm_judge"]
        judge_model: DF.Data | None
        judge_provider: DF.Link | None
        parent: DF.Data
        parentfield: DF.Data
        parenttype: DF.Data
        pass_threshold: DF.Int
        value: DF.LongText
    # end: auto-generated types
    pass
