# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Response Format JSON returns the same object on every provider."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor import ErrorCode, ExecutorConfig, ExecutorContext
from one_bpmn.agents.executor.direct_api import DirectApiExecutor
from one_bpmn.agents.llm_provider import structured_output
from one_bpmn.agents.llm_provider.anthropic_adapter import AnthropicAdapter
from one_bpmn.agents.llm_provider.base import StepResult, ToolSpec
from one_bpmn.agents.llm_provider.openai_adapter import OpenAIAdapter

EXAMPLE = json.dumps({"bible_verse": "", "answer": ""})
GOOD = {"bible_verse": "John 3:16", "answer": "Love."}


def _provider(name):
	if not frappe.db.exists("AI Provider", name):
		frappe.get_doc({"doctype": "AI Provider", "provider": name}).insert(ignore_permissions=True)
	return name


def _model(name, provider, json_mode):
	if not frappe.db.exists("AI Model", name):
		frappe.get_doc(
			{
				"doctype": "AI Model",
				"model_name": name,
				"provider": _provider(provider),
				"enable_model": 1,
				"api_key": "test-key-not-real",
			}
		).insert(ignore_permissions=True)
	frappe.db.set_value("AI Model", name, "support_structured_output", 1 if json_mode else 0)
	return name


def _anthropic_body(text, stop_reason="end_turn"):
	return {
		"content": [{"type": "text", "text": text}],
		"stop_reason": stop_reason,
		"usage": {"input_tokens": 10, "output_tokens": 5},
	}


def _openai_body(text, finish_reason="stop"):
	return {
		"choices": [{"message": {"content": text}, "finish_reason": finish_reason}],
		"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
	}


class TestSchemaFromTheAuthorsFormat(FrappeTestCase):
	def test_an_example_object_becomes_a_closed_schema(self):
		schema = structured_output.normalize_response_schema(
			{"bible_verse": "", "count": 0, "ok": False, "tags": [""], "note": None, "meta": {"a": ""}}
		)
		self.assertEqual(schema["required"], ["bible_verse", "count", "ok", "tags", "note", "meta"])
		self.assertIs(schema["additionalProperties"], False)
		self.assertEqual(schema["properties"]["count"], {"type": "number"})
		self.assertEqual(schema["properties"]["ok"], {"type": "boolean"})
		self.assertEqual(schema["properties"]["tags"], {"type": "array", "items": {"type": "string"}})
		self.assertEqual(schema["properties"]["note"], {"type": ["string", "null"]})
		self.assertIs(schema["properties"]["meta"]["additionalProperties"], False)

	def test_a_full_schema_is_used_as_written(self):
		schema = {"type": "object", "properties": {"a": {"type": "string"}}}
		self.assertEqual(structured_output.normalize_response_schema(json.dumps(schema)), schema)

	def test_an_open_object_is_named_with_its_field(self):
		schema = {"type": "object", "properties": {"meta": {"type": "object", "additionalProperties": True}}}
		with self.assertRaises(structured_output.UnsupportedSchemaRule) as caught:
			structured_output.validate_schema_rules(schema)
		self.assertEqual((caught.exception.rule, caught.exception.field), ("additionalProperties", "meta"))

	def test_length_and_range_rules_pass_because_the_provider_schema_drops_them(self):
		schema = {
			"type": "object",
			"properties": {
				"title": {"type": "string", "minLength": 1, "maxLength": 80},
				"pages": {"type": "array", "items": {"type": "integer", "minimum": 1, "maximum": 9}},
			},
		}
		structured_output.validate_schema_rules(schema)

	def test_the_provider_schema_drops_rejected_rules_but_the_reply_check_keeps_them(self):
		schema = {
			"type": "object",
			"properties": {"title": {"type": "string", "minLength": 1}},
			"required": ["title"],
		}
		sent = structured_output.provider_schema(schema)
		self.assertNotIn("minLength", sent["properties"]["title"])
		self.assertIs(sent["additionalProperties"], False)
		with self.assertRaises(structured_output.ReplyRejected):
			structured_output.read_json_reply('{"title": ""}', schema)


class TestTheSaveRefusesAnUnsupportedRule(FrappeTestCase):
	def _model_doc(self, schema: str):
		attr = frappe.utils.escape_html(schema)
		doc = frappe.new_doc("BPMN Process Model")
		doc.bpmn_xml = (
			'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
			'xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core">'
			'<bpmn:process id="p"><bpmn:serviceTask id="draft" name="Draft Content" '
			f'spiffworkflow:aiResponseFormat="json" spiffworkflow:aiResponseSchema="{attr}"/>'
			"</bpmn:process></bpmn:definitions>"
		)
		return doc

	def test_an_open_object_fails_the_save_naming_task_rule_and_field(self):
		open_object = {"type": "object", "additionalProperties": True}
		doc = self._model_doc(json.dumps({"type": "object", "properties": {"meta": open_object}}))
		with self.assertRaises(frappe.ValidationError) as caught:
			doc.validate_response_schemas()
		self.assertIn("Draft Content", str(caught.exception))
		self.assertIn("additionalProperties", str(caught.exception))
		self.assertIn("meta", str(caught.exception))

	def test_a_min_length_rule_saves(self):
		self._model_doc(
			json.dumps({"type": "object", "properties": {"title": {"type": "string", "minLength": 1}}})
		).validate_response_schemas()

	def test_an_example_object_saves(self):
		self._model_doc(EXAMPLE).validate_response_schemas()


class _Response:
	def __init__(self, body):
		self.status_code = 200
		self._body = body

	def json(self):
		return self._body

	def raise_for_status(self):
		return None


class TestTheRequestCarriesTheSchema(FrappeTestCase):
	def _run(self, provider, json_mode, bodies, **config):
		model = _model(f"_json-{provider.lower()}-{int(json_mode)}", provider, json_mode)
		sent = []

		def post(url, json=None, headers=None, timeout=None):
			sent.append(json)
			return _Response(bodies[min(len(sent), len(bodies)) - 1])

		cfg = ExecutorConfig(
			provider_name=provider,
			model=model,
			system_prompt="You answer questions.",
			user_prompt="What is the capital of France?",
			response_format="json",
			response_schema=EXAMPLE,
			**{"max_retries": 0, **config},
		)
		with patch("requests.post", side_effect=post):
			result = DirectApiExecutor().run(cfg, ExecutorContext())
		return result, sent

	def test_anthropic_gets_output_config_and_no_forced_tool_choice(self):
		result, sent = self._run("Anthropic", True, [_anthropic_body(json.dumps(GOOD))])
		self.assertEqual(result.output, GOOD)
		self.assertEqual(sent[0]["output_config"]["format"]["type"], "json_schema")
		self.assertIs(sent[0]["output_config"]["format"]["schema"]["additionalProperties"], False)
		self.assertNotIn("tool_choice", sent[0])

	def test_openai_gets_a_strict_json_schema_response_format(self):
		result, sent = self._run("OpenAI", True, [_openai_body(json.dumps(GOOD))])
		self.assertEqual(result.output, GOOD)
		self.assertEqual(sent[0]["response_format"]["type"], "json_schema")
		self.assertTrue(sent[0]["response_format"]["json_schema"]["strict"])

	def test_gemini_gets_the_json_schema_on_its_openai_compatible_endpoint(self):
		_result, sent = self._run("Google", True, [_openai_body(json.dumps(GOOD))])
		self.assertEqual(sent[0]["response_format"]["type"], "json_schema")

	def test_a_model_without_json_mode_gets_the_schema_in_the_system_prompt(self):
		result, sent = self._run("OpenAI", False, [_openai_body(json.dumps(GOOD))])
		self.assertEqual(result.output, GOOD)
		self.assertNotIn("response_format", sent[0])
		system = sent[0]["messages"][0]["content"]
		self.assertIn("Reply with only one JSON object", system)
		self.assertIn('"bible_verse"', system)

	def test_every_json_agent_gets_the_field_line(self):
		_result, sent = self._run("OpenAI", True, [_openai_body(json.dumps(GOOD))])
		self.assertIn("The reply has these fields: bible_verse, answer.", sent[0]["messages"][0]["content"])

	def test_a_failed_check_is_retried_once_with_the_error_then_succeeds(self):
		result, sent = self._run(
			"OpenAI", True, [_openai_body(json.dumps({"bible_verse": "x"})), _openai_body(json.dumps(GOOD))]
		)
		self.assertEqual(result.error_code, ErrorCode.SUCCESS)
		self.assertEqual(result.output, GOOD)
		self.assertEqual(len(sent), 2)
		self.assertEqual(sent[1]["messages"][-2], {"role": "assistant", "content": '{"bible_verse": "x"}'})
		self.assertIn("missing required field 'answer'", sent[1]["messages"][-1]["content"])

	def test_a_second_failure_ends_the_run_with_schema_validation_failed(self):
		bad = _openai_body("Paris is the capital.")
		result, sent = self._run("OpenAI", True, [bad, bad], max_retries=3)
		self.assertEqual(result.error_code, ErrorCode.SCHEMA_VALIDATION_FAILED)
		self.assertEqual(len(sent), 2)

	def test_a_reply_cut_off_at_the_token_limit_is_not_parsed_or_retried(self):
		result, sent = self._run(
			"Anthropic", True, [_anthropic_body('{"bible_verse": "Jo', stop_reason="max_tokens")]
		)
		self.assertEqual(result.error_code, ErrorCode.SCHEMA_VALIDATION_FAILED)
		self.assertIn("cut off", result.error_message)
		self.assertEqual(len(sent), 1)

	def test_an_unrelated_question_still_returns_the_declared_object(self):
		reply = {"bible_verse": "", "answer": "Paris."}
		result, _sent = self._run("OpenAI", True, [_openai_body(json.dumps(reply))])
		self.assertEqual(result.output, reply)

	def test_a_missing_jsonschema_package_fails_the_run(self):
		import builtins

		real_import = builtins.__import__

		def no_jsonschema(name, *args, **kwargs):
			if name == "jsonschema":
				raise ImportError(name)
			return real_import(name, *args, **kwargs)

		with patch("builtins.__import__", side_effect=no_jsonschema):
			result, _sent = self._run("OpenAI", True, [_openai_body(json.dumps(GOOD))])
		self.assertEqual(result.error_code, ErrorCode.SCHEMA_VALIDATION_FAILED)
		self.assertIn("jsonschema", result.error_message)


class _FakeAdapter:
	def __init__(self, replies):
		self.replies = list(replies)
		self.calls = []

	async def step(self, system, transcript, tools=None, max_tokens=16384, response_schema=None):
		self.calls.append(
			{
				"system": system,
				"transcript": [dict(e) for e in transcript],
				"response_schema": response_schema,
			}
		)
		return StepResult(content=self.replies.pop(0))


class TestAgentsWithTools(FrappeTestCase):
	def _run(self, provider, replies):
		model = _model(f"_json-tools-{provider.lower()}", provider, True)
		cfg = ExecutorConfig(
			provider_name=provider,
			model=model,
			system_prompt="sys",
			user_prompt="usr",
			response_format="json",
			response_schema=EXAMPLE,
			tools=[
				ToolSpec(
					fn=lambda **kw: "ok", name="echo_tool", description="Echoes.", parameters={}, required=[]
				)
			],
		)
		fake = _FakeAdapter(replies)
		with patch("one_bpmn.agents.llm_provider.factory.get_llm_adapter", return_value=fake):
			result = DirectApiExecutor().run(cfg, ExecutorContext())
		return result, fake

	def test_the_native_schema_reaches_each_step_and_a_prose_reply_is_corrected_once(self):
		result, fake = self._run("Anthropic", ["Here you go.", json.dumps(GOOD)])
		self.assertEqual(result.output, GOOD)
		self.assertEqual(fake.calls[0]["response_schema"]["required"], ["bible_verse", "answer"])
		self.assertIn("not valid JSON", fake.calls[1]["transcript"][-1]["content"])

	def test_gemini_with_tools_uses_the_prompt_fallback(self):
		result, fake = self._run("Google", [json.dumps(GOOD)])
		self.assertEqual(result.output, GOOD)
		self.assertIsNone(fake.calls[0]["response_schema"])
		self.assertIn("Reply with only one JSON object", fake.calls[0]["system"])


class TestTheAdaptersSendTheProviderFormat(FrappeTestCase):
	SCHEMA = structured_output.normalize_response_schema(EXAMPLE)

	def test_anthropic_step_sends_output_config(self):
		sent = {}
		message = SimpleNamespace(
			content=[SimpleNamespace(type="text", text=json.dumps(GOOD))],
			stop_reason="end_turn",
			usage=SimpleNamespace(input_tokens=1, output_tokens=1),
		)

		class _Stream:
			async def __aenter__(self):
				return self

			async def __aexit__(self, *exc):
				return False

			async def get_final_message(self):
				return message

		def stream(**kwargs):
			sent.update(kwargs)
			return _Stream()

		adapter = AnthropicAdapter.__new__(AnthropicAdapter)
		adapter._model = "claude-haiku-4-5"
		adapter._client = SimpleNamespace(messages=SimpleNamespace(stream=stream))
		asyncio.run(adapter.step("sys", [{"role": "user", "content": "q"}], response_schema=self.SCHEMA))
		self.assertEqual(sent["output_config"], {"format": {"type": "json_schema", "schema": self.SCHEMA}})
		self.assertNotIn("tool_choice", sent)

	def test_openai_step_sends_response_format(self):
		create = MagicMock()

		async def fake_create(**kwargs):
			create(**kwargs)
			return SimpleNamespace(
				choices=[
					SimpleNamespace(
						finish_reason="stop", message=SimpleNamespace(content="{}", tool_calls=None)
					)
				],
				usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, prompt_tokens_details=None),
			)

		adapter = OpenAIAdapter.__new__(OpenAIAdapter)
		adapter._model = "gpt-4o"
		adapter._client = SimpleNamespace(
			chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
		)
		asyncio.run(adapter.step("sys", [{"role": "user", "content": "q"}], response_schema=self.SCHEMA))
		self.assertEqual(create.call_args.kwargs["response_format"]["json_schema"]["schema"], self.SCHEMA)
