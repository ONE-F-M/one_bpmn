# Copyright (c) 2026, one-fm and contributors
"""A golden dataset: the cases an agent or a skill is held to, and its versions.

The cases already exist — this is what makes the set of them a thing you can
point at. Readiness says how far a subject is from carrying a representative
dataset; a version is a snapshot of what that dataset was when it was taken, so
"it passed" can be traced to the cases it passed against; and export/import
moves a dataset between sites the way configuration already moves.

A snapshot deliberately drops provenance links — the run, the piece of feedback
or the security event a case came from. Those name records on the site that
produced them, and a dataset imported elsewhere pointing at them would be
claiming a history it does not have.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

# Representative at 20, comfortable at 30 — the shipped defaults. Both are
# settings, because what counts as a representative dataset is a judgement about
# your agents rather than a property of the software.
DEFAULT_MINIMUM = 20
DEFAULT_TARGET = 30


def dataset_sizes() -> tuple[int, int]:
	"""The minimum and target case counts, from Processa Settings.

	0 or blank means the setting was never filled in, so the default stands —
	the alternative is a site where every dataset silently reads as complete.
	"""
	settings = frappe.get_cached_doc("Processa Settings")
	return (
		cint(settings.get("golden_dataset_minimum")) or DEFAULT_MINIMUM,
		cint(settings.get("golden_dataset_target")) or DEFAULT_TARGET,
	)

CASE_TYPES = ("Output", "Trajectory", "Trigger Positive", "Trigger Negative",
			  "Adversarial", "Co-Load Budget", "Memory")

# What is copied when a dataset moves. Provenance and suite membership are not
# here on purpose: the first is site-local, the second is chosen on import.
CASE_FIELDS = ("title", "case_type", "case_kind", "input_user_prompt", "input_context",
			   "expected_output", "bpmn_id")
ASSERTION_FIELDS = ("assertion_type", "value", "judge_provider", "judge_model", "pass_threshold")
EXPECTED_CALL_FIELDS = ("call_order", "tool_name", "argument", "matcher", "expected_value")


SUBJECT_FIELD = {"Suite": "eval_suite", "Agent": "agent_configuration", "Skill": "target_skill"}


def _subject(agent: str = None, skill: str = None, suite: str = None) -> tuple[str, str]:
	"""Whose dataset this is. Exactly one of suite, agent or skill.

	A suite is the unit a run belongs to, so it is the one to version when the
	question is "what did this run pass against". Agent and skill are the wider
	view: how well covered is this thing, across whatever suites its cases are
	scattered over.
	"""
	named = {"Suite": (suite or "").strip(), "Agent": (agent or "").strip(), "Skill": (skill or "").strip()}
	chosen = [k for k, v in named.items() if v]
	if len(chosen) != 1:
		frappe.throw(_("Name exactly one of a suite, an agent or a skill."))

	kind = chosen[0]
	value = named[kind]
	doctype = {"Suite": "AI Eval Suite", "Agent": "AI Agent Configuration", "Skill": "AI Skill"}[kind]
	if not frappe.db.exists(doctype, value):
		# A suite may be given by title, which is what an export carries.
		by_title = frappe.db.get_value(doctype, {"title": value}, "name") if kind == "Suite" else None
		if not by_title:
			frappe.throw(_("No {0} named '{1}'.").format(doctype, value))
		value = by_title
	return kind, value


def _case_names(subject_type: str, subject: str) -> list[str]:
	"""The cases that make up this subject's dataset.

	An agent's dataset is every case in every suite pointing at it. A skill's is
	every case naming it directly, whatever suite it sits in — a skill's trigger
	cases are often written inside the agent's suite.
	"""
	if subject_type == "Suite":
		return frappe.get_all("AI Eval Case", filters={"suite": subject}, pluck="name",
							  order_by="creation asc")
	if subject_type == "Skill":
		return frappe.get_all("AI Eval Case", filters={"target_skill": subject}, pluck="name",
							  order_by="creation asc")
	suites = frappe.get_all("AI Eval Suite", filters={"agent_configuration": subject}, pluck="name")
	if not suites:
		return []
	return frappe.get_all("AI Eval Case", filters={"suite": ["in", suites]}, pluck="name",
						  order_by="creation asc")


def _serialise(case_name: str) -> dict:
	case = frappe.get_doc("AI Eval Case", case_name)
	return {
		**{f: case.get(f) for f in CASE_FIELDS},
		# By title, not by name: a suite's name is a hash that means nothing on
		# the site receiving it. Without this an agent-wide export would flatten
		# its suites into one on import, silently.
		"suite": frappe.db.get_value("AI Eval Suite", case.suite, "title") or "",
		"target_skill": case.target_skill or "",
		"assertions": [{k: a.get(k) for k in ASSERTION_FIELDS} for a in case.assertions or []],
		"expected_tool_calls": [
			{k: c.get(k) for k in EXPECTED_CALL_FIELDS} for c in case.expected_tool_calls or []
		],
	}


def _breakdown(case_names: list[str]) -> dict:
	counts = {t: 0 for t in CASE_TYPES}
	if case_names:
		for row in frappe.get_all("AI Eval Case", filters={"name": ["in", case_names]},
								  fields=["case_type", "count(name) as n"], group_by="case_type"):
			counts[row.case_type or "Output"] = counts.get(row.case_type or "Output", 0) + row.n
	return counts


@frappe.whitelist()
def dataset_readiness(agent: str = None, skill: str = None, suite: str = None) -> dict:
	"""How far this subject is from carrying a representative dataset.

	Reports rather than refuses. The only hard bar on a case count in this app
	is a skill graduating to Action-Allowed; making go-live depend on 20 cases
	would take almost every Live agent out of service on the day it shipped.
	"""
	subject_type, subject = _subject(agent, skill, suite)
	case_names = _case_names(subject_type, subject)
	counts = _breakdown(case_names)
	total = len(case_names)
	minimum, target = dataset_sizes()

	latest = frappe.get_all(
		"AI Golden Dataset Version",
		filters=_version_filters(subject_type, subject),
		fields=["name", "version", "case_count", "taken_at"],
		order_by="version desc",
		limit_page_length=1,
	)

	return {
		"subject_type": subject_type,
		"subject": subject,
		"cases": total,
		"minimum": minimum,
		"target": target,
		"short_by": max(0, minimum - total),
		"by_type": counts,
		"missing_types": [t for t, n in counts.items() if not n],
		"latest_version": latest[0] if latest else None,
		# True once a snapshot exists that is no longer what the cases say —
		# the version is evidence about a dataset that has since moved on.
		"drifted_from_version": bool(latest and latest[0].case_count != total),
	}


def _version_filters(subject_type: str, subject: str) -> dict:
	return {"subject_type": subject_type, SUBJECT_FIELD[subject_type]: subject}


@frappe.whitelist()
def snapshot_dataset(agent: str = None, skill: str = None, suite: str = None, notes: str = "") -> dict:
	"""Record the dataset as it stands now as the next version."""
	subject_type, subject = _subject(agent, skill, suite)
	case_names = _case_names(subject_type, subject)
	if not case_names:
		frappe.throw(_("There are no eval cases for {0}, so there is nothing to version.").format(subject))

	last = frappe.db.get_value(
		"AI Golden Dataset Version", _version_filters(subject_type, subject), "version",
		order_by="version desc",
	)
	counts = _breakdown(case_names)

	version = frappe.get_doc({
		"doctype": "AI Golden Dataset Version",
		"subject_type": subject_type,
		SUBJECT_FIELD[subject_type]: subject,
		"version": (int(last) if last else 0) + 1,
		"case_count": len(case_names),
		"taken_at": now_datetime(),
		"type_breakdown": ", ".join(f"{t}: {n}" for t, n in counts.items() if n) or "none",
		"notes": notes or "",
		"cases": json.dumps([_serialise(c) for c in case_names], indent=1, default=str),
	})
	version.insert()
	return {"name": version.name, "version": version.version, "case_count": version.case_count,
			"label": version.label}


@frappe.whitelist()
def export_dataset(agent: str = None, skill: str = None, suite: str = None, version: str = None) -> dict:
	"""The dataset as a payload to download — a named version, or today's cases."""
	subject_type, subject = _subject(agent, skill, suite)

	if version:
		doc = frappe.get_doc("AI Golden Dataset Version", version)
		if doc.subject_type != subject_type or doc.get(SUBJECT_FIELD[subject_type]) != subject:
			frappe.throw(_("That version belongs to a different subject."))
		cases = json.loads(doc.cases or "[]")
		taken = str(doc.taken_at or "")
		number = doc.version
	else:
		cases = [_serialise(c) for c in _case_names(subject_type, subject)]
		taken = str(now_datetime())
		number = None

	return {
		"format": "one_bpmn.golden_dataset.v1",
		"subject_type": subject_type,
		"subject": subject,
		"version": number,
		"exported_at": taken,
		"site": frappe.local.site,
		"case_count": len(cases),
		"cases": cases,
	}


@frappe.whitelist()
def import_dataset(payload, suite: str = None, dry_run: int = 0) -> dict:
	"""Load a dataset, matching existing cases by title.

	With *suite* given, everything lands there. Without it, each case goes back
	to the suite it was exported from, matched by title — an agent-wide dataset
	covers several suites, and merging them into one loses the split and lets
	two cases sharing a title overwrite each other.

	Nothing is deleted: a case the payload no longer carries is reported, not
	removed, because on the target site it may be someone's work. A suite the
	payload names but this site does not have is reported too, rather than
	created — a suite needs an agent, and guessing which one is worse than
	saying so.
	"""
	if isinstance(payload, str):
		try:
			payload = json.loads(payload)
		except Exception:
			frappe.throw(_("The dataset is not valid JSON."))
	if not isinstance(payload, dict) or payload.get("format") != "one_bpmn.golden_dataset.v1":
		frappe.throw(_("That file is not a golden dataset export."))

	incoming = payload.get("cases") or []
	forced = None
	if suite:
		forced = frappe.get_doc("AI Eval Suite", suite)
		forced.check_permission("write")

	created, updated, skipped, unknown_suites = [], [], [], []
	touched_suites = set()

	for spec in incoming:
		title = (spec.get("title") or "").strip()
		if not title:
			skipped.append("(untitled case)")
			continue

		target = forced.name if forced else _suite_by_title(spec.get("suite"))
		if not target:
			unknown_suites.append(spec.get("suite") or "(no suite recorded)")
			continue
		if not forced:
			frappe.get_doc("AI Eval Suite", target).check_permission("write")
		touched_suites.add(target)

		existing = frappe.db.get_value("AI Eval Case", {"suite": target, "title": title}, "name")
		if dry_run:
			(updated if existing else created).append(title)
			continue

		case = frappe.get_doc("AI Eval Case", existing) if existing else frappe.new_doc("AI Eval Case")
		case.suite = target
		for field in CASE_FIELDS:
			case.set(field, spec.get(field))
		skill = (spec.get("target_skill") or "").strip()
		# A skill that does not exist here is dropped rather than created: an
		# imported dataset must not invent the thing it claims to test.
		case.target_skill = skill if skill and frappe.db.exists("AI Skill", skill) else None
		case.set("assertions", [])
		for assertion in spec.get("assertions") or []:
			case.append("assertions", {k: assertion.get(k) for k in ASSERTION_FIELDS})
		case.set("expected_tool_calls", [])
		for call in spec.get("expected_tool_calls") or []:
			case.append("expected_tool_calls", {k: call.get(k) for k in EXPECTED_CALL_FIELDS})
		case.flags.ignore_mandatory = True
		case.save() if existing else case.insert()
		(updated if existing else created).append(title)

	arriving = {(c.get("title") or "").strip() for c in incoming}
	left_alone = sorted(
		row.title
		for row in frappe.get_all("AI Eval Case", filters={"suite": ["in", list(touched_suites)]},
								  fields=["title"])
		if row.title not in arriving
	) if touched_suites else []

	# Named so nobody has to read the payload to discover that an agent-wide
	# dataset was folded into a single suite.
	merged_from = sorted({(c.get("suite") or "") for c in incoming if c.get("suite")}) if forced else []

	return {
		"suite": forced.name if forced else None,
		"suites": sorted(touched_suites),
		"created": created,
		"updated": updated,
		"skipped": skipped,
		"left_alone": left_alone,
		"unknown_suites": sorted(set(unknown_suites)),
		"merged_from": merged_from if len(merged_from) > 1 else [],
		"dry_run": bool(dry_run),
	}


def _suite_by_title(title) -> str | None:
	title = (title or "").strip()
	if not title:
		return None
	return frappe.db.get_value("AI Eval Suite", {"title": title}, "name")
