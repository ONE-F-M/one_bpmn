# Copyright (c) 2026, one-fm and contributors
"""
Unit tests for Logix's deterministic tools (agents/google_adk/script_task_agent/tools.py).

Covers the extracted transforms (security validate + hints, unified diff, code
extraction) and the LOGIX_TOOLS registry. No LLM calls.
"""

import json

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.google_adk.script_task_agent import tools


class TestLogixValidateScript(FrappeTestCase):
    def test_safe_script_is_valid_no_hints(self):
        out = tools.validate_script("doc = frappe.get_doc('Employee', 'HR-001')\nfrappe.msgprint(doc.name)")
        self.assertTrue(out["valid"])
        self.assertEqual(out["violations"], [])
        self.assertEqual(out["fix_hints"], [])

    def test_forbidden_import_is_flagged_with_guidance(self):
        out = tools.validate_script("import os\nos.system('ls')")
        self.assertFalse(out["valid"])
        self.assertTrue(out["violations"])
        self.assertEqual(out["fix_hints"], [tools.SAFE_REWRITE_GUIDANCE])

    def test_syntax_error_is_invalid(self):
        out = tools.validate_script("def broken(:\n    pass")
        self.assertFalse(out["valid"])
        self.assertTrue(any("Syntax error" in v for v in out["violations"]))


class TestLogixDiff(FrappeTestCase):
    def test_diff_of_changed_scripts(self):
        out = tools.diff_scripts("a = 1\nb = 2\n", "a = 1\nb = 3\n")
        self.assertIn("-b = 2", out["diff"])
        self.assertIn("+b = 3", out["diff"])

    def test_identical_scripts_have_empty_diff(self):
        self.assertEqual(tools.diff_scripts("x = 1\n", "x = 1\n")["diff"], "")


class TestLogixExtractCode(FrappeTestCase):
    def test_extracts_fenced_python(self):
        text = "Here you go:\n```python\nx = 1\nprint(x)\n```\nHope that helps."
        self.assertEqual(tools.extract_code(text), "x = 1\nprint(x)")

    def test_returns_whole_text_when_no_fence(self):
        self.assertEqual(tools.extract_code("  just some text  "), "just some text")

    def test_handles_empty(self):
        self.assertEqual(tools.extract_code(""), "")


class TestLogixRegistry(FrappeTestCase):
    def test_registry_has_expected_tools(self):
        names = {t.name for t in tools.LOGIX_TOOLS}
        self.assertEqual(
            names,
            {
                "list_api_server_scripts",
                "get_server_script_content",
                "get_server_script_meta",
                "get_doctype_fields",
                "validate_script",
                "diff_scripts",
            },
        )

    def test_toolspecs_have_valid_schemas(self):
        for spec in tools.LOGIX_TOOLS:
            self.assertTrue(spec.name)
            self.assertTrue(spec.description)
            self.assertIsInstance(spec.parameters, dict)
            self.assertIsInstance(spec.required, list)
            for req in spec.required:
                self.assertIn(req, spec.parameters)

    def test_writer_and_clarifier_bundles(self):
        writer = {t.name for t in tools.WRITER_TOOLS}
        clarifier = {t.name for t in tools.CLARIFIER_TOOLS}
        self.assertEqual(
            writer,
            {"get_server_script_content", "get_server_script_meta", "list_api_server_scripts", "get_doctype_fields"},
        )
        self.assertEqual(clarifier, {"list_api_server_scripts", "get_server_script_meta"})

    def test_validate_script_tool_fn_returns_json(self):
        by_name = {t.name: t for t in tools.LOGIX_TOOLS}
        parsed = json.loads(by_name["validate_script"].fn(code="import os"))
        self.assertFalse(parsed["valid"])
        self.assertIn("fix_hints", parsed)

    def test_read_tool_fn_is_callable_and_returns_json_string(self):
        # list_api_server_scripts hits the DB but is read-only and always returns
        # a JSON string (possibly "[]"). Verify the wiring, not the contents.
        by_name = {t.name: t for t in tools.LOGIX_TOOLS}
        raw = by_name["list_api_server_scripts"].fn()
        self.assertIsInstance(raw, str)
        json.loads(raw)  # must be valid JSON
