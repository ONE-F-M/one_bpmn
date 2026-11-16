# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A map's agent configurations travel with its config export, and come back through the same conflict dialog."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.api.config_export_import import confirm_overwrite_config, export_bpmn_config, import_bpmn_config


def fixtures(test) -> SimpleNamespace:
	"""A tool, a skill using it, and two agents using the skill, named uniquely for this test.

	The Agent Creation map starts on every new configuration and commits, so the engine trigger is patched out.
	"""
	patcher = patch("processa.processa_engine.triggers.on_doc_event")
	patcher.start()
	test.addCleanup(patcher.stop)
	suffix = frappe.generate_hash(length=6)
	n = SimpleNamespace(
		SUFFIX=suffix,
		SCRIPT=f"Export Probe Script {suffix}",
		TOOL=f"Export Probe Tool {suffix}",
		SKILL=f"Export Probe Skill {suffix}",
		AGENT=f"Export Probe Agent {suffix}",
		DELEGATE=f"Export Probe Delegate {suffix}",
	)
	n.XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
  xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" id="d1">
  <bpmn:process id="p1" isExecutable="true">
    <bpmn:serviceTask id="run_agent" spiffworkflow:serviceType="ai_agent" spiffworkflow:aiAgentConfig="{n.AGENT}" />
    <bpmn:serviceTask id="delegate" spiffworkflow:serviceType="connector" spiffworkflow:connectorId="a2a"
      spiffworkflow:connectorParams='{{"agent": "{n.DELEGATE}", "instruction": "go"}}' />
  </bpmn:process>
</bpmn:definitions>"""
	frappe.get_doc(
		{
			"doctype": "Server Script",
			"__newname": n.SCRIPT,
			"script_type": "API",
			"api_method": f"export_probe_{suffix}",
			"script": "pass",
		}
	).insert()
	frappe.get_doc(
		{"doctype": "AI Agent Tool", "tool_name": n.TOOL, "description": "probe", "script": n.SCRIPT}
	).insert()
	frappe.get_doc(
		{
			"doctype": "AI Skill",
			"skill_name": n.SKILL,
			"description": "probe skill",
			"body": "Do the probe.",
			"resources": [{"resource_type": "Reference", "resource_name": "ref", "resource_value": "x"}],
			"allowed_tools": [{"tool": n.TOOL}],
		}
	).insert()
	for name in (n.AGENT, n.DELEGATE):
		frappe.get_doc(
			{
				"doctype": "AI Agent Configuration",
				"agent_name": name,
				"agent_id": frappe.scrub(name),
				"agent_framework": "Direct API",
				"agent_type": "Background",
				"enabled": 1,
				"system_prompt": "You probe.",
				"guardrails": [{"guardrail": "Never guess", "category": "Safety", "enabled": 1}],
				"examples": [{"input": "hi", "expected_output": "hello", "enabled": 1}],
				"enabled_skills": [{"skill": n.SKILL}],
			}
		).insert()
	return n


def renamed(n, payload: dict) -> dict:
	"""The export with every agent record renamed, so it imports as new records."""
	text = json.dumps(payload)
	for name in (n.TOOL, n.SKILL, n.AGENT, n.DELEGATE):
		text = text.replace(name, f"{name} copy")
	# agent_id is unique on its own, so the copies need their own.
	for name in (n.AGENT, n.DELEGATE):
		text = text.replace(f'"{frappe.scrub(name)}"', f'"{frappe.scrub(name + " copy")}"')
	return json.loads(text)


def names(rows, type_name):
	return {r["name"] for r in rows if r["type"] == type_name}


class TestExportCarriesAgents(FrappeTestCase):
	def setUp(self):
		self.n = fixtures(self)

	def test_the_agent_its_skill_its_tool_and_the_tool_script_are_exported(self):
		n = self.n
		out = export_bpmn_config(n.XML)

		self.assertEqual({c["name"] for c in out["agent_configurations"]}, {n.AGENT, n.DELEGATE})
		agent = next(c for c in out["agent_configurations"] if c["name"] == n.AGENT)
		self.assertEqual(agent["guardrails"][0]["guardrail"], "Never guess")
		self.assertEqual(agent["examples"][0]["expected_output"], "hello")
		self.assertEqual(agent["enabled_skills"][0]["skill"], n.SKILL)
		self.assertNotIn("owner", agent)
		self.assertNotIn("parent", agent["guardrails"][0])
		self.assertEqual([s["name"] for s in out["ai_skills"]], [n.SKILL])
		self.assertEqual(out["ai_skills"][0]["allowed_tools"][0]["tool"], n.TOOL)
		self.assertEqual([t["name"] for t in out["agent_tools"]], [n.TOOL])
		self.assertIn(n.SCRIPT, [s["name"] for s in out["server_scripts"]])
		self.assertEqual(out["counts"]["agent_configurations"], 2)
		self.assertEqual(out["counts"]["ai_skills"], 1)
		self.assertEqual(out["counts"]["agent_tools"], 1)

	def test_a_map_without_agents_exports_empty_agent_lists(self):
		n = self.n
		xml = n.XML.replace(f'spiffworkflow:aiAgentConfig="{n.AGENT}"', "").replace(n.DELEGATE, "")
		out = export_bpmn_config(xml)

		self.assertEqual(out["agent_configurations"], [])
		self.assertEqual(out["counts"]["agent_configurations"], 0)


class TestImportAgents(FrappeTestCase):
	def setUp(self):
		self.n = fixtures(self)
		self.payload = export_bpmn_config(self.n.XML)
		patcher = patch("frappe.db.commit")
		patcher.start()
		self.addCleanup(patcher.stop)

	def test_missing_records_are_created_with_their_child_rows(self):
		n = self.n
		result = import_bpmn_config(json.dumps(renamed(n, self.payload)))

		self.assertEqual(names(result["created"], "AI Agent Tool"), {f"{n.TOOL} copy"})
		self.assertEqual(names(result["created"], "AI Skill"), {f"{n.SKILL} copy"})
		self.assertEqual(
			names(result["created"], "AI Agent Configuration"), {f"{n.AGENT} copy", f"{n.DELEGATE} copy"}
		)
		self.assertEqual(result["failed"], [])
		agent = frappe.get_doc("AI Agent Configuration", f"{n.AGENT} copy")
		self.assertEqual(agent.guardrails[0].guardrail, "Never guess")
		self.assertEqual(agent.enabled_skills[0].skill, f"{n.SKILL} copy")
		self.assertEqual(
			frappe.get_doc("AI Skill", f"{n.SKILL} copy").allowed_tools[0].tool, f"{n.TOOL} copy"
		)

	def test_identical_records_are_skipped(self):
		n = self.n
		result = import_bpmn_config(json.dumps(self.payload))

		self.assertEqual(names(result["skipped"], "AI Agent Configuration"), {n.AGENT, n.DELEGATE})
		self.assertEqual(names(result["skipped"], "AI Skill"), {n.SKILL})
		self.assertEqual(result["needs_confirmation"], [])

	def test_a_changed_record_waits_for_the_user_and_overwrite_replaces_its_rows(self):
		n = self.n
		agent = next(c for c in self.payload["agent_configurations"] if c["name"] == n.AGENT)
		agent["guardrails"] = [{"guardrail": "Always cite", "category": "Safety", "enabled": 1}]

		result = import_bpmn_config(json.dumps(self.payload))

		pending = [i for i in result["needs_confirmation"] if i["type"] == "AI Agent Configuration"]
		self.assertEqual([i["name"] for i in pending], [n.AGENT])
		self.assertIn("Never guess", pending[0]["existing_text"])
		self.assertIn("Always cite", pending[0]["incoming_text"])
		self.assertEqual(
			frappe.get_doc("AI Agent Configuration", n.AGENT).guardrails[0].guardrail, "Never guess"
		)

		confirm_overwrite_config(
			json.dumps(
				[{"doctype": "AI Agent Configuration", "name": n.AGENT, "data": pending[0]["incoming_data"]}]
			)
		)

		rows = frappe.get_doc("AI Agent Configuration", n.AGENT).guardrails
		self.assertEqual([r.guardrail for r in rows], ["Always cite"])

	def test_a_record_the_site_cannot_save_is_reported_and_the_rest_still_land(self):
		n = self.n
		payload = renamed(n, self.payload)
		payload["agent_configurations"][0]["ai_model"] = f"No Such Model {n.SUFFIX}"

		result = import_bpmn_config(json.dumps(payload))

		failed = result["failed"]
		self.assertEqual([f["type"] for f in failed], ["AI Agent Configuration"])
		self.assertIn("No Such Model", failed[0]["reason"])
		self.assertEqual(len(names(result["created"], "AI Agent Configuration")), 1)
		self.assertTrue(frappe.db.exists("AI Skill", f"{n.SKILL} copy"))

	def test_overwrite_refuses_a_doctype_outside_the_agent_set(self):
		with self.assertRaises(frappe.ValidationError):
			confirm_overwrite_config(
				json.dumps([{"doctype": "Server Script", "name": self.n.SCRIPT, "data": {}}])
			)

	def test_overwrite_refuses_a_user_without_write_access(self):
		user = frappe.get_doc(
			{"doctype": "User", "email": f"export-probe-{self.n.SUFFIX}@example.com", "first_name": "Probe"}
		).insert()
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(user.name)

		with self.assertRaises(frappe.PermissionError):
			confirm_overwrite_config(
				json.dumps([{"doctype": "AI Agent Configuration", "name": self.n.AGENT, "data": {}}])
			)
