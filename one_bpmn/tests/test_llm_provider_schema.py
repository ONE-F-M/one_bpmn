# Copyright (c) 2026, one-fm and contributors
# Regression coverage: each provider adapter's tool-definition builder must
# pass through a parameter's full JSON Schema (enum, array items) rather than
# flattening it to bare type/description — a tool's aiToolParams may document
# constraints (e.g. an enum of allowed doctypes) the LLM needs to call it
# correctly.

from __future__ import annotations

from google.genai import types

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.llm_provider.anthropic_adapter import _build_tool_def as _anthropic_tool_def
from one_bpmn.agents.llm_provider.base import ToolSpec, build_parameter_schema
from one_bpmn.agents.llm_provider.gemini import _build_fn_decl
from one_bpmn.agents.llm_provider.openai_adapter import _build_tool_def as _openai_tool_def


def _tool() -> ToolSpec:
	return ToolSpec(
		fn=lambda **kw: "",
		name="query_documents",
		description="Query documents.",
		parameters={
			"doctype": {"type": "string", "enum": ["ToDo", "Task"], "description": "The doctype"},
			"fields": {"type": "array", "items": {"type": "string"}, "description": "Fields to return"},
		},
		required=["doctype"],
	)


class TestBuildParameterSchema(FrappeTestCase):
	def test_preserves_enum_and_items(self):
		schema = build_parameter_schema(_tool())
		self.assertEqual(schema["properties"]["doctype"]["enum"], ["ToDo", "Task"])
		self.assertEqual(schema["properties"]["fields"]["items"], {"type": "string"})
		self.assertEqual(schema["required"], ["doctype"])


class TestOpenAIToolDef(FrappeTestCase):
	def test_enum_reaches_function_schema(self):
		tool_def = _openai_tool_def(_tool())
		props = tool_def["function"]["parameters"]["properties"]
		self.assertEqual(props["doctype"]["enum"], ["ToDo", "Task"])
		self.assertEqual(tool_def["function"]["parameters"]["required"], ["doctype"])


class TestAnthropicToolDef(FrappeTestCase):
	def test_enum_reaches_input_schema(self):
		tool_def = _anthropic_tool_def(_tool())
		props = tool_def["input_schema"]["properties"]
		self.assertEqual(props["doctype"]["enum"], ["ToDo", "Task"])


class TestGeminiFunctionDeclaration(FrappeTestCase):
	def test_enum_and_items_reach_schema(self):
		decl = _build_fn_decl(_tool())
		doctype_schema = decl.parameters.properties["doctype"]
		self.assertEqual(doctype_schema.enum, ["ToDo", "Task"])
		fields_schema = decl.parameters.properties["fields"]
		self.assertEqual(fields_schema.type, types.Type.ARRAY)
		self.assertEqual(fields_schema.items.type, types.Type.STRING)

	def test_no_parameters_is_none(self):
		tool = ToolSpec(fn=lambda **kw: "", name="no_args", description="No args.")
		decl = _build_fn_decl(tool)
		self.assertIsNone(decl.parameters)
