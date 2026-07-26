"""
Schema validator for Docu-generated Frappe DocType definitions.

Docu produces a DocType Intermediate Representation (IR) — a plain dict describing
a DocType and its fields (see docu_agent for the schema). Before that IR is ever
applied to the database it passes through ``validate_doctype_ir`` here, which is a
*safety and correctness* gate, not a style lint:

  - legal, non-reserved doctype names and field names,
  - only whitelisted field types,
  - required ``options`` on relational/select field types,
  - no attempt to redefine Frappe's standard/meta fields.

SECURITY NOTE: the apply endpoint (api/docu_api.apply_doctype) MUST re-run this
server-side and refuse on any violation — never trust that the agent validated
before applying, and never trust an IR posted by the client.
"""

from __future__ import annotations

import re

# ── Field types Docu is allowed to emit ──────────────────────────────────────
# Deliberately a conservative subset of Frappe's fieldtypes. Layout-only types
# (Section/Column Break, HTML, Heading) are allowed because a good form needs
# them, but they never require options.
ALLOWED_FIELDTYPES = frozenset({
	"Data", "Small Text", "Text", "Long Text", "Text Editor", "Code", "Markdown Editor",
	"Int", "Float", "Currency", "Percent",
	"Check",
	"Date", "Datetime", "Time", "Duration",
	"Select", "Link", "Dynamic Link", "Table", "Table MultiSelect",
	"Attach", "Attach Image", "Signature", "Color", "Rating",
	"Password", "Read Only", "Phone",
	# Layout / presentational
	"Section Break", "Column Break", "Tab Break", "HTML", "Heading",
})

# Field types that MUST carry a non-empty ``options`` value.
_OPTIONS_REQUIRED = frozenset({
	"Link", "Table", "Table MultiSelect", "Dynamic Link", "Select",
})

# "Repeating list" field types — may define their rows inline via ``child_fields``.
_TABLE_FIELDTYPES = frozenset({"Table", "Table MultiSelect"})

# Layout fieldtypes that never need a fieldname/label to be meaningful and are
# skipped by most of the per-field checks.
_LAYOUT_FIELDTYPES = frozenset({
	"Section Break", "Column Break", "Tab Break",
})

# Frappe standard/meta field names — a custom DocType inherits these automatically.
# Redefining them corrupts the doc. (frappe.model.default_fields + a few more.)
RESERVED_FIELDNAMES = frozenset({
	"name", "owner", "creation", "modified", "modified_by", "docstatus", "idx",
	"parent", "parentfield", "parenttype", "doctype", "_user_tags", "_comments",
	"_assign", "_liked_by", "_seen", "amended_from", "amendment_date",
})

# A DocType named after any of these would collide with Frappe internals.
RESERVED_DOCTYPE_NAMES = frozenset({
	"DocType", "DocField", "User", "Role", "Report", "Print Format",
})

_FIELDNAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
# DocType names: start with a letter, letters/digits/spaces, no leading/trailing space.
_DOCTYPE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 ]*[A-Za-z0-9]$")

_MAX_FIELDS = 200


def validate_doctype_ir(ir: dict, existing_fieldnames: set | None = None) -> dict:
	"""Validate a Docu DocType IR.

	Returns ``{valid, violations, fix_hints}``. ``violations`` are precise,
	human-readable strings; ``fix_hints`` is a single actionable guidance string
	(empty when valid) a self-correcting loop can feed straight back to the model.

	``existing_fieldnames`` is the set of fieldnames already on the target DocType
	when customizing an existing type. Those fields are not being (re)created —
	Docu only edits their allowed properties via Customize Form (which validates
	the change itself) — so the strict new-field checks are skipped for them. This
	lets a standard DocType's own fields (e.g. the reserved ``amended_from``) pass
	through untouched while new fields are still fully validated.
	"""
	existing_fieldnames = existing_fieldnames or set()
	violations: list[str] = []

	if not isinstance(ir, dict):
		return {
			"valid": False,
			"violations": ["The DocType definition must be a JSON object."],
			"fix_hints": [_FIX_HINT],
		}

	# ── DocType name ─────────────────────────────────────────────────────────
	name = (ir.get("doctype_name") or "").strip()
	if not name:
		violations.append("Missing 'doctype_name'.")
	else:
		if not _DOCTYPE_NAME_RE.match(name):
			violations.append(
				f"DocType name '{name}' is invalid — use letters, digits and single "
				f"spaces, starting with a letter (e.g. 'Vehicle Inspection')."
			)
		if name in RESERVED_DOCTYPE_NAMES:
			violations.append(f"DocType name '{name}' collides with a Frappe core DocType.")

	# ── Fields ───────────────────────────────────────────────────────────────
	fields = ir.get("fields")
	if not isinstance(fields, list) or not fields:
		violations.append("A DocType needs a non-empty 'fields' array.")
		fields = []

	if len(fields) > _MAX_FIELDS:
		violations.append(f"Too many fields ({len(fields)}); maximum is {_MAX_FIELDS}.")

	seen: set[str] = set()
	has_data_field = False
	for idx, field in enumerate(fields):
		pos = f"field #{idx + 1}"
		if not isinstance(field, dict):
			violations.append(f"{pos} is not an object.")
			continue

		fieldtype = (field.get("fieldtype") or "").strip()
		fieldname = (field.get("fieldname") or "").strip()
		label = (field.get("label") or "").strip()

		# Field already present on the target DocType (customizing an existing
		# type). Docu never redefines it here — at most it edits allowed props via
		# Customize Form, which validates the change itself. Skip the new-field
		# structural checks (allowed types, reserved names, snake_case, required
		# label/options) so a standard DocType's own fields pass through.
		if fieldname and fieldname in existing_fieldnames:
			if fieldname in seen:
				violations.append(f"{pos}: duplicate fieldname '{fieldname}'.")
			else:
				seen.add(fieldname)
			has_data_field = True
			continue

		if fieldtype not in ALLOWED_FIELDTYPES:
			violations.append(
				f"{pos}: field type '{fieldtype or '(missing)'}' is not allowed. "
				f"Use one of the supported types."
			)
			continue

		if fieldtype in _LAYOUT_FIELDTYPES:
			# Layout breaks don't need a fieldname/label and can repeat.
			continue

		has_data_field = True

		if not fieldname:
			violations.append(f"{pos} ({label or fieldtype}): missing 'fieldname'.")
		elif not _FIELDNAME_RE.match(fieldname):
			violations.append(
				f"{pos}: fieldname '{fieldname}' must be snake_case "
				f"(lowercase letters, digits, underscores; starting with a letter)."
			)
		elif fieldname in RESERVED_FIELDNAMES:
			violations.append(
				f"{pos}: fieldname '{fieldname}' is a reserved Frappe field and "
				f"cannot be redefined."
			)
		elif fieldname in seen:
			violations.append(f"{pos}: duplicate fieldname '{fieldname}'.")
		else:
			seen.add(fieldname)

		if not label:
			violations.append(f"{pos} ({fieldname or fieldtype}): missing 'label'.")

		# A Table / Table MultiSelect field is a "repeating list". It may point at an
		# existing child DocType via 'options', OR define its rows inline via
		# 'child_fields' — in which case apply_doctype auto-creates the child DocType.
		child_fields = field.get("child_fields")
		is_table = fieldtype in _TABLE_FIELDTYPES
		has_inline_child = is_table and isinstance(child_fields, list) and bool(child_fields)
		if has_inline_child:
			child_seen: set[str] = set()
			child_has_data = False
			for cidx, cf in enumerate(child_fields):
				cpos = f"{pos} → repeating-list column #{cidx + 1}"
				if not isinstance(cf, dict):
					violations.append(f"{cpos} is not an object.")
					continue
				cft = (cf.get("fieldtype") or "").strip()
				cfn = (cf.get("fieldname") or "").strip()
				clabel = (cf.get("label") or "").strip()
				if cft not in ALLOWED_FIELDTYPES:
					violations.append(f"{cpos}: field type '{cft or '(missing)'}' is not allowed.")
					continue
				if cft in _TABLE_FIELDTYPES:
					violations.append(f"{cpos}: a repeating list cannot itself contain another repeating list.")
					continue
				if cft in _LAYOUT_FIELDTYPES:
					continue
				child_has_data = True
				if not cfn:
					violations.append(f"{cpos} ({clabel or cft}): missing 'fieldname'.")
				elif not _FIELDNAME_RE.match(cfn):
					violations.append(f"{cpos}: fieldname '{cfn}' must be snake_case.")
				elif cfn in RESERVED_FIELDNAMES:
					violations.append(f"{cpos}: fieldname '{cfn}' is a reserved Frappe field.")
				elif cfn in child_seen:
					violations.append(f"{cpos}: duplicate fieldname '{cfn}'.")
				else:
					child_seen.add(cfn)
				if not clabel:
					violations.append(f"{cpos} ({cfn or cft}): missing 'label'.")
				if cft in _OPTIONS_REQUIRED and not (cf.get("options") or "").strip():
					violations.append(f"{cpos} ({cfn or clabel}): a '{cft}' field requires 'options'.")
			if not child_has_data:
				violations.append(f"{pos} ({label or fieldname}): the repeating list has no data columns.")

		if fieldtype in _OPTIONS_REQUIRED and not (field.get("options") or "").strip() and not has_inline_child:
			hint = {
				"Link": "the target DocType name",
				"Table": "the child-table DocType name (or provide 'child_fields')",
				"Table MultiSelect": "the child-table DocType name (or provide 'child_fields')",
				"Dynamic Link": "the fieldname holding the target DocType",
				"Select": "newline-separated choices",
			}[fieldtype]
			violations.append(
				f"{pos} ({fieldname or label}): a '{fieldtype}' field requires 'options' "
				f"({hint})."
			)

	if fields and not has_data_field:
		violations.append("The DocType has only layout breaks and no real data fields.")

	return {
		"valid": not violations,
		"violations": violations,
		"fix_hints": [] if not violations else [_FIX_HINT],
	}


_FIX_HINT = (
	"Fix every issue listed above and output the complete corrected DocType JSON. "
	"Use snake_case fieldnames, a supported fieldtype for every field, and provide "
	"'options' for Link/Table/Dynamic Link/Select fields. Do not redefine Frappe's "
	"standard fields (name, owner, creation, modified, docstatus, parent, ...)."
)
