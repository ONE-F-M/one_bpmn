# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""WI-001997: agents own their maps — the clone template is gone.

Covers the three behavioural changes:

  * ``is_chat_startable_map`` distinguishes a chat map (start event
    conditioned on Chat Conversation insert) from a business-process map
    and from no map at all;
  * a chat mode label on an agent mapped to a NON-chat map is rejected at
    save — the label promises a chat presence the map cannot deliver;
  * ``create_agent_configuration`` links the designer-chosen process_model
    and waives the label only for process-embedded (non-chat-map) agents.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.agent_config_resolver import (
	create_agent_configuration,
	get_creation_process_model,
)
from one_bpmn.agents.agent_provisioning import is_chat_startable_map, validate_agent_config

test_ignore = ["BPMN Process Model"]

CHAT_XML = (
	'<?xml version="1.0" encoding="UTF-8"?>'
	'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"'
	' xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" id="zz_wi1997_defs">'
	'<bpmn:process id="zz_wi1997_proc" isExecutable="true">'
	'<bpmn:startEvent id="chat_start">'
	'<bpmn:conditionalEventDefinition id="zz_wi1997_cond"'
	' spiffworkflow:triggerDoctype="Chat Conversation"'
	' spiffworkflow:triggerType="After Insert" />'
	"</bpmn:startEvent>"
	"</bpmn:process></bpmn:definitions>"
)

# Same shape, but it starts on a business record — not chat-startable.
BUSINESS_XML = CHAT_XML.replace("Chat Conversation", "ToDo")


def _model_fixture(xml: str, slug: str) -> str:
	name = f"ZZ WI1997 {slug}"
	if frappe.db.exists("BPMN Process Model", name):
		return name
	doc = frappe.get_doc({
		"doctype": "BPMN Process Model",
		"title": name,
		"process_id": f"zz_wi1997_{slug}",
		"version": 1,
		"bpmn_xml": xml,
	})
	doc.flags.ignore_mandatory = True
	doc.insert(ignore_permissions=True, ignore_mandatory=True)
	return doc.name


class TestChatStartableMap(FrappeTestCase):
	def test_detection(self):
		self.assertTrue(is_chat_startable_map(_model_fixture(CHAT_XML, "chat")))
		self.assertFalse(is_chat_startable_map(_model_fixture(BUSINESS_XML, "biz")))
		self.assertIsNone(is_chat_startable_map(""))
		self.assertIsNone(is_chat_startable_map("ZZ WI1997 missing"))


class TestChatLabelAgainstMap(FrappeTestCase):
	"""Controller validation: the label must match what the map can deliver."""

	def setUp(self):
		super().setUp()
		# Suppress the After-Insert creation-process trigger — a real run makes
		# live AI calls; the trigger's own behaviour is covered by WI-001620.
		frappe.flags.in_migrate = True

	def tearDown(self):
		frappe.flags.in_migrate = False
		super().tearDown()

	def _config(self, slug: str, label: str = "", process_model: str = None):
		doc = frappe.new_doc("AI Agent Configuration")
		doc.agent_name = f"ZZ WI1997 {slug}"
		doc.agent_id = f"zz_wi1997_{slug}"
		doc.agent_type = "Chat"
		doc.agent_framework = "Direct API"
		doc.chat_mode_label = label
		doc.process_model = process_model
		return doc

	def test_label_on_non_chat_map_is_rejected(self):
		biz = _model_fixture(BUSINESS_XML, "biz")
		with self.assertRaises(frappe.ValidationError):
			self._config("labelled_biz", label="ZZ WI1997 Biz", process_model=biz).insert()

	def test_label_on_chat_map_saves(self):
		chat = _model_fixture(CHAT_XML, "chat")
		doc = self._config("labelled_chat", label="ZZ WI1997 Chat", process_model=chat)
		doc.insert()
		self.assertTrue(frappe.db.exists("AI Agent Configuration", doc.name))

	def test_label_without_map_saves(self):
		doc = self._config("labelled_mapless", label="ZZ WI1997 Mapless")
		doc.insert()
		self.assertTrue(frappe.db.exists("AI Agent Configuration", doc.name))

	def test_process_agent_needs_no_label(self):
		biz = _model_fixture(BUSINESS_XML, "biz")
		doc = self._config("process_agent", process_model=biz)
		doc.insert()
		errors = " ".join(
			validate_agent_config(doc.name, test_provider=False)["errors"]
		)
		self.assertNotIn("chat mode label", errors)

	def test_mapless_chat_agent_still_needs_label(self):
		doc = self._config("mapless_unlabelled")
		doc.insert()
		errors = " ".join(
			validate_agent_config(doc.name, test_provider=False)["errors"]
		)
		self.assertIn("chat mode label", errors)


class TestCreateAgentWithProcessModel(FrappeTestCase):
	"""Endpoint contract: the map is a designer-chosen link at creation."""

	def setUp(self):
		super().setUp()
		if not get_creation_process_model():
			self.skipTest("no agent-creation process on this site")
		frappe.flags.in_migrate = True

	def tearDown(self):
		frappe.flags.in_migrate = False
		super().tearDown()

	def _ai_model(self):
		return frappe.db.get_value("AI Model", {"ai_provider_credentials": ("is", "set")}, "name")

	def test_links_designer_chosen_map_and_waives_label(self):
		biz = _model_fixture(BUSINESS_XML, "ep_biz")
		result = create_agent_configuration({
			"agent_name": "ZZ WI1997 Process Agent",
			"ai_model": self._ai_model(),
			"process_model": biz,
			"system_prompt": "Test prompt.",
		})
		doc = frappe.get_doc("AI Agent Configuration", result["name"])
		self.assertEqual(doc.process_model, biz)
		self.assertFalse(doc.chat_mode_label)

	def test_unknown_process_model_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			create_agent_configuration({
				"agent_name": "ZZ WI1997 Ghost Map Agent",
				"ai_model": self._ai_model(),
				"process_model": "ZZ WI1997 does not exist",
				"system_prompt": "Test prompt.",
			})

	def test_label_still_required_without_map(self):
		with self.assertRaises(frappe.ValidationError):
			create_agent_configuration({
				"agent_name": "ZZ WI1997 Mapless Agent",
				"ai_model": self._ai_model(),
				"system_prompt": "Test prompt.",
			})

	def test_label_still_required_with_chat_map(self):
		chat = _model_fixture(CHAT_XML, "ep_chat")
		with self.assertRaises(frappe.ValidationError):
			create_agent_configuration({
				"agent_name": "ZZ WI1997 Chat Map Agent",
				"ai_model": self._ai_model(),
				"process_model": chat,
				"system_prompt": "Test prompt.",
			})
