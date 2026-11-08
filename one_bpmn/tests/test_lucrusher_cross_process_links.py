# Copyright (c) 2026, one-fm and contributors
# License: MIT. See license.txt
"""LuCrusher reads the calls that link processes and drafts them as message, signal and call activity objects."""

import ast

from frappe.tests.utils import FrappeTestCase

from one_bpmn.ai_agent_registry.definitions.lucrusher import tools as ci
from one_bpmn.one_bpmn.patches.v1_0 import lucrusher_drafts_cross_process_links as p
from one_bpmn.one_bpmn.patches.v1_0.lucrusher_prosally_follows_code_and_workflow import apply_edits
from one_bpmn.one_bpmn.patches.v1_0.seed_lucrusher_skills import SKILLS


def _links(source):
	return ci._function_info(ast.parse(source).body[0], source.splitlines(), 60)["links"]


def _body(skill_name):
	return next(s["body"] for s in SKILLS if s["skill_name"] == skill_name)


class TestScanLinks(FrappeTestCase):
	def test_enqueue_message_and_new_doc_are_reported(self):
		source = (
			"def on_submit(doc):\n"
			"\tfrappe.enqueue('app.tasks.run', queue='long')\n"
			"\tsend_message('GitHub: PR Merged')\n"
			"\tfrappe.new_doc('Work Item')\n"
			"\tfrappe.publish_realtime('refresh')\n"
		)
		self.assertEqual(
			[(link["kind"], link["target"]) for link in _links(source)],
			[
				("enqueue", "'app.tasks.run'"),
				("message", "'GitHub: PR Merged'"),
				("creates", "'Work Item'"),
				("realtime", "'refresh'"),
			],
		)

	def test_keyword_target_is_read(self):
		self.assertEqual(_links("def f():\n\tfrappe.enqueue(method='app.tasks.run')")[0]["target"], "'app.tasks.run'")

	def test_plain_function_has_no_links(self):
		self.assertEqual(_links("def f(doc):\n\tdoc.save()"), [])


class TestSkillEdits(FrappeTestCase):
	def test_each_skill_gains_its_link_rules_once(self):
		for skill_name, marker, edits in p.SKILL_EDITS:
			body = _body(skill_name)
			out = apply_edits(body, edits, marker)
			self.assertIn(marker, out)
			self.assertNotEqual(out, body)
			self.assertEqual(apply_edits(out, edits, marker), out)

	def test_prosally_skill_gains_the_link_objects(self):
		skill_name, marker, edits = p.SKILL_EDITS[2]
		out = apply_edits(_body(skill_name), edits, marker)
		for text in ("IntermediateThrowEvent", "CallActivity", "called_process_id", "never reaches another process"):
			self.assertIn(text, out)

	def test_edited_skill_is_left_alone(self):
		skill_name, marker, edits = p.SKILL_EDITS[0]
		edited = _body(skill_name).replace(p.R5, "- R5: Edited.")
		self.assertEqual(apply_edits(edited, edits, marker), edited)
