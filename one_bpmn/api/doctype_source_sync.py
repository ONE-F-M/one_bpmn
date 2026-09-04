# Copyright (c) 2026, one-fm and contributors
"""Write a schema change into the DocType's own JSON, when the DocType is ours.

A Custom Field on Employee cannot be written into erpnext's source, so an
override is the only mechanism there is and a Property Setter is the right
artefact. For a DocType one of our own apps owns, the schema is already in
source at ``<app>/<module>/doctype/<name>/<name>.json``, and emitting a Property
Setter against it is a permanent override of our own source: the JSON says one
thing, the setter says another, the effective schema is knowable only on a
migrated site — and the generated patch re-applies the override on every migrate,
so deleting the row does not stick.

So ownership decides the destination. This module answers "is this DocType ours"
and, when it is, folds the site's schema into that file the way Frappe's own
exporter writes it.
"""

from __future__ import annotations

import json

import frappe
from frappe import _

# Per-site metadata that must never reach a source file: a DocField's name is a
# hash minted per install, and timestamps would make every export a diff.
_VOLATILE = {
	"name", "creation", "modified", "modified_by", "owner", "docstatus", "idx",
	"parent", "parenttype", "parentfield", "doctype",
	"_user_tags", "_comments", "_assign", "_liked_by", "_seen",
}

# A Custom Field carries these to say WHERE it goes. The fields array expresses
# position by order, so they are not properties of the field itself.
_PLACEMENT = {"insert_after", "dt"}


def owned_in_source(dt: str) -> bool:
	"""True when this DocType's schema lives in a repository we control.

	Ownership of the DocType decides, not the presence of a customization: a
	DocType we own can legitimately carry a Custom Field another app added, and
	that still belongs in our JSON. Reuses the ownership question
	``_customization_app_for_doctype`` already answers rather than defining a
	second one.
	"""
	from one_bpmn.api.production_review import _app_for_doctype, _same_owner

	if frappe.db.get_value("DocType", dt, "custom"):
		# Created through the UI. There is no source file to write into.
		return False
	owning = _app_for_doctype(dt)
	configured = (
		frappe.get_cached_value("Processa Settings", None, "customization_app") or ""
	).strip()
	if not owning or not configured:
		return False
	return owning == configured or _same_owner(owning, configured)


def source_json_path(dt: str) -> str | None:
	"""Repo-relative path of the DocType's own JSON, as Frappe lays it out."""
	from one_bpmn.api.production_review import _app_for_doctype

	module = frappe.db.get_value("DocType", dt, "module")
	app = _app_for_doctype(dt)
	if not module or not app:
		return None
	slug = frappe.scrub(dt)
	return f"{app}/{frappe.scrub(module)}/doctype/{slug}/{slug}.json"


def _typed(value, property_type: str):
	"""A Property Setter stores its value as text; the JSON wants it typed.

	``field_order`` is the case that matters beyond numbers: Frappe keeps it as a
	JSON array in a text property, and writing it back as a string would leave a
	DocType whose field order is a sentence.
	"""
	if property_type in ("Check", "Int"):
		return frappe.utils.cint(value)
	if property_type in ("Float", "Currency", "Percent"):
		return frappe.utils.flt(value)
	if isinstance(value, str) and value[:1] in ("[", "{"):
		try:
			decoded = json.loads(value)
		except json.JSONDecodeError:
			return value
		if isinstance(decoded, (list, dict)):
			return decoded
	return value


def site_schema(dt: str) -> dict:
	"""What THIS site says the schema is.

	Three sources, in the order they override each other: the DocField rows,
	where a direct edit to a standard DocType lands; the Property Setters
	Customize Form mints instead of touching those rows; and the Custom Fields it
	adds. A setter therefore wins over the row it shadows, which is what the
	running site actually serves.
	"""
	doc_level, field_level = {}, {}
	for setter in frappe.get_all(
		"Property Setter",
		filters={"doc_type": dt},
		fields=["doctype_or_field", "field_name", "property", "property_type", "value"],
	):
		value = _typed(setter.value, setter.property_type)
		if setter.doctype_or_field == "DocType":
			doc_level[setter.property] = value
		elif setter.field_name:
			field_level.setdefault(setter.field_name, {})[setter.property] = value

	fields = []
	for row in frappe.get_all("DocField", filters={"parent": dt}, fields=["*"], order_by="idx"):
		if not row.get("fieldname"):
			continue
		field = {k: v for k, v in row.items() if k not in _VOLATILE}
		field.update(field_level.get(row["fieldname"], {}))
		fields.append(field)

	added = []
	for row in frappe.get_all("Custom Field", filters={"dt": dt}, fields=["*"], order_by="idx"):
		field = {k: v for k, v in row.items() if k not in _VOLATILE and k not in _PLACEMENT}
		added.append({"after": row.get("insert_after"), "field": field})

	return {"doctype_level": doc_level, "fields": fields, "added_fields": added}


def _set(value) -> bool:
	"""Whether a value is worth writing. Frappe's exporter omits the defaults."""
	return value not in (None, "", 0, [], {})


def _apply(target: dict, incoming: dict) -> list:
	"""Set what changed, drop what was cleared, leave everything else alone.

	Only differences are written, which is what keeps a sync with no real change
	from producing a diff: the file is not regenerated, it is edited.
	"""
	changed = []
	for key, value in incoming.items():
		if _set(value):
			if target.get(key) != value:
				target[key] = value
				changed.append(key)
		elif key in target and _set(target.get(key)):
			target.pop(key)
			changed.append(key)
	return changed


def _dump(doc: dict, trailing_newline: bool) -> str:
	"""Serialise the way Frappe's exporter does, minus the re-sort.

	``frappe.as_json`` sorts keys, and 17 of one_bpmn's 67 DocType files are not
	in that order today — re-sorting them would put a few hundred moved lines in
	front of a reviewer looking for one changed property. Indentation and
	separators match, so a file that IS in Frappe's order stays byte-identical to
	what Frappe would write; one that is not keeps its own order instead of being
	churned.
	"""
	text = json.dumps(doc, indent=1, separators=(",", ": "), ensure_ascii=True, default=str)
	return text + "\n" if trailing_newline else text


def merge_into_source(existing: str, dt: str, schema: dict = None) -> tuple:
	"""Fold this site's schema into the DocType's JSON.

	Returns ``(text, notes)``, and ``text`` is None when nothing differs: an
	unchanged file must not be written at all, or a sync with no real change
	would still show a diff.

	``schema`` defaults to this site's, and is a parameter so the same merge can
	be shown against another site's state without inserting its rows here.
	"""
	path = source_json_path(dt)
	try:
		doc = json.loads(existing) if existing and existing.strip() else None
	except json.JSONDecodeError:
		raise ValueError(f"{path} is not valid JSON; refusing to overwrite it")
	if not isinstance(doc, dict):
		raise ValueError(f"{path} is not in the repository, so there is nothing to edit")

	schema = schema or site_schema(dt)
	notes = []

	changed = _apply(doc, schema["doctype_level"])
	if changed:
		notes.append(_("DocType properties: {0}").format(", ".join(sorted(changed))))

	rows = doc.setdefault("fields", [])
	by_name = {r.get("fieldname"): r for r in rows if isinstance(r, dict)}

	for incoming in schema["fields"]:
		target = by_name.get(incoming.get("fieldname"))
		if target is None:
			# On the site but not in source. Whatever put it there is either a
			# Custom Field, handled below, or a field this file predates.
			continue
		changed = _apply(target, incoming)
		if changed:
			notes.append(_("{0}: {1}").format(incoming["fieldname"], ", ".join(sorted(changed))))

	for entry in schema["added_fields"]:
		field = entry["field"]
		fieldname = field.get("fieldname")
		if fieldname in by_name:
			changed = _apply(by_name[fieldname], field)
			if changed:
				notes.append(_("{0}: {1}").format(fieldname, ", ".join(sorted(changed))))
			continue
		after = next((i for i, r in enumerate(rows) if r.get("fieldname") == entry["after"]), None)
		rows.insert(
			after + 1 if after is not None else len(rows),
			{k: v for k, v in field.items() if _set(v)},
		)
		by_name[fieldname] = rows[after + 1 if after is not None else len(rows) - 1]
		notes.append(_("added field {0}").format(fieldname))

	if not notes:
		return None, []
	return _dump(doc, existing.endswith("\n")), notes
