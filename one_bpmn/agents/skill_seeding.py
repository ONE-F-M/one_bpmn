"""Seed AI Skill records from a patch and enable them on one agent configuration.

A skill spec is a dict with ``skill_name``, ``description`` and ``body``, plus
optional ``resources`` (rows for AI Skill Resource) and ``status`` (Active by
default, so ``load_skill`` will serve it). The AI Skill controller still
validates every record, so a description without trigger phrasing or a body
over the token ceiling fails the patch instead of shipping silently.
"""

from __future__ import annotations

import frappe


def seed_skills(agent_name: str, skills: list[dict]) -> list[str]:
	"""Create or refresh each skill, then enable it on ``agent_name``.

	Idempotent: skills are matched by ``skill_name``, resources are replaced
	wholesale, and an enabled row is added only when missing. A site without
	the agent configuration still gets the skills; the enabling step is skipped.
	"""
	names = [_upsert_skill(spec) for spec in skills]
	if names and frappe.db.exists("AI Agent Configuration", agent_name):
		_enable(agent_name, names)
	return names


def _upsert_skill(spec: dict) -> str:
	fields = {
		"description": spec["description"],
		"body": spec["body"],
		"status": spec.get("status", "Active"),
	}
	if frappe.db.exists("AI Skill", spec["skill_name"]):
		skill = frappe.get_doc("AI Skill", spec["skill_name"])
		skill.update(fields)
	else:
		skill = frappe.get_doc({"doctype": "AI Skill", "skill_name": spec["skill_name"], **fields})
	skill.set("resources", [])
	for row in spec.get("resources") or []:
		skill.append("resources", row)
	skill.flags.ignore_permissions = True
	skill.save()
	return skill.name


def _enable(agent_name: str, skill_names: list[str]) -> None:
	config = frappe.get_doc("AI Agent Configuration", agent_name)
	present = {row.skill for row in config.enabled_skills}
	missing = [name for name in skill_names if name not in present]
	if not missing:
		return
	for name in missing:
		config.append("enabled_skills", {"skill": name})
	config.flags.ignore_permissions = True
	config.save()
