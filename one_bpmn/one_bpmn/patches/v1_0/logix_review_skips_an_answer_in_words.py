"""Logix's review step passes an answer in words straight through instead of reviewing it as code.

The reviewer model, handed a draft with no python block, returned a revised_script, and the review
step wrapped that in a code block as the reply: the writer's correct answer to a question became a
rewritten script. The reviewer now runs only on a draft that has code. Idempotent by its marker.
"""

import frappe

SCRIPT = "Logix – Tool Review Script"
OLD = (
	'review_raw = run_sync(_adapter.complete(system=_system, user="Shape kind: " + shape_kind'
	' + "\\n\\n" + draft)).text\n'
)
NEW = (
	"# A draft with no python block is an answer in words; there is no script to review.\n"
	'_has_code = re.search(r"```python\\s*\\n.*?```", draft, re.DOTALL)\n'
	'review_raw = run_sync(_adapter.complete(system=_system, user="Shape kind: " + shape_kind'
	' + "\\n\\n" + draft)).text if _has_code else ""\n'
)


def execute():
	code = frappe.db.get_value("Server Script", SCRIPT, "script")
	if not code or "_has_code" in code or code.count(OLD) != 1:
		return
	frappe.db.set_value("Server Script", SCRIPT, "script", code.replace(OLD, NEW), update_modified=False)
