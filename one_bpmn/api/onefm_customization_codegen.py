# Copyright (c) 2026, ONE BPMN and contributors
# For license information, please see license.txt
#
# Renders a "Review Doctypes → Sync" PR in the shape the customization-owner app
# (one_fm by default) already uses for every customization it carries.
#
# A Custom Field on Employee is not part of erpnext; it is part of one_fm. one_fm
# expresses that as four things, and a PR that writes only one of them is half a
# change:
#
#   custom/custom_field/<dt>.py     get_<dt>_custom_fields()  -> {DocType: [...]}
#   custom/property_setter/<dt>.py  get_<dt>_properties()     -> [ ... ]
#   setup/custom_field.py           import + custom_fields.update(...)
#   setup/property_setter.py        import + field_properties.extend(...)
#
# The two setup/ aggregators feed ``after_install`` (setup/setup.py), which is the
# FRESH-INSTALL path only — it never runs on a site that already exists. So a
# patch under patches/v15_0/ applies the same getters to existing sites, and the
# pair is what makes a customization land everywhere. Registering without the
# patch leaves live sites untouched; patching without registering leaves fresh
# installs bare.
#
# The Frappe-native ``<module>/custom/<dt>.json`` file is still written, and
# MERGED rather than regenerated: it may already carry entries this sync knows
# nothing about (another map's doctypes, or a hand-added record), and rewriting it
# wholesale from one snapshot would silently delete them.

import json
import re

import frappe

# ── field pruning ────────────────────────────────────────────────────────────
# ``fields="*"`` on Custom Field yields ~45 columns, nearly all of them defaults.
# The hand-written modules carry 5-8 keys. Emitting the full row would produce a
# file no reviewer can read and a diff that churns on every unrelated framework
# default, so only these keys survive — and only when they hold a value.
#
# ``fieldname``/``fieldtype`` are kept even when falsy: they identify the record.
_CF_KEYS = (
	"fieldname", "label", "fieldtype", "options", "insert_after", "depends_on",
	"mandatory_depends_on", "read_only_depends_on", "fetch_from", "fetch_if_empty",
	"default", "description", "precision", "length", "reqd", "read_only", "hidden",
	"unique", "in_list_view", "in_standard_filter", "in_global_search", "in_preview",
	"bold", "collapsible", "collapsible_depends_on", "allow_on_submit",
	"ignore_user_permissions", "ignore_xss_filter", "translatable", "no_copy",
	"print_hide", "print_hide_if_no_value", "report_hide", "allow_bulk_edit",
	"permlevel", "width", "columns", "link_filters", "non_negative", "sort_options",
	"is_virtual", "hide_border", "hide_days", "hide_seconds",
)
_CF_ALWAYS = ("fieldname", "fieldtype")

# Property Setter rows map 1:1 onto what one_fm's ``add_property_setter`` reads
# (setup/setup.py) — it takes exactly these five plus doctype_or_field.
_PS_KEYS = ("doctype_or_field", "doc_type", "field_name", "property", "property_type", "value")


def _prune_custom_field(rec: dict) -> dict:
	"""Reduce a Custom Field row to the keys the hand-written modules carry."""
	out = {}
	for k in _CF_KEYS:
		v = rec.get(k)
		if k in _CF_ALWAYS or (v not in (None, "", 0)):
			out[k] = v
	return out


def _prune_property_setter(rec: dict) -> dict:
	"""Reduce a Property Setter row to what ``add_property_setter`` consumes.

	``field_name`` is kept even when empty: absent means "a property of the
	DocType itself" (field_order, for one), and ``add_property_setter`` decides
	between the two on ``doctype_or_field``, so both keys must always be present.
	"""
	return {k: rec.get(k) for k in _PS_KEYS}


# ── python literal rendering ─────────────────────────────────────────────────


def _py(value, indent: int) -> str:
	"""Render a JSON-ish value as Python source, matching one_fm's house style.

	Tabs for indentation, double-quoted strings, one key per line. ``json.dumps``
	is deliberately not used for the outer structure: it cannot emit ``None`` or
	tab indentation, and the existing modules are hand-written Python.
	"""
	pad = "\t" * indent
	inner = "\t" * (indent + 1)
	if isinstance(value, dict):
		if not value:
			return "{}"
		lines = [f"{inner}{_py(k, 0)}: {_py(v, indent + 1)}," for k, v in value.items()]
		return "{\n" + "\n".join(lines) + f"\n{pad}}}"
	if isinstance(value, (list, tuple)):
		if not value:
			return "[]"
		lines = [f"{inner}{_py(v, indent + 1)}," for v in value]
		return "[\n" + "\n".join(lines) + f"\n{pad}]"
	if value is None:
		return "None"
	if isinstance(value, bool):
		return "True" if value else "False"
	if isinstance(value, (int, float)):
		return repr(value)
	# json.dumps gives correct escaping for quotes, backslashes and newlines,
	# which matters: property setter values carry eval: expressions and JSON.
	return json.dumps(str(value), ensure_ascii=False)


def getter_name(dt: str, kind: str) -> str:
	"""``get_employee_custom_fields`` / ``get_employee_properties``."""
	suffix = "custom_fields" if kind == "custom_field" else "properties"
	return f"get_{frappe.scrub(dt)}_{suffix}"


def module_path(app: str, dt: str, kind: str) -> str:
	"""Repo-relative path of the generated data module.

	Repo-relative means relative to the directory holding the app package, i.e.
	``one_fm/custom/...`` and not ``one_fm/one_fm/custom/...`` — the app name
	appears once. (The doubled form is the on-disk bench path
	``apps/one_fm/one_fm/...``, which is not what the GitHub Contents API wants.)
	"""
	return f"{app}/custom/{kind}/{frappe.scrub(dt)}.py"


def customization_json_path(app: str, dt: str) -> str:
	"""Repo-relative path of the Frappe-native ``custom/<dt>.json``.

	Placed under a module of the CUSTOMIZATION app, not the module that owns the
	DocType. ``frappe.modules.utils.sync_customizations`` walks every installed
	app's modules looking for ``<module>/custom/*.json`` and applies each file to
	whatever ``data["doctype"]`` names, so the directory it sits in does not have
	to match the DocType's own app — which is what makes it possible to carry an
	Interview customization inside one_fm at all.

	Uses the module named after the app when it has one (both one_fm and one_bpmn
	do), else its first module.
	"""
	modules = frappe.local.app_modules.get(app) or []
	module = app if app in modules else (modules[0] if modules else app)
	return f"{app}/{module}/custom/{frappe.scrub(dt)}.json"


def render_custom_field_module(dt: str, records: list) -> str:
	"""``get_<dt>_custom_fields()`` returning ``{dt: [field, ...]}``."""
	fields = [_prune_custom_field(r) for r in records]
	fields.sort(key=lambda f: f.get("fieldname") or "")
	body = _py({dt: fields}, 1)
	return (
		f"def {getter_name(dt, 'custom_field')}():\n"
		f"\treturn {body}\n"
	)


def render_property_setter_module(dt: str, records: list) -> str:
	"""``get_<dt>_properties()`` returning a flat list of property dicts."""
	props = [_prune_property_setter(r) for r in records]
	props.sort(key=lambda p: ((p.get("field_name") or ""), (p.get("property") or "")))
	body = _py(props, 1)
	return (
		f"def {getter_name(dt, 'property_setter')}():\n"
		f"\treturn {body}\n"
	)


# ── setup/ aggregator splicing ───────────────────────────────────────────────

_AGGREGATOR = {
	"custom_field": {
		"path": "{app}/setup/custom_field.py",
		"call": "\tcustom_fields.update({getter}())\n",
		# The line the new call is inserted before, so it lands inside the
		# function that builds the dict rather than after its return.
		"anchor_return": "\treturn custom_fields",
	},
	"property_setter": {
		"path": "{app}/setup/property_setter.py",
		"call": "\tfield_properties.extend({getter}())\n",
		"anchor_return": "\treturn field_properties",
	},
}


def aggregator_path(app: str, kind: str) -> str:
	return _AGGREGATOR[kind]["path"].format(app=app)


def splice_aggregator(existing: str, app: str, dt: str, kind: str) -> str:
	"""Add the import and the update/extend call, if not already present.

	Idempotent by construction: a re-run finds both lines and returns the text
	untouched, so syncing the same doctype twice does not accumulate duplicates.
	Raises when the anchor is missing rather than appending blindly — a silently
	misplaced call would register the fields nowhere and fail no test.
	"""
	spec = _AGGREGATOR[kind]
	getter = getter_name(dt, kind)
	import_line = f"from {app}.custom.{kind}.{frappe.scrub(dt)} import {getter}\n"
	call_line = spec["call"].format(getter=getter)

	text = existing
	if import_line not in text:
		# Place it after the last existing import from the same package, so the
		# block stays together and sorted-ish the way the file already is.
		pattern = re.compile(rf"^from {re.escape(app)}\.custom\.{kind}\..*$", re.M)
		matches = list(pattern.finditer(text))
		if matches:
			at = matches[-1].end() + 1
			text = text[:at] + import_line + text[at:]
		else:
			text = import_line + text

	if call_line not in text:
		anchor = spec["anchor_return"]
		idx = text.rfind(anchor)
		if idx == -1:
			raise ValueError(
				f"{aggregator_path(app, kind)} has no '{anchor.strip()}' line to insert before; "
				"the aggregator's shape has changed and the generated call would land in the wrong place."
			)
		# Walk back over blank lines so the call joins the block of calls rather
		# than being separated from it by the gap before the return.
		start = idx
		while start > 0 and text[start - 1] == "\n" and text[start - 2:start - 1] == "\n":
			start -= 1
		text = text[:start] + call_line + text[start:]

	return text


# ── patch ────────────────────────────────────────────────────────────────────


def patch_module_name(model_name: str, stamp: str) -> str:
	"""One patch per sync run, named for the map and the run.

	``stamp`` distinguishes repeat syncs of the same map; without it a second run
	would either overwrite the first patch (losing it on sites that had not
	migrated yet) or need its entry deduplicated in patches.txt.
	"""
	return f"processa_sync_{frappe.scrub(model_name)}_{stamp}"


def patch_path(app: str, model_name: str, stamp: str) -> str:
	return f"{app}/patches/v15_0/{patch_module_name(model_name, stamp)}.py"


def render_patch(app: str, model_name: str, doctypes: list, stamp: str) -> str:
	"""A patch applying every getter this run generated, to existing sites."""
	cf_imports, ps_imports, cf_calls, ps_calls = [], [], [], []
	for dt in doctypes:
		scrubbed = frappe.scrub(dt)
		cf = getter_name(dt, "custom_field")
		ps = getter_name(dt, "property_setter")
		cf_imports.append(f"from {app}.custom.custom_field.{scrubbed} import {cf}")
		ps_imports.append(f"from {app}.custom.property_setter.{scrubbed} import {ps}")
		cf_calls.append(f"\tcreate_custom_fields({cf}(), update=True)")
		ps_calls.append(f"\tadd_property_setter({ps}())")

	listed = ", ".join(doctypes)
	return (
		'"""Apply the customizations Processa synced for: ' + listed + '.\n'
		"\n"
		"Generated by Processa (Review Doctypes → Sync) for process map\n"
		f"``{model_name}``. The data lives in the custom/ modules imported below --\n"
		"this patch only applies it to a site that already exists. Fresh installs\n"
		"get the same content through setup/setup.py's after_install.\n"
		"\n"
		"Idempotent: create_custom_fields(update=True) updates a field that is\n"
		"already there instead of failing, and make_property_setter overwrites the\n"
		"property it owns.\n"
		'"""\n'
		"\n"
		"from frappe.custom.doctype.custom_field.custom_field import create_custom_fields\n"
		"\n"
		f"from {app}.setup.setup import add_property_setter\n"
		+ "\n".join(cf_imports) + "\n"
		+ "\n".join(ps_imports) + "\n"
		"\n"
		"\n"
		"def execute():\n"
		+ "\n".join(cf_calls) + "\n"
		+ "\n".join(ps_calls) + "\n"
	)


def patches_txt_path(app: str) -> str:
	return f"{app}/patches.txt"


def splice_patches_txt(existing: str, app: str, model_name: str, stamp: str, date: str, note: str = "") -> str:
	"""Append the patch entry, once.

	Appended at the end because Frappe runs patches.txt in order and this patch
	depends on the custom/ modules committed alongside it — nothing later in the
	file may assume it has run.
	"""
	entry = f"{app}.patches.v15_0.{patch_module_name(model_name, stamp)}"
	if entry in existing:
		return existing
	comment = f" #{date}"
	if note:
		comment += f" {note}"
	text = existing if existing.endswith("\n") else existing + "\n"
	return text + entry + comment + "\n"


# ── Frappe-native customizations JSON (merged, not regenerated) ──────────────


def merge_customization_json(existing: str, incoming: dict) -> str:
	"""Merge ``incoming`` into an existing ``custom/<dt>.json``.

	The file is shared: it carries every customization of that DocType, not just
	the ones this sync touched. Regenerating it from a single snapshot would drop
	anything the snapshot did not include, so records are matched by identity and
	added or updated in place, and untouched records are preserved.

	Custom Fields are identified by ``fieldname``, Property Setters by the triple
	(doctype_or_field, field_name, property) — the tuple that makes a property
	setter unique. Neither is identified by ``name``: those are per-site row names
	and differ between BA and Production.
	"""
	try:
		current = json.loads(existing) if existing and existing.strip() else {}
	except json.JSONDecodeError:
		# A corrupt or hand-mangled file is not something to silently overwrite.
		raise ValueError("existing custom/*.json is not valid JSON; refusing to overwrite it")
	if not isinstance(current, dict):
		raise ValueError("existing custom/*.json is not a JSON object")

	def key_cf(r):
		return r.get("fieldname")

	def key_ps(r):
		return (r.get("doctype_or_field"), r.get("field_name"), r.get("property"))

	merged = dict(current)
	merged["doctype"] = incoming.get("doctype") or current.get("doctype")
	merged["sync_on_migrate"] = 1

	for section, keyfn in (("custom_fields", key_cf), ("property_setters", key_ps)):
		out = list(current.get(section) or [])
		index = {keyfn(r): i for i, r in enumerate(out)}
		for rec in incoming.get(section) or []:
			k = keyfn(rec)
			if k in index:
				out[index[k]] = rec
			else:
				index[k] = len(out)
				out.append(rec)
		merged[section] = out

	for section in ("custom_perms", "links"):
		if section in incoming:
			merged.setdefault(section, incoming[section] or [])

	return frappe.as_json(merged)
