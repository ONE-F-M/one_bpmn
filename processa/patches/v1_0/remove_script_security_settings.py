import frappe

FIELDS = (
	"section_break_script_security",
	"script_security_intro",
	"column_break_script_security",
	"script_block_while",
	"script_block_functiondef",
	"script_block_lambda",
	"script_strict_builtins",
	"script_strict_frappe_attrs",
	"script_block_all_imports",
	"script_binop_multiply_threshold",
)


def execute():
	frappe.db.delete("Singles", {"doctype": "Processa Settings", "field": ("in", FIELDS)})
