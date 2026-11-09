"""Permission scoping for AI Skill and AI Skill Activation.

System Manager sees everything. Anyone else sees a skill only when they created it, or when an AI Agent
Configuration that enables it is owned by them, directly or through the agent's process.
An activation is visible when its skill is.
"""

import frappe
from frappe.query_builder import DocType


def _is_system_manager(user: str) -> bool:
	return "System Manager" in frappe.get_roles(user)


def _linked_skills(user: str):
	"""Subquery of the skills enabled on an agent that the user owns."""
	enabled = DocType("AI Agent Enabled Skill")
	config = DocType("AI Agent Configuration")
	model = DocType("BPMN Process Model")
	process = DocType("Process")
	return (
		frappe.qb.from_(enabled)
		.join(config).on(config.name == enabled.parent)
		.left_join(model).on(model.name == config.process_model)
		.left_join(process).on(process.name == model.process_name)
		.select(enabled.skill)
		.where((config.process_owner == user) | (process.process_owner == user))
	)


def _visible_skills(user: str):
	"""Subquery of the skill names the user may see."""
	skill = DocType("AI Skill")
	return (
		frappe.qb.from_(skill)
		.select(skill.name)
		.where(skill.name.isin(_linked_skills(user)) | (skill.owner == user))
	)


def skill_is_visible(skill: str | None, user: str) -> bool:
	if not skill:
		return False
	if _is_system_manager(user):
		return True
	return bool(_visible_skills(user).where(DocType("AI Skill").name == skill).run())


def ai_skill_query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user
	if _is_system_manager(user):
		return ""
	return f"`tabAI Skill`.`name` in ({_visible_skills(user).get_sql()})"


def ai_skill_has_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if doc.is_new():
		return True
	return skill_is_visible(doc.name, user)


def ai_skill_activation_query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user
	if _is_system_manager(user):
		return ""
	return f"`tabAI Skill Activation`.`skill` in ({_visible_skills(user).get_sql()})"


def ai_skill_activation_has_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
	user = user or frappe.session.user
	return skill_is_visible(doc.skill, user)
