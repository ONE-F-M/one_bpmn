"""Seed the skills for the four specialist agents and enable them.

The bodies live as folders under ``one_bpmn/agent_skills`` so the Frappe and
mobile ones stay readable copies of ONE-F-M/ai-instructions, and the reference
files that skill ships with become resources the model loads only when it needs
them.

System prompts are left alone. A skill the model can load is worth having before
anything is taken out of a prompt, and moving domain rules out of the prompts is
its own piece of work.
"""

import frappe

from one_bpmn.agents.skill_seeding import seed_agent_skills

_SKILLS = {
	"Dev Agent": [
		"create-doctype",
		"doctype-controllers",
		"create-patch",
		"write-tests",
		"create-api",
		"add-custom-fields",
		"add-property-setter",
		"customize-doctype",
		"create-report",
		"verifying-before-pull-request",
		"handling-change-requests",
		"deleting-files-in-sandbox",
	],
	"Frontend Agent": [
		"write-client-script",
		"build-vue-frontend",
		"frontend-house-style",
		"registering-desk-scripts",
		"customising-upstream-doctypes",
		"reviewing-frontend-changes",
	],
	"Mobile App Agent": [
		"ionic-vue-mobile-app",
		"checking-backend-endpoints",
	],
	"Connector Agent": [
		"deciding-http-vs-python-handler",
		"reviewing-connectors",
		"securing-connectors",
		"connector-manifest-reading",
	],
}


def execute():
	frappe.reload_doc("one_bpmn", "doctype", "ai_skill")
	frappe.reload_doc("one_bpmn", "doctype", "ai_skill_resource")
	frappe.reload_doc("one_bpmn", "doctype", "ai_agent_enabled_skill")

	for agent, skills in _SKILLS.items():
		seed_agent_skills(agent, skills)
