"""Seed AI Skill records from a patch and enable them on one agent configuration.

A skill spec is a dict with ``skill_name``, ``description`` and ``body``, plus
optional ``resources`` (rows for AI Skill Resource) and ``status`` (Active by
default, so ``load_skill`` will serve it). The AI Skill controller still
validates every record, so a description without trigger phrasing or a body
over the token ceiling fails the patch instead of shipping silently.

Skills ship as folders under ``one_bpmn/agent_skills``: a ``SKILL.md`` with
YAML frontmatter and a body, and every other file as a resource named by its
path relative to the folder, so a body that links to ``references/x.md`` names
the resource the model loads.
"""

from __future__ import annotations

import os

import frappe

SKILLS_DIR = "agent_skills"


def skills_root() -> str:
	"""Where the skill folders live.

	``get_app_path`` scrubs each path part, which turns a hyphenated folder name
	into an underscored one that does not exist.
	"""
	return os.path.join(frappe.get_app_path("one_bpmn"), SKILLS_DIR)


def seed_agent_skills(agent_name: str, skill_dirs: list[str]) -> list[str]:
	"""Seed the named skill folders and enable them on ``agent_name``."""
	return seed_skills(agent_name, [load_skill_dir(name) for name in skill_dirs])


def load_skill_dir(dir_name: str) -> dict:
	"""Read one shipped skill folder into a spec."""
	import yaml

	root = os.path.join(skills_root(), dir_name)
	with open(os.path.join(root, "SKILL.md")) as handle:
		text = handle.read()

	if not text.startswith("---"):
		frappe.throw(f"{dir_name}/SKILL.md has no frontmatter")
	_, front, body = text.split("---\n", 2)
	meta = yaml.safe_load(front) or {}

	return {
		"skill_name": meta.get("name") or dir_name,
		"description": " ".join(str(meta.get("description") or "").split()),
		"body": body.strip(),
		"resources": _resources(root),
	}


def _resources(root: str) -> list[dict]:
	rows = []
	for folder, _dirs, files in os.walk(root):
		for name in sorted(files):
			if name == "SKILL.md":
				continue
			path = os.path.join(folder, name)
			with open(path) as handle:
				rows.append(
					{
						"resource_type": "Reference",
						"resource_name": os.path.relpath(path, root),
						"resource_value": handle.read(),
					}
				)
	return sorted(rows, key=lambda row: row["resource_name"])


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
