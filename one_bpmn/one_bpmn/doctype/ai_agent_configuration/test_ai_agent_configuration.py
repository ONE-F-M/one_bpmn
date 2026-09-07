# Copyright (c) 2026, Kartik Sharma and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import (
	_cast_constant,
	_load_json_constant,
	get_agent_config,
)


class TestAIAgentConfiguration(FrappeTestCase):
	"""Tests for AI Agent Configuration DocType and get_agent_config utility."""

	def _cleanup_test_record(self):
		"""Remove any existing test record by agent_id or name."""
		frappe.cache.delete_value("agent_config:test_agent_unit")
		# The document name is derived from agent_name, so look up by both
		existing = frappe.db.exists("AI Agent Configuration", {"agent_id": "test_agent_unit"})
		if existing:
			frappe.delete_doc("AI Agent Configuration", existing, force=True)
		# Also check by the expected name ("Test Agent") in case agent_id was changed
		if frappe.db.exists("AI Agent Configuration", "Test Agent"):
			frappe.delete_doc("AI Agent Configuration", "Test Agent", force=True)
		frappe.db.commit()

	def setUp(self):
		"""Create a test agent configuration record."""
		self._cleanup_test_record()

		self.test_doc = frappe.get_doc({
			"doctype": "AI Agent Configuration",
			"agent_name": "Test Agent",
			"agent_id": "test_agent_unit",
			"agent_framework": "LangGraph",
			"enabled": 1,
			"temperature": 0.5,
			"max_tokens": 1000,
			"llm_provider_override": "Use Global",
			"system_prompt": "You are a test agent.",
			"langsmith_project": "test-project",
			"constants": [
				{
					"constant_name": "max_retries",
					"constant_value": "3",
					"constant_type": "Integer",
				},
				{
					"constant_name": "threshold",
					"constant_value": "0.85",
					"constant_type": "Float",
				},
				{
					"constant_name": "verbose",
					"constant_value": "true",
					"constant_type": "Boolean",
				},
				{
					"constant_name": "label",
					"constant_value": "hello",
					"constant_type": "String",
				},
			],
			"sub_prompts": [
				{
					"sub_agent_id": "analyzer",
					"sub_agent_name": "Analyzer Sub-Agent",
					"prompt_text": "Analyze the input carefully.",
					"temperature": 0.2,
				},
			],
		})
		self.test_doc.insert(ignore_permissions=True)
		frappe.db.commit()

	def tearDown(self):
		"""Clean up test data."""
		self._cleanup_test_record()

	def test_get_agent_config_returns_valid_config(self):
		"""Test that get_agent_config returns a properly structured dict."""
		config = get_agent_config("test_agent_unit")

		self.assertIsNotNone(config)
		self.assertEqual(config["system_prompt"], "You are a test agent.")
		self.assertEqual(config["temperature"], 0.5)
		self.assertEqual(config["max_tokens"], 1000)
		self.assertEqual(config["llm_provider_override"], "Use Global")
		self.assertEqual(config["langsmith_project"], "test-project")

	def test_get_agent_config_returns_none_for_missing(self):
		"""Test that get_agent_config returns None for a non-existent agent."""
		config = get_agent_config("nonexistent_agent_xyz")
		self.assertIsNone(config)

	def test_get_agent_config_returns_none_for_disabled(self):
		"""Test that disabled agents return None."""
		self.test_doc.enabled = 0
		self.test_doc.save(ignore_permissions=True)
		frappe.db.commit()

		# Clear cache since save triggers on_update
		config = get_agent_config("test_agent_unit")
		self.assertIsNone(config)

	def test_constants_type_casting(self):
		"""Test that constants are correctly cast to their declared types."""
		config = get_agent_config("test_agent_unit")

		self.assertEqual(config["constants"]["max_retries"], 3)
		self.assertIsInstance(config["constants"]["max_retries"], int)

		self.assertAlmostEqual(config["constants"]["threshold"], 0.85)
		self.assertIsInstance(config["constants"]["threshold"], float)

		self.assertTrue(config["constants"]["verbose"])
		self.assertIsInstance(config["constants"]["verbose"], bool)

		self.assertEqual(config["constants"]["label"], "hello")
		self.assertIsInstance(config["constants"]["label"], str)

	def test_sub_prompts_loaded(self):
		"""Test that sub-prompts are loaded and keyed by sub_agent_id."""
		config = get_agent_config("test_agent_unit")

		self.assertIn("analyzer", config["sub_prompts"])
		self.assertEqual(config["sub_prompts"]["analyzer"]["prompt"], "Analyze the input carefully.")
		self.assertEqual(config["sub_prompts"]["analyzer"]["temperature"], 0.2)

	def test_cache_is_populated(self):
		"""Test that the first call populates the cache."""
		# Ensure cache is empty
		frappe.cache.delete_value("agent_config:test_agent_unit")
		self.assertIsNone(frappe.cache.get_value("agent_config:test_agent_unit"))

		# Call get_agent_config — should populate cache
		config = get_agent_config("test_agent_unit")
		self.assertIsNotNone(config)

		# Cache should now have a value
		cached = frappe.cache.get_value("agent_config:test_agent_unit")
		self.assertIsNotNone(cached)
		self.assertEqual(cached["system_prompt"], "You are a test agent.")

	def test_cache_invalidated_on_save(self):
		"""Test that saving the doc clears the cache via on_update."""
		# Populate cache
		get_agent_config("test_agent_unit")
		self.assertIsNotNone(frappe.cache.get_value("agent_config:test_agent_unit"))

		# Save doc — should invalidate cache
		self.test_doc.system_prompt = "Updated prompt."
		self.test_doc.save(ignore_permissions=True)
		frappe.db.commit()

		# Cache should be cleared
		self.assertIsNone(frappe.cache.get_value("agent_config:test_agent_unit"))

		# Next call should return updated value
		config = get_agent_config("test_agent_unit")
		self.assertEqual(config["system_prompt"], "Updated prompt.")


class TestCastConstant(FrappeTestCase):
	"""Tests for the _cast_constant helper function."""

	def test_cast_integer(self):
		self.assertEqual(_cast_constant("42", "Integer"), 42)
		self.assertEqual(_cast_constant("0", "Integer"), 0)
		self.assertEqual(_cast_constant("-5", "Integer"), -5)

	def test_cast_float(self):
		self.assertAlmostEqual(_cast_constant("3.14", "Float"), 3.14)
		self.assertAlmostEqual(_cast_constant("0.0", "Float"), 0.0)

	def test_cast_boolean(self):
		self.assertTrue(_cast_constant("true", "Boolean"))
		self.assertTrue(_cast_constant("1", "Boolean"))
		self.assertTrue(_cast_constant("yes", "Boolean"))
		self.assertFalse(_cast_constant("false", "Boolean"))
		self.assertFalse(_cast_constant("0", "Boolean"))
		self.assertFalse(_cast_constant("no", "Boolean"))

	def test_cast_string(self):
		self.assertEqual(_cast_constant("hello", "String"), "hello")
		self.assertEqual(_cast_constant("", "String"), "")

	def test_cast_unknown_type_returns_string(self):
		"""Unknown types should return the raw string value."""
		self.assertEqual(_cast_constant("anything", "JSON"), "anything")


class TestLoadJsonConstant(FrappeTestCase):
	"""Tests for the _load_json_constant helper used by all ported agent files."""

	def test_returns_default_when_config_is_none(self):
		default = ["a", "b"]
		result = _load_json_constant(None, "key", default)
		self.assertEqual(result, default)

	def test_returns_default_when_key_missing(self):
		config = {"constants": {"other_key": '["x"]'}}
		default = ["a", "b"]
		result = _load_json_constant(config, "key", default)
		self.assertEqual(result, default)

	def test_parses_valid_json_array(self):
		config = {"constants": {"my_list": '["yes", "no", "maybe"]'}}
		result = _load_json_constant(config, "my_list", ["default"])
		self.assertEqual(result, ["yes", "no", "maybe"])

	def test_returns_default_for_invalid_json(self):
		config = {"constants": {"bad": "not valid json ["}}
		default = ["fallback"]
		result = _load_json_constant(config, "bad", default)
		self.assertEqual(result, default)

	def test_returns_default_for_non_list_json(self):
		"""If the JSON parses to a dict or string, we still want a list fallback."""
		config = {"constants": {"obj": '{"key": "value"}'}}
		default = ["fallback"]
		result = _load_json_constant(config, "obj", default)
		self.assertEqual(result, default)


class TestRequiredVariablesValidation(FrappeTestCase):
	"""Tests for validate_required_variables() on AI Agent Configuration."""

	def _make_config(self, system_prompt, required_variables, sub_prompts=None):
		"""Create a transient doc for validation testing (not saved)."""
		doc_dict = {
			"doctype": "AI Agent Configuration",
			"agent_name": f"_Test Validate {frappe.generate_hash(length=6)}",
			"agent_id": f"_test_validate_{frappe.generate_hash(length=6)}",
			"agent_framework": "LangGraph",
			"system_prompt": system_prompt,
			"required_variables": required_variables,
			"enabled": 1,
		}
		if sub_prompts:
			doc_dict["sub_prompts"] = sub_prompts
		doc = frappe.get_doc(doc_dict)
		return doc

	def test_missing_variable_throws(self):
		"""Prompt missing a required variable should throw."""
		doc = self._make_config(
			system_prompt="Hello world",
			required_variables='[{"name": "user_name"}]',
		)
		with self.assertRaises(frappe.ValidationError):
			doc.insert()

	def test_all_variables_present_passes(self):
		"""Prompt containing all required variables should save."""
		doc = self._make_config(
			system_prompt="Hello {user_name}, welcome!",
			required_variables='[{"name": "user_name"}]',
		)
		doc.insert()
		self.assertTrue(frappe.db.exists("AI Agent Configuration", doc.name))
		doc.delete()

	def test_empty_required_variables_passes(self):
		"""No required_variables should save without error."""
		doc = self._make_config(
			system_prompt="Hello world",
			required_variables="",
		)
		doc.insert()
		self.assertTrue(frappe.db.exists("AI Agent Configuration", doc.name))
		doc.delete()

	def test_malformed_json_passes(self):
		"""Malformed JSON in required_variables should not crash (graceful skip)."""
		doc = self._make_config(
			system_prompt="Hello world",
			required_variables="not valid json [",
		)
		doc.insert()
		self.assertTrue(frappe.db.exists("AI Agent Configuration", doc.name))
		doc.delete()

	def test_sub_prompt_variable_present_passes(self):
		"""Variable sourced from a sub-prompt should validate against that sub-prompt."""
		doc = self._make_config(
			system_prompt="Hello world",
			required_variables='[{"name": "process_name", "source": "ack_prompt"}]',
			sub_prompts=[{
				"sub_agent_id": "ack_prompt",
				"sub_agent_name": "Ack Prompt",
				"prompt_text": "Found process: {process_name}"
			}],
		)
		doc.insert()
		self.assertTrue(frappe.db.exists("AI Agent Configuration", doc.name))
		doc.delete()

	def test_sub_prompt_variable_missing_throws(self):
		"""Variable sourced from a sub-prompt that is missing from the sub-prompt text should throw."""
		doc = self._make_config(
			system_prompt="Hello world",
			required_variables='[{"name": "process_name", "source": "ack_prompt"}]',
			sub_prompts=[{
				"sub_agent_id": "ack_prompt",
				"sub_agent_name": "Ack Prompt",
				"prompt_text": "Found a process."
			}],
		)
		with self.assertRaises(frappe.ValidationError):
			doc.insert()

