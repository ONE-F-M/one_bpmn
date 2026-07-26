# Copyright (c) 2026, ONE BPMN and contributors
# For license information, please see license.txt
#
# On-demand comparison of a process map's referenced objects between the current
# site (BA / authoring) and the linked Production site, driven from the Processa
# canvas ("Actions" → "Review Doctypes" / "Review Workflow Objects").
#
#   Review Workflow Objects  — Roles, Server Scripts, Workflow States, and
#       Workflow Action Masters referenced by the model. "Sync" overwrites
#       existing records and creates new ones on Production directly via API.
#
#   Review Doctypes          — Referenced DocTypes plus their Custom Fields and
#       Property Setters. "Sync" opens a GitHub pull request (per owning app)
#       carrying the changes; merging + deploying migrates Production.
#
# Consumer endpoints run on the BA site (called by the frontend). The snapshot /
# apply endpoints are the source-of-truth counterparts executed on Production
# (reached through one_bpmn.api.editability._call_production_api, which falls
# back to a direct local call in single-site dev).

import json
import os

import frappe
from frappe import _

from one_bpmn.api.editability import _call_production_api

# Source-of-truth methods executed on the Production site.
SNAPSHOT_WORKFLOW = "one_bpmn.api.production_review.snapshot_workflow_objects"
APPLY_WORKFLOW = "one_bpmn.api.production_review.apply_workflow_objects"
SNAPSHOT_DOCTYPES = "one_bpmn.api.production_review.snapshot_doctype_schema"

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

# Records are applied to Production in dependency-friendly order.
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


def _refs_for_model(model_name: str, ptype: str = "read") -> dict:
	"""Referenced objects for a process map, from its stored BPMN XML.

	``ptype`` is the permission required on the model — ``read`` to review,
	``write`` to sync (mirrors the Deploy/Disable gate).
	"""
	from one_bpmn.api.process_map_api import _extract_bpmn_references

	if not model_name:
		frappe.throw(_("Process map name is required."))
	doc = frappe.get_doc("BPMN Process Model", model_name)
	doc.check_permission(ptype)
	xml = doc.bpmn_xml or ""
	if not xml.strip():
		frappe.throw(_("This process map has no BPMN content to analyse."))
	return _extract_bpmn_references(xml)


def _workflow_targets(refs: dict) -> dict:
	return {
		"Role": sorted(refs.get("lane_roles") or []),
		"Server Script": sorted(refs.get("server_scripts") or []),
		"Workflow State": sorted(refs.get("workflow_states") or []),
		"Workflow Action Master": sorted(refs.get("workflow_actions") or []),
	}


# ─────────────────────────────────────────────────────────────────────────────
# Workflow Objects — snapshot / diff / apply
# ─────────────────────────────────────────────────────────────────────────────


def _build_workflow_snapshot(targets: dict) -> dict:
	"""{doctype: {name: canonical-record-or-None}} for the requested names."""
	snap = {}
	for dt, names in targets.items():
		fields = _WORKFLOW_FIELDS[dt]
		snap[dt] = {name: _canonical_record(dt, name, fields) for name in names}
	return snap


def _diff_workflow(local: dict, remote: dict) -> list:
	"""BA → Production diff: records present locally but missing/different remotely."""
	changes = []
	for dt, recs in local.items():
		remote_dt = (remote or {}).get(dt) or {}
		for name, lrec in recs.items():
			if lrec is None:
				continue  # not present locally — nothing to push
			rrec = remote_dt.get(name)
			if rrec is None:
				changes.append({"object_type": dt, "name": name, "action": "Create", "detail": ""})
			elif rrec != lrec:
				diffk = [k for k in lrec if lrec.get(k) != (rrec or {}).get(k)]
				changes.append({"object_type": dt, "name": name, "action": "Update", "detail": ", ".join(diffk[:6])})
	return changes


@frappe.whitelist()
def review_workflow_objects(model_name: str) -> dict:
	"""Compare referenced workflow objects against Production (read-only)."""
	targets = _workflow_targets(_refs_for_model(model_name, "read"))
	local = _build_workflow_snapshot(targets)
	remote = _call_production_api(SNAPSHOT_WORKFLOW, {"targets": json.dumps(targets)}) or {}
	changes = _diff_workflow(local, remote)
	return {"has_changes": bool(changes), "changes": changes}


@frappe.whitelist(methods=["POST"])
def sync_workflow_objects(model_name: str) -> dict:
	"""Overwrite/create the changed workflow objects on Production via API."""
	targets = _workflow_targets(_refs_for_model(model_name, "write"))
	local = _build_workflow_snapshot(targets)
	remote = _call_production_api(SNAPSHOT_WORKFLOW, {"targets": json.dumps(targets)}) or {}
	changes = _diff_workflow(local, remote)
	if not changes:
		return {"synced": False, "message": _("No changes seen in the relevant workflow objects.")}

	# Collect the FULL source docs for the changed names only.
	changed_by_type = {}
	for c in changes:
		changed_by_type.setdefault(c["object_type"], set()).add(c["name"])

	payload = {}
	for dt, names in changed_by_type.items():
		payload[dt] = []
		for name in sorted(names):
			if frappe.db.exists(dt, name):
				rec = {k: v for k, v in frappe.get_doc(dt, name).as_dict().items() if k not in _META_KEYS}
				payload[dt].append(rec)

	results = _call_production_api(APPLY_WORKFLOW, {"payload": json.dumps(payload)}) or {}
	return {"synced": True, "results": results}


# ── Source-of-truth (Production) endpoints ──────────────────────────────────


@frappe.whitelist()
def snapshot_workflow_objects(targets: str) -> dict:
	"""Return canonical records for the requested workflow objects (Production)."""
	frappe.only_for("System Manager")
	return _build_workflow_snapshot(_parse(targets))


@frappe.whitelist(methods=["POST"])
def apply_workflow_objects(payload: str) -> dict:
	"""Create/overwrite the supplied workflow objects (Production)."""
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
# Doctypes — snapshot / diff / GitHub PR sync
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


def _diff_doctypes(local: dict, remote: dict) -> list:
	"""Granular BA → Production diff over DocTypes / Custom Fields / Property Setters."""
	changes = []
	for dt, lsnap in local.items():
		rsnap = (remote or {}).get(dt) or {}
		if lsnap.get("exists") and not rsnap.get("exists"):
			changes.append({"object_type": "DocType", "name": dt, "doctype": dt,
			                "action": "Create", "detail": _("Missing on Production")})
		for section, otype in (("custom_fields", "Custom Field"), ("property_setters", "Property Setter")):
			lrecs = lsnap.get(section) or {}
			rrecs = rsnap.get(section) or {}
			for name, lrec in lrecs.items():
				rrec = rrecs.get(name)
				if rrec is None:
					changes.append({"object_type": otype, "name": name, "doctype": dt, "action": "Create", "detail": ""})
				elif rrec != lrec:
					diffk = [k for k in lrec if lrec.get(k) != (rrec or {}).get(k)]
					changes.append({"object_type": otype, "name": name, "doctype": dt,
					                "action": "Update", "detail": ", ".join(diffk[:6])})
	return changes


@frappe.whitelist()
def review_doctypes(model_name: str) -> dict:
	"""Compare referenced DocTypes + customizations against Production (read-only)."""
	doctypes = sorted(_refs_for_model(model_name, "read").get("doctypes") or [])
	local = _build_doctype_snapshot(doctypes)
	remote = _call_production_api(SNAPSHOT_DOCTYPES, {"doctypes": json.dumps(doctypes)}) or {}
	changes = _diff_doctypes(local, remote)
	return {"has_changes": bool(changes), "changes": changes}


@frappe.whitelist(methods=["POST"])
def sync_doctypes(model_name: str) -> dict:
	"""Open a GitHub PR (per owning app) carrying the changed customizations."""
	from one_bpmn.api.github_sync import open_customization_pr

	doctypes = sorted(_refs_for_model(model_name, "write").get("doctypes") or [])
	local = _build_doctype_snapshot(doctypes)
	remote = _call_production_api(SNAPSHOT_DOCTYPES, {"doctypes": json.dumps(doctypes)}) or {}
	changes = _diff_doctypes(local, remote)
	if not changes:
		return {"synced": False, "message": _("No changes seen in the relevant doctype(s)")}

	changed_doctypes = sorted({c["doctype"] for c in changes})

	token = frappe.get_cached_doc("Processa Settings").get_password("github_token")

	# Group the changed doctypes by their owning app.
	by_app = {}
	for dt in changed_doctypes:
		app = _app_for_doctype(dt)
		by_app.setdefault(app, []).append(dt)

	prs, skipped = [], []
	for app, dts in by_app.items():
		repo = _repo_for_app(app) if app else None
		if not app or not repo or not token:
			skipped.append({"app": app, "doctypes": dts,
			                "reason": _("No GitHub token, or no GitHub remote resolved for app '{0}'.").format(app or "?")})
			continue
		files = {}
		for dt in dts:
			path, content = _customization_file(dt, app)
			files[path] = content
		head_branch = f"processa/sync-{frappe.scrub(model_name)}-{frappe.generate_hash(length=6)}"
		title = f"Processa: sync customizations for {', '.join(dts)}"
		body = (
			"Automated by Processa (Review Doctypes → Sync).\n\n"
			f"Process map: `{model_name}`\n"
			f"DocTypes: {', '.join(dts)}\n\n"
			"These Custom Field / Property Setter changes exist on the authoring (BA) "
			"site but not yet on Production. Merging and deploying this branch migrates them."
		)
		# base_branch=None → github_sync targets the repository's default branch.
		pr_url = open_customization_pr(
			token=token,
			repo=repo,
			base_branch=None,
			head_branch=head_branch,
			files=files,
			commit_message=title,
			pr_title=title,
			pr_body=body,
		)
		prs.append({"app": app, "repository": repo, "pr_url": pr_url, "doctypes": dts})

	return {"synced": bool(prs), "prs": prs, "skipped": skipped}


@frappe.whitelist()
def snapshot_doctype_schema(doctypes: str) -> dict:
	"""Return Custom Fields + Property Setters per DocType (Production)."""
	frappe.only_for("System Manager")
	return _build_doctype_snapshot(_parse(doctypes) or [])


def _app_for_doctype(dt: str) -> str | None:
	module = frappe.db.get_value("DocType", dt, "module")
	if not module:
		return None
	return frappe.local.module_app.get(frappe.scrub(module))


def _repo_for_app(app: str) -> str | None:
	"""Derive "owner/repo" from the app's git remote (each app is its own repo)."""
	import subprocess

	repo_root = os.path.dirname(frappe.get_app_path(app))

	def _git(*args):
		try:
			out = subprocess.run(
				["git", "-C", repo_root, *args], capture_output=True, text=True, timeout=10
			)
			return out.stdout.strip() if out.returncode == 0 else ""
		except Exception:
			return ""

	# Prefer origin/upstream, then fall back to whatever remote is configured.
	url = ""
	for remote in ("origin", "upstream"):
		url = _git("remote", "get-url", remote)
		if url:
			break
	if not url:
		remotes = _git("remote").split()
		if remotes:
			url = _git("remote", "get-url", remotes[0])
	return _parse_github_repo(url)


def _parse_github_repo(url: str) -> str | None:
	"""Extract "owner/repo" from an https or ssh GitHub remote URL."""
	import re

	if not url:
		return None
	m = re.search(r"github\.com[:/]+([^/]+)/([^/]+?)(?:\.git)?/?$", url)
	return f"{m.group(1)}/{m.group(2)}" if m else None


def _customization_file(dt: str, app: str) -> tuple[str, str]:
	"""Build the app-source customization JSON for a DocType (path, content).

	Mirrors ``frappe.modules.utils.export_customizations`` but in-memory and
	without the developer-mode guard/msgprint, so the content can be pushed to
	GitHub. ``sync_on_migrate`` is set so Production applies it on migrate.
	"""
	module = frappe.db.get_value("DocType", dt, "module")
	custom = {
		"custom_fields": frappe.get_all("Custom Field", fields="*", filters={"dt": dt}, order_by="name"),
		"property_setters": frappe.get_all("Property Setter", fields="*", filters={"doc_type": dt}, order_by="name"),
		"custom_perms": [],
		"links": frappe.get_all("DocType Link", fields="*", filters={"parent": dt}, order_by="name"),
		"doctype": dt,
		"sync_on_migrate": 1,
	}
	content = frappe.as_json(custom)

	module_path = frappe.get_module_path(module)
	file_abs = os.path.join(module_path, "custom", frappe.scrub(dt) + ".json")
	repo_root = os.path.dirname(frappe.get_app_path(app))
	rel_path = os.path.relpath(file_abs, repo_root)
	return rel_path, content


# ─────────────────────────────────────────────────────────────────────────────
# Frontend capability probe
# ─────────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def production_review_settings() -> dict:
	"""Lightweight flags the Processa canvas needs to render the Actions menu."""
	settings = frappe.get_cached_doc("Processa Settings")
	return {"connect_to_production": bool(settings.connect_to_production)}
