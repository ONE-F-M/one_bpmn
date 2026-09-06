# Copyright (c) 2026, one-fm and contributors
"""A prompt that tells the model to call a tool the map does not have.

The Frontend Agent ran for weeks on a prompt ordering draft_change, review_change
and propose_pull_request — none existed — and every delegation ended "staged but
never delivered". This is the deploy-time check that would have refused it.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api import compilation as comp

OLD_FRONTEND_PROMPT = (
	"4. Call draft_change once per file. 6. Call review_change. "
	"7. Call propose_pull_request with a title. 8. Call finalize exactly once. "
	"Always call register_hook. 3. Call dispatch_to_sandbox with the app."
)
BOX = {"locate_ui", "read_file", "edit_file", "run_tests", "open_pull_request"}
KNOWN = BOX | {"finalize"}  # finalize is a real tool on other maps


def _agents(prompt, tools=BOX, config=""):
	return {
		"build_change": {
			"serviceType": "ai_agent",
			"aiToolsAdhoc": "tools",
			"aiAgentConfig": config,
			"aiSystemPrompt": prompt,
			"aiToolShapes": json.dumps([{"bpmn_id": t} for t in sorted(tools)]),
		}
	}


class TestToolContractGaps(FrappeTestCase):
	def test_the_old_frontend_prompt_is_caught_in_full(self):
		self.assertEqual(
			comp._tool_contract_gaps(OLD_FRONTEND_PROMPT, BOX, KNOWN),
			["dispatch_to_sandbox", "draft_change", "finalize", "propose_pull_request", "register_hook", "review_change"],
		)

	def test_only_a_calling_position_counts(self):
		prompt = "Set target_app to one_bpmn. The hooks.py entry goes under doctype_js. Call read_file first."
		self.assertEqual(comp._tool_contract_gaps(prompt, BOX, KNOWN), [])

	def test_english_after_call_is_not_a_tool(self):
		prompt = "This is called before the review. Call it once per file, and call back when done."
		self.assertEqual(comp._tool_contract_gaps(prompt, BOX, KNOWN), [])

	def test_a_bare_word_counts_only_when_some_map_has_that_tool(self):
		self.assertEqual(comp._tool_contract_gaps("Call finalize last.", BOX, KNOWN), ["finalize"])
		self.assertEqual(comp._tool_contract_gaps("Call finalize last.", BOX, set()), [])

	def test_backticks_and_case_do_not_hide_a_reference(self):
		self.assertEqual(comp._tool_contract_gaps("Then CALL `draft_change`.", BOX, KNOWN), ["draft_change"])


class TestValidateAiToolContract(FrappeTestCase):
	def setUp(self):
		self._known = patch.object(comp, "_known_tool_ids", return_value=KNOWN)
		self._known.start()

	def tearDown(self):
		self._known.stop()

	def test_a_clean_prompt_passes_silently(self):
		self.assertEqual(comp._validate_ai_tool_contract(_agents("Call read_file, then call open_pull_request.")), [])

	def test_a_background_agent_with_a_dead_tool_blocks_the_deploy(self):
		with patch.object(frappe.db, "exists", return_value=True), patch.object(
			frappe.db, "get_value", return_value=frappe._dict(system_prompt=OLD_FRONTEND_PROMPT, agent_type="Background")
		):
			with self.assertRaises(frappe.ValidationError) as caught:
				comp._validate_ai_tool_contract(_agents("irrelevant — the configuration's prompt wins", config="Frontend Agent"))
		self.assertIn("draft_change", str(caught.exception))
		self.assertIn("build_change", str(caught.exception))

	def test_a_chat_agent_with_a_dead_tool_only_warns(self):
		with patch.object(frappe.db, "exists", return_value=True), patch.object(
			frappe.db, "get_value", return_value=frappe._dict(system_prompt="Call create_jira_stories.", agent_type="Chat")
		):
			warnings = comp._validate_ai_tool_contract(_agents("", config="BA Agent"))
		self.assertEqual(len(warnings), 1)
		self.assertEqual(warnings[0]["label"], "Tool Contract")
		self.assertIn("create_jira_stories", warnings[0]["detail"])

	def test_without_a_configuration_the_shape_prompt_is_checked(self):
		with patch.object(frappe.db, "exists", return_value=False):
			warnings = comp._validate_ai_tool_contract(_agents("Call review_change."))
		self.assertEqual([w["label"] for w in warnings], ["Tool Contract"])

	def test_agents_without_a_tools_box_are_ignored(self):
		self.assertEqual(comp._validate_ai_tool_contract({"x": {"serviceType": "ai_agent"}}), [])


class TestSeedPromptsMatchTheirMaps(FrappeTestCase):
	"""The seed patches are what a fresh site gets. Each must only ask for tools the
	agent's live map actually has — the exact way the Frontend prompt went stale."""

	SEEDS = (
		("one_bpmn.one_bpmn.patches.v1_0.seed_frontend_agent_config", "Frontend Agent"),
		("one_bpmn.one_bpmn.patches.v1_0.seed_dev_agent_config", "Dev Agent"),
		("one_bpmn.one_bpmn.patches.v1_0.seed_mobile_app_agent_config", "Mobile App Agent"),
	)
	RETIRED = ("dispatch_to_sandbox", "draft_change", "review_change", "propose_pull_request",
	           "stage_change", "read_repo_map", "register_hook", "finalize")

	def _live_tool_ids(self, model):
		spec = frappe.db.get_value("BPMN Process Model", model, "serialized_spec")
		if not spec:
			self.skipTest(f"{model} is not compiled on this site")
		ids = set()
		for cfg in (json.loads(spec).get("service_task_extensions") or {}).values():
			ids |= {s["bpmn_id"] for s in json.loads(cfg.get("aiToolShapes") or "[]")}
		return ids

	def test_no_seed_names_a_retired_tool(self):
		for module, _model in self.SEEDS:
			prompt = frappe.get_attr(module + "._SYSTEM_PROMPT")
			called = {m.lower() for m in comp._TOOL_CALL_RE.findall(prompt)}
			self.assertEqual(sorted(called & set(self.RETIRED)), [], module)

	def test_every_tool_a_seed_calls_exists_on_the_live_map(self):
		for module, model in self.SEEDS:
			prompt = frappe.get_attr(module + "._SYSTEM_PROMPT")
			gaps = comp._tool_contract_gaps(prompt, self._live_tool_ids(model), comp._known_tool_ids())
			self.assertEqual(gaps, [], f"{model}: {gaps}")
