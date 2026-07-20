# Copyright (c) 2026, ONE BPMN and contributors
# For license information, please see license.txt
#
# Production-side (source-of-truth) endpoints for the Processa canvas
# "Review Doctypes" / "Review Workflow Objects" actions.
#
# The authoring (BA) site calls these over the Production API connection to:
#   - snapshot_workflow_objects  — canonical records of Roles, Server Scripts,
#         Workflow States, and Workflow Action Masters, used for diffing.
#   - apply_workflow_objects    — "Sync" for workflow objects: overwrites
#         existing records and creates new ones directly on this site.
#   - snapshot_doctype_schema   — Custom Fields + Property Setters per
#         DocType, used for diffing. (Doctype sync itself happens through a
#         GitHub pull request opened from the BA site — merging and deploying
#         migrates this site; nothing is written here.)

import frappe
from frappe import _

# The meaningful fields compared per workflow object type. Kept small and stable
# so the same canonical shape is produced on both sites.
_WORKFLOW_FIELDS = {
	"Role": ["role_name", "disabled", "desk_access", "two_factor_auth", "restrict_to_domain", "home_page"],
	"Server Script": [
		"script_type", "reference_doctype", "doctype_event", "api_method", "allow_guest",
		"module", "disabled", "event_frequency", "cron_format", "script",
	],
	"Workflow State": ["workflow_state_name", "style", "icon"],
	"Workflow Action Master": ["workflow_action_name"],
}

# Records are applied in dependency-friendly order.
_APPLY_ORDER = ["Role", "Workflow State", "Workflow Action Master", "Server Script"]

# Volatile metadata never used for comparison or push.
_META_KEYS = {
	"creation", "modified", "modified_by", "owner", "docstatus", "idx",
	"_user_tags", "_comments", "_assign", "_liked_by", "parent", "parenttype", "parentfield",
}


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────


def _parse(value):
	if isinstance(value, (dict, list)):
		return value
	return frappe.parse_json(value) if value else {}


def _clean(record: dict) -> dict:
	"""Drop volatile metadata so two records compare on content alone."""
	return {k: v for k, v in record.items() if k not in _META_KEYS}


def _canonical_record(doctype: str, name: str, fields: list) -> dict | None:
	if not frappe.db.exists(doctype, name):
		return None
	doc = frappe.get_doc(doctype, name)
	return {f: doc.get(f) for f in fields}


# ─────────────────────────────────────────────────────────────────────────────
# Workflow Objects — snapshot / apply
# ─────────────────────────────────────────────────────────────────────────────


def _build_workflow_snapshot(targets: dict) -> dict:
	"""{doctype: {name: canonical-record-or-None}} for the requested names."""
	snap = {}
	for dt, names in targets.items():
		fields = _WORKFLOW_FIELDS[dt]
		snap[dt] = {name: _canonical_record(dt, name, fields) for name in names}
	return snap


@frappe.whitelist()
def snapshot_workflow_objects(targets: str) -> dict:
	"""Return canonical records for the requested workflow objects."""
	frappe.only_for("System Manager")
	return _build_workflow_snapshot(_parse(targets))


@frappe.whitelist(methods=["POST"])
def apply_workflow_objects(payload: str) -> dict:
	"""Create/overwrite the supplied workflow objects."""
	frappe.only_for("System Manager")
	payload = _parse(payload)
	results = {"created": [], "updated": [], "failed": []}
	for dt in _APPLY_ORDER:
		for rec in payload.get(dt, []) or []:
			_upsert_record(dt, rec, results)
	frappe.db.commit()
	return results


def _upsert_record(dt: str, rec: dict, results: dict) -> None:
	name = rec.get("name")
	try:
		if name and frappe.db.exists(dt, name):
			doc = frappe.get_doc(dt, name)
			for k, v in rec.items():
				if k in _META_KEYS or k in ("name", "doctype"):
					continue
				doc.set(k, v)
			doc.flags.ignore_permissions = True
			doc.flags.ignore_validate = True
			doc.save(ignore_permissions=True)
			results["updated"].append(f"{dt}: {name}")
		else:
			rec.setdefault("doctype", dt)
			doc = frappe.get_doc(rec)
			doc.flags.ignore_permissions = True
			doc.flags.ignore_validate = True
			doc.insert(ignore_permissions=True)
			results["created"].append(f"{dt}: {doc.name}")
	except Exception as e:
		results["failed"].append(f"{dt}: {name} — {e}")
		frappe.log_error(title=f"Workflow object sync failed: {dt} {name}", message=frappe.get_traceback())


# ─────────────────────────────────────────────────────────────────────────────
# Doctypes — snapshot
# ─────────────────────────────────────────────────────────────────────────────


def _build_doctype_snapshot(doctypes: list) -> dict:
	snap = {}
	for dt in doctypes:
		exists = bool(frappe.db.exists("DocType", dt))
		snap[dt] = {
			"exists": exists,
			"custom": bool(frappe.db.get_value("DocType", dt, "custom")) if exists else False,
			"custom_fields": {
				r["name"]: _clean(r)
				for r in frappe.get_all("Custom Field", filters={"dt": dt}, fields=["*"])
			},
			"property_setters": {
				r["name"]: _clean(r)
				for r in frappe.get_all("Property Setter", filters={"doc_type": dt}, fields=["*"])
			},
		}
	return snap


@frappe.whitelist()
def snapshot_doctype_schema(doctypes: str) -> dict:
	"""Return Custom Fields + Property Setters per DocType."""
	frappe.only_for("System Manager")
	return _build_doctype_snapshot(_parse(doctypes) or [])
