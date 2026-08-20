# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
The unified Document Request process.

Four BPMN maps — SOP, Manual and two Policy variants — were replaced by one map
that takes ``document_type`` as a parameter. These tests pin the two properties
that unification actually depends on:

  1. Every document type starts the SAME map. If a second map ever reappears
     with a Document Request trigger, the fleet has silently re-forked.
  2. The per-type behaviour that used to be a whole separate diagram is now
     data on one element — the template map on ``fetch_template``. A type
     missing from that map degrades to no template rather than failing loudly,
     so it needs an explicit test.

Plus the taxonomy cleanup: a Process master with no map behind it is worse than
absent, because it can be authored against.
"""

import html
import re
import unittest

import frappe

PROCESS = "Document Request"


def _active_model():
	"""The active model for the process, not a hard-coded model name.

	Model names carry a version suffix — the live one is "Document Request (1)" —
	so reading one by the process name returned nothing and every assertion here
	ran against an empty string, failing with a JSONDecodeError that said nothing
	about the real problem.
	"""
	return frappe.db.get_value(
		"BPMN Process Model", {"process_name": PROCESS, "is_active": 1}, "name"
	)


DOCUMENT_TYPES = ("SOP", "Policy", "Manual", "Guideline")

# Retired by patch deprecate_document_generation_processes.
DEPRECATED_PROCESSES = (
	"Manual Generation from Guidelines",
	"Policy Generation from Guideline",
	"SOP Generation from Guidelines",
)


def _template_expression() -> str:
	"""The Jinja document_type -> Drive template id map, off the live diagram.

	It lives on ``create_file`` now. It used to be on a ``fetch_template`` task
	that downloaded the template as PLAIN TEXT to put in the drafting prompt —
	which is what flattened the templates' bilingual tables into pipe characters
	and got them printed in published documents. The map moved to the task that
	COPIES the template instead, and fetch_template is gone; the lookup itself is
	unchanged, and so is what these tests are checking.
	"""
	xml = frappe.db.get_value("BPMN Process Model", _active_model(), "bpmn_xml") or ""
	match = re.search(r'id="create_file".*?connectorParams="([^"]*)"', xml, re.S)
	return html.unescape(match.group(1)) if match else ""


class TestUnifiedMapIsTheOnlyOne(unittest.TestCase):
	"""The point of the story: one map, not four."""

	def test_exactly_one_active_map_triggers_on_document_request(self):
		triggers = frappe.db.sql(
			"""select pm.name from `tabBPMN Start Event Config` sec
			   join `tabBPMN Process Model` pm on pm.name = sec.parent
			   where sec.trigger_doctype = 'Document Request'
			     and sec.trigger_type = 'DocType Event'
			     and pm.is_active = 1""",
			pluck=True,
		)
		self.assertEqual(
			sorted(set(triggers)),
			[_active_model()],
			"a second map triggering on Document Request means the fork is back",
		)

	def test_the_retired_maps_are_gone(self):
		for stale in (
			"sop_generation_process",
			"manual_generation_process",
			"policy_generation_process",
			"Process_cc43ded4",
		):
			self.assertFalse(
				frappe.db.exists("BPMN Process Model", {"process_id": stale}),
				f"{stale} was replaced by the unified map and must not be back",
			)

	def test_the_unified_map_is_active_and_compiled(self):
		model = frappe.get_doc("BPMN Process Model", _active_model())
		self.assertTrue(model.is_active, "the one remaining map must be active")
		self.assertTrue(model.serialized_spec, "an uncompiled map never starts")


class TestDocumentTypeIsAParameter(unittest.TestCase):
	"""What used to be four diagrams is now one diagram plus a lookup."""

	def test_start_guard_admits_every_type(self):
		"""The per-type guard became the constant True.

		It must be spelled ``True`` rather than removed: Spiff rejects a
		conditional start event with no condition child, and ``true`` would
		NameError if Spiff ever evaluated it.
		"""
		xml = frappe.db.get_value("BPMN Process Model", _active_model(), "bpmn_xml") or ""
		# Scope to the conditional start event first: a bare <bpmn:condition
		# prefix also matches <bpmn:conditionExpression on every gateway flow.
		definition = re.search(
			r"<bpmn:conditionalEventDefinition.*?</bpmn:conditionalEventDefinition>", xml, re.S
		)
		self.assertIsNotNone(definition, "the start event must stay conditional")
		match = re.search(
			r"<bpmn:condition\s[^>]*>(.*?)</bpmn:condition>", definition.group(0), re.S
		)
		self.assertIsNotNone(match, "the start event needs a condition child at all")
		self.assertEqual(match.group(1).strip(), "True")

	def test_every_type_resolves_a_template_or_blank(self):
		from frappe.utils.jinja import render_template

		expression = _template_expression()
		self.assertTrue(expression, "create_file must carry the per-type map")

		for document_type in DOCUMENT_TYPES:
			with self.subTest(document_type=document_type):
				rendered = render_template(
					expression, {"task_data": {"document_type": document_type}}
				)
				self.assertIsInstance(rendered, str)

	def test_the_three_generated_types_have_a_template(self):
		from frappe.utils.jinja import render_template

		expression = _template_expression()
		for document_type in ("SOP", "Policy", "Manual"):
			with self.subTest(document_type=document_type):
				rendered = render_template(
					expression, {"task_data": {"document_type": document_type}}
				)
				self.assertTrue(
					frappe.parse_json(rendered).get("file"),
					f"{document_type} is copied from a canonical template; it cannot be blank",
				)

	def test_an_unknown_type_degrades_instead_of_raising(self):
		"""Adding an option to Document Request.document_type without adding a
		template must resolve to blank rather than raising here.

		Note that a BLANK id is not a working Create: copying a template is now
		how the file is made, so a type with no template cannot produce one. That
		is a deliberate limitation of having only three templates, recorded by
		test_guideline_has_no_template_on_purpose below."""
		from frappe.utils.jinja import render_template

		# The expression is the whole connectorParams JSON, so what must be
		# empty is the file id inside it, not the rendered string.
		rendered = render_template(
			_template_expression(), {"task_data": {"document_type": "Not A Real Type"}}
		)
		self.assertEqual(frappe.parse_json(rendered).get("file"), "")

	def test_guideline_has_no_template_on_purpose(self):
		"""A Guideline is a SOURCE document, not one this process generates.

		It is mapped explicitly to "" rather than left out, so the omission reads
		as a decision instead of an oversight. The consequence is real and worth
		stating: request_action="Create" with document_type="Guideline" has no
		template to copy and cannot produce a branded document. Either a
		Guideline template gets provided, or the option should not be offered for
		Create.
		"""
		from frappe.utils.jinja import render_template

		expression = _template_expression()
		self.assertIn("'Guideline'", expression,
		              "map Guideline explicitly, so the gap is visible in the diagram")
		rendered = render_template(expression, {"task_data": {"document_type": "Guideline"}})
		self.assertEqual(frappe.parse_json(rendered).get("file"), "")

	def test_document_type_options_are_all_known_to_the_template_map(self):
		"""Every option a user can pick should be a deliberate entry in the map.

		Guideline is currently mapped to "" on purpose — it is a *source*
		document, not a generated one. This test documents that, so adding a
		fifth option silently is what fails.
		"""
		field = frappe.get_meta("Document Request").get_field("document_type")
		options = [o.strip() for o in (field.options or "").split("\n") if o.strip()]
		expression = _template_expression()
		for option in options:
			with self.subTest(option=option):
				self.assertIn(
					f"'{option}'", expression, f"{option} is selectable but absent from the map"
				)


class TestOneAgentServesEveryType(unittest.TestCase):
	def test_the_draft_task_points_at_the_shared_agent(self):
		xml = frappe.db.get_value("BPMN Process Model", _active_model(), "bpmn_xml") or ""
		match = re.search(r'id="draft_task"[^>]*aiAgentConfig="([^"]*)"', xml)
		self.assertIsNotNone(match, "the drafting task must name an agent")
		self.assertEqual(match.group(1), "Document Request Agent")

	def test_the_agent_can_actually_run(self):
		"""An agent with no ai_model is stamped Needs Attention on re-save and
		then blocks deployment — the failure that cost time when the unified
		agent was first created."""
		agent = frappe.get_doc("AI Agent Configuration", "Document Request Agent")
		self.assertTrue(agent.enabled)
		self.assertEqual(agent.lifecycle_status, "Live")
		self.assertTrue(agent.ai_model, "no AI Model linked -> Needs Attention -> will not deploy")


class TestDeprecatedProcessMasters(unittest.TestCase):
	"""A Process master with no map can still be authored against — which is
	how two Process Implementation rows were opened against a process whose
	diagram had already been deleted."""

	def test_the_retired_masters_are_gone(self):
		for process in DEPRECATED_PROCESSES:
			with self.subTest(process=process):
				self.assertFalse(
					frappe.db.exists("Process", process),
					f"{process} has no map behind it and must not be selectable",
				)

	def test_nothing_is_authored_against_them(self):
		orphans = frappe.get_all(
			"Process Implementation",
			filters={"process_name": ["in", list(DEPRECATED_PROCESSES)]},
			pluck="name",
		)
		self.assertEqual(orphans, [], "implementations survived their process")

	def test_the_replacement_master_exists(self):
		self.assertTrue(
			frappe.db.exists("Process", PROCESS),
			"the taxonomy must still describe document generation, via one entry",
		)


class TestEveryTypeStartsTheSameProcess(unittest.TestCase):
	"""The end-to-end proof, run through the real doc-event trigger."""

	def setUp(self):
		self.requester = frappe.db.get_value(
			"Employee", {"status": "Active", "reports_to": ["is", "set"]}, "name"
		)
		if not self.requester:
			self.skipTest("no active Employee with a line manager to raise a request as")

	def tearDown(self):
		frappe.db.rollback()

	def _raise_request(self, document_type):
		doc = frappe.get_doc({
			"doctype": "Document Request",
			"requester": self.requester,
			"request_action": "Create",
			"document_type": document_type,
			"title": f"_Test Unified {document_type}",
			"requirement_text": "Unification check.",
		})
		doc.insert(ignore_permissions=True)
		return doc

	def _instance_for(self, doc):
		return frappe.db.get_value(
			"BPMN Process Instance",
			{"context_doctype": "Document Request", "context_docname": doc.name},
			["name", "process_model", "status"],
			as_dict=True,
		)

	def test_each_type_starts_the_unified_map(self):
		for document_type in DOCUMENT_TYPES:
			with self.subTest(document_type=document_type):
				instance = self._instance_for(self._raise_request(document_type))
				self.assertIsNotNone(instance, "no process started for this type")
				self.assertEqual(instance.process_model, _active_model())
				self.assertEqual(instance.status, "Active")

	def test_a_request_parks_for_human_approval_before_touching_drive(self):
		"""Nothing reaches Google Drive or the model until a person approves —
		which is what makes the first leg safe to exercise on a live site."""
		doc = self._raise_request("SOP")
		self.assertEqual(doc.status, "Pending Request Approval")
		self.assertIsNotNone(self._instance_for(doc))
