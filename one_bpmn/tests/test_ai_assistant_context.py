# Copyright (c) 2026, one-fm and contributors
# Diagram-aware AI assistant (selector prompt authoring): the digest builder,
# server-script evidence sniffing, mode catalogs and the prompt id post-check.

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.ai_assistant import (
	FIELD_CATALOG,
	SELECTOR_FIELD_CATALOG,
	_build_diagram_digest,
	_build_current_config_block,
	_catalog_for_mode,
	_lint_recommended_prompts,
	_server_script_result_keys,
)

# Mirror of the real support-triage shape: 7 selectable heads, two of which
# chain through an XOR join into an automatic update_field task.
TRIAGE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
    id="Defs_Digest" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_Digest" isExecutable="true">
    <bpmn:startEvent id="StartEvent_1"><bpmn:outgoing>Flow_In</bpmn:outgoing></bpmn:startEvent>
    <bpmn:sequenceFlow id="Flow_In" sourceRef="StartEvent_1" targetRef="Triage" />
    <bpmn:adHocSubProcess id="Triage" name="Support Triage" spiffworkflow:serviceType="ai_task_selector">
      <bpmn:incoming>Flow_In</bpmn:incoming>
      <bpmn:outgoing>Flow_Out</bpmn:outgoing>
      <bpmn:scriptTask id="look_up_order" name="Look up order" spiffworkflow:serverScript="Digest Test Lookup">
        <bpmn:documentation>Check the description for a Sales Order.</bpmn:documentation>
      </bpmn:scriptTask>
      <bpmn:serviceTask id="Activity_0q9helm" name="Set Status for Support"
          spiffworkflow:serviceType="update_field"
          spiffworkflow:updateFieldDoctype="HD Ticket"
          spiffworkflow:updateFieldRows="[{&#34;field&#34;:&#34;status&#34;,&#34;value&#34;:&#34;Pending Support Confirmation&#34;}]" />
      <bpmn:userTask id="Activity_02s5ksc" name="Escalate to Support agent"
          spiffworkflow:assigneeMode="DocField" spiffworkflow:assigneeDocfield="owner">
        <bpmn:outgoing>Flow_Esc</bpmn:outgoing>
      </bpmn:userTask>
      <bpmn:exclusiveGateway id="Gateway_1">
        <bpmn:incoming>Flow_Esc</bpmn:incoming>
        <bpmn:outgoing>Flow_Set</bpmn:outgoing>
      </bpmn:exclusiveGateway>
      <bpmn:serviceTask id="Activity_06nuvut" name="Set Ticket Status to Responded"
          spiffworkflow:serviceType="update_field"
          spiffworkflow:updateFieldDoctype="HD Ticket"
          spiffworkflow:updateFieldRows="[{&#34;field&#34;:&#34;status&#34;,&#34;value&#34;:&#34;Support Resolved&#34;}]">
        <bpmn:incoming>Flow_Set</bpmn:incoming>
      </bpmn:serviceTask>
      <bpmn:sequenceFlow id="Flow_Esc" sourceRef="Activity_02s5ksc" targetRef="Gateway_1" />
      <bpmn:sequenceFlow id="Flow_Set" sourceRef="Gateway_1" targetRef="Activity_06nuvut" />
      <bpmn:sendTask id="Activity_1nxthko" name="Send reply email" spiffworkflow:notificationName="Ticket In Progress" />
      <bpmn:scriptTask id="resolve" name="Mark resolved">
        <bpmn:script>done = True</bpmn:script>
      </bpmn:scriptTask>
      <bpmn:completionCondition xsi:type="bpmn:tFormalExpression">done</bpmn:completionCondition>
    </bpmn:adHocSubProcess>
    <bpmn:sequenceFlow id="Flow_Out" sourceRef="Triage" targetRef="EndEvent_1" />
    <bpmn:endEvent id="EndEvent_1"><bpmn:incoming>Flow_Out</bpmn:incoming></bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>
"""


class TestDiagramDigest(FrappeTestCase):
	def digest(self):
		return _build_diagram_digest(TRIAGE_XML, "Triage")

	def test_candidates_are_heads_only(self):
		digest = self.digest()
		self.assertEqual(
			sorted(digest["candidate_ids"]),
			sorted(["look_up_order", "Activity_0q9helm", "Activity_02s5ksc", "Activity_1nxthko", "resolve"]),
		)
		# Chained continuation + gateway must NOT be selectable
		self.assertNotIn("Activity_06nuvut", digest["candidate_ids"])
		self.assertNotIn("Gateway_1", digest["candidate_ids"])

	def test_chain_described_with_observable_effect(self):
		block = self.digest()["block"]
		self.assertIn("then AUTOMATICALLY", block)
		self.assertIn('sets HD Ticket.status = "Support Resolved"', block)

	def test_update_field_effects_and_notification_surface(self):
		block = self.digest()["block"]
		self.assertIn('sets HD Ticket.status = "Pending Support Confirmation"', block)
		self.assertIn('sends notification "Ticket In Progress"', block)

	def test_completion_condition_included(self):
		self.assertIn("COMPLETION CONDITION", self.digest()["block"])
		self.assertIn("done", self.digest()["block"])

	def test_no_adhoc_returns_none(self):
		self.assertIsNone(_build_diagram_digest("<bad xml", "Triage"))
		self.assertIsNone(_build_diagram_digest(TRIAGE_XML, "NoSuchElement"))


class TestServerScriptSniffing(FrappeTestCase):
	def test_result_keys_extracted(self):
		script = frappe.get_doc({
			"doctype": "Server Script",
			"name": "Digest Test Lookup",
			"script_type": "API",
			"api_method": "digest_test_lookup",
			"script": 'result["is_sales"] = 0\nresult["sales_order"] = ""\nresult["is_sales"] = 1',
		})
		script.insert(ignore_permissions=True)
		self.assertEqual(_server_script_result_keys("Digest Test Lookup"), ["is_sales", "sales_order"])
		# and the digest embeds them as evidence variables
		digest = _build_diagram_digest(TRIAGE_XML, "Triage")
		self.assertIn("is_sales", digest["block"])

	def test_missing_script_is_safe(self):
		self.assertEqual(_server_script_result_keys("No Such Script"), [])


class TestPromptLint(FrappeTestCase):
	DIGEST = {
		"candidate_ids": ["look_up_order", "Activity_0q9helm", "resolve"],
		"element_ids": {"look_up_order", "Activity_0q9helm", "Gateway_1", "Activity_06nuvut", "resolve"},
	}

	def test_unknown_id_flagged(self):
		warnings = _lint_recommended_prompts(
			{"aiSystemPrompt": "Activate Activity_deadbeef then look_up_order, Activity_0q9helm, resolve."},
			self.DIGEST,
		)
		self.assertTrue(any("Activity_deadbeef" in w for w in warnings))

	def test_unmentioned_candidate_flagged(self):
		warnings = _lint_recommended_prompts(
			{"aiSystemPrompt": "Activate look_up_order then resolve."},
			self.DIGEST,
		)
		self.assertTrue(any("Activity_0q9helm" in w for w in warnings))

	def test_clean_prompt_no_warnings(self):
		warnings = _lint_recommended_prompts(
			{"aiSystemPrompt": "look_up_order, then Activity_0q9helm, then resolve (via Gateway_1)."},
			self.DIGEST,
		)
		self.assertEqual(warnings, [])


class TestModeCatalog(FrappeTestCase):
	def test_selector_catalog_excludes_agent_only_fields(self):
		self.assertIn("aiSystemPrompt", SELECTOR_FIELD_CATALOG)
		self.assertNotIn("aiOutputVariable", SELECTOR_FIELD_CATALOG)
		self.assertNotIn("aiResponseSchema", SELECTOR_FIELD_CATALOG)
		self.assertIs(_catalog_for_mode("selector"), SELECTOR_FIELD_CATALOG)
		self.assertIs(_catalog_for_mode("agent"), FIELD_CATALOG)
		self.assertIs(_catalog_for_mode("bogus"), FIELD_CATALOG)

	def test_current_config_block_filters_by_catalog(self):
		block = _build_current_config_block(
			'{"aiSystemPrompt": "draft", "aiOutputVariable": "x", "aiUserPrompt": ""}',
			SELECTOR_FIELD_CATALOG,
		)
		self.assertIn("aiSystemPrompt", block)
		self.assertNotIn("aiOutputVariable", block)

# TestRegistryToolsInDigest was removed with the AI Agent Tool registry
# (WI-001423): a selector's tools are its ad-hoc sub-process shapes, which the
# TestDiagramDigest cases above already cover.
