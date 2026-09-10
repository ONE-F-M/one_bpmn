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
from frappe.utils import now_datetime

# A dataset is representative at 20 and comfortable at 30 — the range the story
# asks for. Both are reported: one is the bar, the other is the target.
DATASET_MINIMUM = 20
DATASET_TARGET = 30

CASE_TYPES = ("Output", "Trajectory", "Trigger Positive", "Trigger Negative",
			  "Adversarial", "Co-Load Budget", "Memory")

# What is copied when a dataset moves. Provenance and suite membership are not
# here on purpose: the first is site-local, the second is chosen on import.
CASE_FIELDS = ("title", "case_type", "case_kind", "input_user_prompt", "input_context",
			   "expected_output", "bpmn_id")
ASSERTION_FIELDS = ("assertion_type", "value", "judge_provider", "judge_model", "pass_threshold")
EXPECTED_CALL_FIELDS = ("call_order", "tool_name", "argument", "matcher", "expected_value")


def _subject(agent: str = None, skill: str = None) -> tuple[str, str]:
	"""Whose dataset this is. Exactly one of agent or skill."""
	agent = (agent or "").strip()
	skill = (skill or "").strip()
	if bool(agent) == bool(skill):
		frappe.throw(_("Name either an agent or a skill, not both and not neither."))
	if agent:
		if not frappe.db.exists("AI Agent Configuration", agent):
			frappe.throw(_("No AI Agent Configuration named '{0}'.").format(agent))
		return "Agent", agent
	if not frappe.db.exists("AI Skill", skill):
		frappe.throw(_("No AI Skill named '{0}'.").format(skill))
	return "Skill", skill


def _case_names(subject_type: str, subject: str) -> list[str]:
	"""The cases that make up this subject's dataset.

	An agent's dataset is every case in every suite pointing at it. A skill's is
	every case naming it directly, whatever suite it sits in — a skill's trigger
	cases are often written inside the agent's suite.
	"""
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
def dataset_readiness(agent: str = None, skill: str = None) -> dict:
	"""How far this subject is from carrying a representative dataset.

	Reports rather than refuses. The only hard bar on a case count in this app
	is a skill graduating to Action-Allowed; making go-live depend on 20 cases
	would take almost every Live agent out of service on the day it shipped.
	"""
	subject_type, subject = _subject(agent, skill)
	case_names = _case_names(subject_type, subject)
	counts = _breakdown(case_names)
	total = len(case_names)

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
		"minimum": DATASET_MINIMUM,
		"target": DATASET_TARGET,
		"short_by": max(0, DATASET_MINIMUM - total),
		"by_type": counts,
		"missing_types": [t for t, n in counts.items() if not n],
		"latest_version": latest[0] if latest else None,
		# True once a snapshot exists that is no longer what the cases say —
		# the version is evidence about a dataset that has since moved on.
		"drifted_from_version": bool(latest and latest[0].case_count != total),
	}


def _version_filters(subject_type: str, subject: str) -> dict:
	if subject_type == "Agent":
		return {"subject_type": "Agent", "agent_configuration": subject}
	return {"subject_type": "Skill", "target_skill": subject}


@frappe.whitelist()
def snapshot_dataset(agent: str = None, skill: str = None, notes: str = "") -> dict:
	"""Record the dataset as it stands now as the next version."""
	subject_type, subject = _subject(agent, skill)
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
		"agent_configuration": subject if subject_type == "Agent" else None,
		"target_skill": subject if subject_type == "Skill" else None,
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
def export_dataset(agent: str = None, skill: str = None, version: str = None) -> dict:
	"""The dataset as a payload to download — a named version, or today's cases."""
	subject_type, subject = _subject(agent, skill)

	if version:
		doc = frappe.get_doc("AI Golden Dataset Version", version)
		if doc.get("agent_configuration") != (subject if subject_type == "Agent" else None) \
		   and doc.get("target_skill") != (subject if subject_type == "Skill" else None):
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
def import_dataset(payload, suite: str, dry_run: int = 0) -> dict:
	"""Load a dataset into ``suite``, matching existing cases by title.

	Titles are the identity because a case's name is a hash — importing the same
	dataset twice must update the cases it already created rather than double
	the suite. Nothing is deleted: a case the payload no longer carries is
	reported, not removed, because on the target site it may be someone's work.
	"""
	if isinstance(payload, str):
		try:
			payload = json.loads(payload)
		except Exception:
			frappe.throw(_("The dataset is not valid JSON."))
	if not isinstance(payload, dict) or payload.get("format") != "one_bpmn.golden_dataset.v1":
		frappe.throw(_("That file is not a golden dataset export."))

	suite_doc = frappe.get_doc("AI Eval Suite", suite)
	suite_doc.check_permission("write")

	incoming = payload.get("cases") or []
	existing = {
		row.title: row.name
		for row in frappe.get_all("AI Eval Case", filters={"suite": suite}, fields=["name", "title"])
	}
	created, updated, skipped = [], [], []

	for spec in incoming:
		title = (spec.get("title") or "").strip()
		if not title:
			skipped.append("(untitled case)")
			continue
		if dry_run:
			(updated if title in existing else created).append(title)
			continue

		case = frappe.get_doc("AI Eval Case", existing[title]) if title in existing \
			else frappe.new_doc("AI Eval Case")
		case.suite = suite
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
		case.save() if title in existing else case.insert()
		(updated if title in existing else created).append(title)

	untouched = sorted(set(existing) - {(c.get("title") or "").strip() for c in incoming})
	return {
		"suite": suite,
		"created": created,
		"updated": updated,
		"skipped": skipped,
		# Named so nobody has to diff two lists by eye to see what the import
		# did NOT bring.
		"left_alone": untouched,
		"dry_run": bool(dry_run),
	}
