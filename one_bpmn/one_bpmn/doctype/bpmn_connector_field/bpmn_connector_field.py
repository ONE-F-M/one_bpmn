# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class BPMNConnectorField(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		choices: DF.SmallText | None
		choices_source_path: DF.Data | None
		condition_field: DF.Data | None
		condition_operator: DF.Literal["", "equals", "one of"]
		condition_value: DF.Data | None
		default_value: DF.Data | None
		expression: DF.Check
		field_label: DF.Data | None
		field_name: DF.Data
		field_type: DF.Literal["String", "Text", "Dropdown", "Boolean", "Hidden"]
		help_text: DF.SmallText | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		required: DF.Check
		value_transform: DF.Data | None
	# end: auto-generated types

	pass
