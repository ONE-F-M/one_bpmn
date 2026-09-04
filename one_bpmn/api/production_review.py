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

from one_bpmn.api.editability import _call_production_api, _is_ba_instance


def _require_ba_instance():
	"""Guard the BA-only review actions.

	"Review Doctypes" / "Review Workflow Objects" (and their Sync counterparts)
	are only meaningful on a BA (authoring) instance comparing against
	Production. Enforced here so the gate holds even if the frontend is bypassed.
	The snapshot/apply endpoints below run ON Production and are intentionally
	NOT gated by this.
	"""
	if not _is_ba_instance():
		frappe.throw(
			_("This action is only available on a BA instance (Processa Settings → Instance Type)."),
			title=_("Not Available"),
		)

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


def _clean_docfield(record: dict) -> dict:
	"""Like ``_clean`` but also drops ``name``.

	A DocField's name is a random hash minted per site when the DocType is
	installed, so the same field is called something different on BA and on
	Production. Comparing it would make every field look changed — which is
	why DocFields are keyed by ``fieldname`` in the snapshot, not by name.
	"""
	return {k: v for k, v in record.items() if k not in _META_KEYS and k != "name"}


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
	_require_ba_instance()
	targets = _workflow_targets(_refs_for_model(model_name, "read"))
	local = _build_workflow_snapshot(targets)
	remote = _call_production_api(SNAPSHOT_WORKFLOW, {"targets": json.dumps(targets)}) or {}
	changes = _diff_workflow(local, remote)
	return {"has_changes": bool(changes), "changes": changes}


@frappe.whitelist(methods=["POST"])
def sync_workflow_objects(model_name: str) -> dict:
	"""Overwrite/create the changed workflow objects on Production via API."""
	_require_ba_instance()
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
	"""Snapshot a DocType's schema surface for BA → Production comparison.

	Custom Fields and Property Setters cover everything done through Customize
	Form. They do NOT cover an edit made to a STANDARD DocType directly: Frappe
	writes that straight onto the DocField row and mints no Property Setter, so
	a change such as a Link field's ``link_filters`` was invisible here and the
	review reported "no changes" while real drift sat unsynced.

	``docfields`` closes that hole. It is keyed by ``fieldname`` rather than by
	row name — see ``_clean_docfield``.
	"""
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
			"docfields": {
				r["fieldname"]: _clean_docfield(r)
				for r in frappe.get_all("DocField", filters={"parent": dt}, fields=["*"], order_by="idx")
				if r.get("fieldname")
			} if exists else {},
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

		# DocField drift — a standard DocType edited directly rather than through
		# Customize Form. Only compared when Production actually reports the key:
		# an older Production predates it, and treating "absent" as "empty" would
		# announce every field on every DocType as missing there.
		if "docfields" in rsnap:
			lfields = lsnap.get("docfields") or {}
			rfields = rsnap.get("docfields") or {}
			for fieldname, lrec in lfields.items():
				rrec = rfields.get(fieldname)
				if rrec is None:
					changes.append({"object_type": "DocField", "name": f"{dt}-{fieldname}", "doctype": dt,
					                "action": "Create", "detail": _("Field is not on Production")})
				elif rrec != lrec:
					diffk = [k for k in lrec if lrec.get(k) != rrec.get(k)]
					changes.append({"object_type": "DocField", "name": f"{dt}-{fieldname}", "doctype": dt,
					                "action": "Update", "detail": ", ".join(diffk[:6])})
	return changes


@frappe.whitelist()
def review_doctypes(model_name: str) -> dict:
	"""Compare referenced DocTypes + customizations against Production (read-only)."""
	_require_ba_instance()
	doctypes = sorted(_refs_for_model(model_name, "read").get("doctypes") or [])
	local = _build_doctype_snapshot(doctypes)
	remote = _call_production_api(SNAPSHOT_DOCTYPES, {"doctypes": json.dumps(doctypes)}) or {}
	changes = _diff_doctypes(local, remote)
	return {"has_changes": bool(changes), "changes": changes}


@frappe.whitelist(methods=["POST"])
def sync_doctypes(model_name: str) -> dict:
	"""Open a GitHub PR (per owning app) carrying the changed customizations."""
	from one_bpmn.api.github_sync import open_customization_pr

	_require_ba_instance()
	doctypes = sorted(_refs_for_model(model_name, "write").get("doctypes") or [])
	local = _build_doctype_snapshot(doctypes)
	remote = _call_production_api(SNAPSHOT_DOCTYPES, {"doctypes": json.dumps(doctypes)}) or {}
	changes = _diff_doctypes(local, remote)
	if not changes:
		return {"synced": False, "message": _("No changes seen in the relevant doctype(s)")}

	# A customization file carries Custom Fields, Property Setters, perms and
	# links. It cannot express an edit made to a standard DocType's own field,
	# so those are reported back instead of being quietly dropped from the PR.
	docfield_changes = [c for c in changes if c["object_type"] == "DocField"]
	syncable = [c for c in changes if c["object_type"] != "DocField"]

	source_edits = []
	by_dt = {}
	for c in docfield_changes:
		by_dt.setdefault(c["doctype"], []).append(c["name"])
	for dt, names in sorted(by_dt.items()):
		source_edits.append({
			"doctype": dt,
			"fields": sorted(names),
			"reason": _(
				"Changed on the DocType itself rather than through Customize Form, so no Property "
				"Setter exists to carry it. Either change {0} in its owning app's source and deploy, "
				"or re-apply the change through Customize Form."
			).format(dt),
		})

	if not syncable:
		return {
			"synced": False,
			"source_edits": source_edits,
			"message": _(
				"The only differences are direct DocType edits, which cannot be synced as "
				"customizations. See the details for what to do with them."
			),
		}

	changed_doctypes = sorted({c["doctype"] for c in syncable})

	# What changed, per DocType, for the PR body. Taken from the diff rather than
	# from the file writer, which has not run by the time the body is composed.
	summary = {}
	for c in changes:
		label = f"{c['object_type']} {c['name']}" if c["object_type"] != "DocField" else c["name"]
		detail = f" ({c['detail']})" if c.get("detail") else ""
		summary.setdefault(c["doctype"], []).append(f"{c['action']} {label}{detail}")

	token = frappe.get_cached_doc("Processa Settings").get_password("github_token")

	# Group by the app whose SOURCE carries the customization, which is not the
	# app that owns the DocType — see _customization_app_for_doctype.
	by_app = {}
	for dt in changed_doctypes:
		app = _customization_app_for_doctype(dt)
		by_app.setdefault(app, []).append(dt)

	allowed_owners = _allowed_repo_owners()
	prs, skipped = [], []
	for app, dts in by_app.items():
		repo = _repo_for_app(app) if app else None
		if not app or not repo or not token:
			skipped.append({"app": app, "doctypes": dts,
			                "reason": _("No GitHub token, or no GitHub remote resolved for app '{0}'.").format(app or "?")})
			continue

		stamp = frappe.generate_hash(length=6)
		head_branch = f"processa/sync-{frappe.scrub(model_name)}-{stamp}"
		files, build_files, artefacts, routing = _customization_pr_files(app, dts, model_name, stamp)
		if not files and not routing["owned"]:
			# Nothing this app can carry. Reported rather than opened empty.
			skipped.append({"app": app, "doctypes": dts,
			                "reason": _("Nothing to write for these doctypes.")})
			continue
		title = (
			f"Processa: sync {', '.join(dts)}"
			if routing["owned"] else f"Processa: sync customizations for {', '.join(dts)}"
		)
		body = _pr_body(app, dts, model_name, artefacts, routing,
		                {dt: summary.get(dt) or [] for dt in dts})
		# base_branch=None → github_sync targets the repository's default branch.
		pr_url = open_customization_pr(
			token=token,
			repo=repo,
			base_branch=None,
			head_branch=head_branch,
			files=files,
			build_files=build_files,
			commit_message=title,
			pr_title=title,
			pr_body=body,
			allowed_owners=allowed_owners,
		)
		prs.append({"app": app, "repository": repo, "pr_url": pr_url,
		            "doctypes": dts, "files": artefacts})

	return {"synced": bool(prs), "prs": prs, "skipped": skipped, "source_edits": source_edits}


def _customization_pr_files(app: str, dts: list, model_name: str, stamp: str):
	"""Build the PR's file set in the customization app's own convention.

	Returns ``(files, build_files, artefacts)``:
	  * ``files``      — paths written whole (the generated data modules + patch).
	  * ``build_files`` — a callback run once the branch exists, for the paths that
	    must be READ and appended to: the two setup/ aggregators, patches.txt, and
	    the shared custom/<dt>.json. Those cannot be built up front.
	  * ``artefacts``  — every path touched, for the PR body and the API response.
	"""
	from one_bpmn.api import doctype_source_sync as source
	from one_bpmn.api import onefm_customization_codegen as gen

	# Ownership decides the destination. A DocType whose schema is in a
	# repository we control is edited in its own JSON; overriding our own source
	# with a Property Setter would leave the file no longer true, and the
	# generated patch would re-apply the override on every migrate.
	owned = [dt for dt in dts if source.owned_in_source(dt) and source.source_json_path(dt)]
	foreign = [dt for dt in dts if dt not in owned]

	files, artefacts = {}, []
	snapshots = {}
	source_paths = {dt: source.source_json_path(dt) for dt in owned}
	artefacts += sorted(source_paths.values())
	for dt in foreign:
		cfs = frappe.get_all("Custom Field", filters={"dt": dt}, fields=["*"], order_by="name")
		pss = frappe.get_all("Property Setter", filters={"doc_type": dt}, fields=["*"], order_by="name")
		snapshots[dt] = (cfs, pss)

		cf_path = gen.module_path(app, dt, "custom_field")
		ps_path = gen.module_path(app, dt, "property_setter")
		files[cf_path] = gen.render_custom_field_module(dt, cfs)
		files[ps_path] = gen.render_property_setter_module(dt, pss)
		artefacts += [cf_path, ps_path]

	if foreign:
		patch_path = gen.patch_path(app, model_name, stamp)
		files[patch_path] = gen.render_patch(app, model_name, foreign, stamp)
		artefacts.append(patch_path)

	spliced = [gen.aggregator_path(app, k) for k in ("custom_field", "property_setter")] if foreign else []
	if foreign:
		spliced.append(gen.patches_txt_path(app))
	# Under the CUSTOMIZATION app's module, not the DocType's owning module. The
	# latter is what the previous implementation used, and for a foreign DocType it
	# resolves outside this repo entirely (../hrms/hrms/hr/custom/interview.json).
	json_paths = {dt: gen.customization_json_path(app, dt) for dt in foreign}
	artefacts += spliced + sorted(json_paths.values())

	today = frappe.utils.today()
	source_notes = {}

	def build_files(reader):
		out = {}
		# Our own DocTypes first: the file is edited, never regenerated, so a
		# property nobody changed keeps its value and field order is preserved.
		for dt in owned:
			path = source_paths[dt]
			existing = reader(path)
			if not (existing or "").strip():
				# Authored on the BA site and never in source: it has to be
				# written, with the package marker and controller a standard
				# DocType is loaded through.
				created, notes = source.create_source_files(dt)
				out.update(created)
				source_notes[dt] = notes
				continue
			text, notes = source.merge_into_source(existing, dt)
			source_notes[dt] = notes
			if text is not None:
				out[path] = text

		for kind in ("custom_field", "property_setter") if foreign else ():
			path = gen.aggregator_path(app, kind)
			text = reader(path)
			if text is None:
				raise ValueError(
					f"{path} is not in the repository, so the generated getter cannot be registered. "
					f"Is '{app}' the right customization owner app?"
				)
			for dt in dts:
				text = gen.splice_aggregator(text, app, dt, kind)
			out[path] = text

		if foreign:
			pt_path = gen.patches_txt_path(app)
			pt_text = reader(pt_path)
			if pt_text is None:
				raise ValueError(f"{pt_path} is not in the repository; the patch would never run.")
			out[pt_path] = gen.splice_patches_txt(
				pt_text, app, model_name, stamp, today, note=f"Processa sync: {', '.join(foreign)}"
			)

		# The Frappe-native customizations file is merged, never regenerated: it
		# carries customizations beyond the ones this run happens to know about.
		for dt in foreign:
			path = json_paths[dt]
			cfs, pss = snapshots[dt]
			incoming = {
				"doctype": dt,
				"custom_fields": [_clean(r) for r in cfs],
				"property_setters": [_clean(r) for r in pss],
				"custom_perms": [],
				"links": frappe.get_all("DocType Link", fields="*", filters={"parent": dt}, order_by="name"),
				"sync_on_migrate": 1,
			}
			out[path] = gen.merge_customization_json(reader(path) or "", incoming)
		return out

	return files, build_files, artefacts, {"owned": owned, "foreign": foreign, "notes": source_notes}


def _routing_table(routing: dict, summary: dict = None) -> str:
	"""Which route each DocType took, and why, for the reviewer.

	The point of the table is that a DocType we own can be seen NOT to have been
	overridden: the reason column is the whole argument for the split.
	"""
	if not routing:
		return ""
	summary = summary or {}

	def what(dt, fallback):
		"""A few items, then a count. The full list is the diff below."""
		items = summary.get(dt) or fallback
		if len(items) <= 5:
			return "; ".join(items)
		return "; ".join(items[:5]) + f"; and {len(items) - 5} more"

	lines = ["| DocType | Written to | Why | What changed |", "| --- | --- | --- | --- |"]
	for dt in routing.get("owned") or []:
		lines.append(
			f"| {dt} | its own DocType JSON | we own this DocType, so the source file stays "
			f"the truth and no Property Setter overrides it "
			f"| {what(dt, routing.get('notes', {}).get(dt) or ['schema'])} |"
		)
	for dt in routing.get("foreign") or []:
		lines.append(
			f"| {dt} | customization artefacts | owned by an app we do not control, so an "
			f"override is the only mechanism there is | {what(dt, ['customizations'])} |"
		)
	return "\n".join(lines) + "\n\n"


def _pr_body(app: str, dts: list, model_name: str, artefacts: list, routing: dict = None,
             summary: dict = None) -> str:
	listed = "\n".join(f"- `{p}`" for p in artefacts)
	routing = routing or {}
	foreign = routing.get("foreign", dts)
	return (
		"Automated by Processa (Review Doctypes → Sync).\n\n"
		f"Process map: `{model_name}`\n"
		f"DocTypes: {', '.join(dts)}\n"
		f"Customization owner app: `{app}`\n\n"
		+ _routing_table(routing, summary) +
		"These changes exist on the authoring (BA) site but not yet on Production.\n\n"
		+ ("" if not foreign else
		f"For the DocTypes above that route to customizations, written in {app}'s own "
		"convention so the change lands on both a fresh install and an existing site:\n\n"
		"- the `custom/custom_field/` and `custom/property_setter/` data modules hold the content\n"
		"- `setup/custom_field.py` and `setup/property_setter.py` register them for **fresh installs** "
		"(via `after_install`, which never runs on an existing site)\n"
		"- the patch under `patches/v15_0/` applies them to **existing sites** on `bench migrate`\n"
		"- `custom/*.json` is updated too, and is **merged** rather than regenerated, so "
		"customizations outside this sync are preserved\n\n")
		+ f"Files touched:\n{listed}\n\n"
		+ ("The data modules are regenerated from the BA site's current state, so any hand edit "
		   "made to those two files will be replaced — review that hunk with care." if foreign else
		   "Each DocType JSON was EDITED, not regenerated: a property nobody changed keeps its "
		   "value and field order is preserved.")
	)


@frappe.whitelist()
def snapshot_doctype_schema(doctypes: str) -> dict:
	"""Return Custom Fields + Property Setters + DocFields per DocType (Production)."""
	frappe.only_for("System Manager")
	return _build_doctype_snapshot(_parse(doctypes) or [])


def _app_for_doctype(dt: str) -> str | None:
	module = frappe.db.get_value("DocType", dt, "module")
	if not module:
		return None
	return frappe.local.module_app.get(frappe.scrub(module))


def _customization_app_for_doctype(dt: str) -> str | None:
	"""The app whose SOURCE should carry this DocType's customizations.

	Not the same question as "who owns the DocType". A Custom Field on Employee is
	owned by one_fm — erpnext knows nothing about it — and every one of the 108
	customization modules in one_fm targets a DocType belonging to erpnext, hrms,
	frappe, helpdesk or lending. Routing by owning app therefore aimed every
	customization PR at an upstream repository (``frappe/erpnext``,
	``frappe/hrms``): not a fork, the public project.

	So the customization app from Processa Settings wins, EXCEPT where the DocType
	belongs to an app that is itself ours — one_bpmn's own doctypes are customized
	in one_bpmn, not exported into one_fm. "Ours" is decided by the configured
	app's git owner, so this needs no hardcoded list of repositories.

	Falls back to the owning app when nothing is configured, preserving the old
	behaviour for a site that has not filled the field in.
	"""
	owning = _app_for_doctype(dt)
	configured = (frappe.get_cached_value("Processa Settings", None, "customization_app") or "").strip()
	if not configured:
		return owning
	if owning and owning != configured and _same_owner(owning, configured):
		return owning
	return configured


def _same_owner(app_a: str, app_b: str) -> bool:
	"""True when both apps' git remotes sit under the same GitHub owner."""
	repo_a, repo_b = _repo_for_app(app_a), _repo_for_app(app_b)
	if not repo_a or not repo_b:
		return False
	return repo_a.split("/")[0].lower() == repo_b.split("/")[0].lower()


def _allowed_repo_owners() -> tuple:
	"""The GitHub owner(s) a customization PR may target.

	Derived from the configured customization app's own remote rather than
	hardcoded, so a fork or a renamed organisation needs no code change.
	"""
	configured = (frappe.get_cached_value("Processa Settings", None, "customization_app") or "").strip()
	repo = _repo_for_app(configured) if configured else None
	return (repo.split("/")[0],) if repo else ()


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


# ``_customization_file`` lived here: it built the single customizations JSON that
# used to be the whole PR, pathed from the DocType's OWNING module. Both halves are
# gone — the file set now follows the customization app's own convention
# (onefm_customization_codegen), and the JSON's path comes from
# ``customization_json_path``, under a module of the app the PR actually targets.


# ─────────────────────────────────────────────────────────────────────────────
# Frontend capability probe
# ─────────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def production_review_settings() -> dict:
	"""Lightweight flags the Processa canvas needs to render the Actions menu.

	``instance_type`` drives which environment-specific actions are shown:
	"Review Doctypes/Workflow" only on a BA instance, "Reassign User Task" only
	on a Production instance. ``connect_to_production`` is still surfaced for
	other callers.
	"""
	settings = frappe.get_cached_doc("Processa Settings")
	return {
		"connect_to_production": bool(settings.connect_to_production),
		"instance_type": settings.instance_type or "",
	}
