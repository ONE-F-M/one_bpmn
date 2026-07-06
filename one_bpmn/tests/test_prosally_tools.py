# Copyright (c) 2026, one-fm and contributors
"""
Unit tests for ProsAlly's deterministic tools (agents/google_adk/prosally_agent/tools.py).

These cover the non-LLM pipeline steps that were extracted into ToolSpec-backed
functions: diagram reading, IR compilation, semantic validation + hint
translation, property preservation, and the registry itself. No LLM calls.
"""

import json

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.google_adk.prosally_agent import tools


# A minimal, lint-clean IR (same shape the pipeline test uses).
_GOOD_IR = {
    "name": "Leave Request",
    "nodes": [
        {"id": "start", "type": "startEvent", "name": "Request Received"},
        {"id": "task_fill", "type": "userTask", "name": "Fill Leave Form"},
        {"id": "gw", "type": "exclusiveGateway", "name": "Approved?"},
        {"id": "ok", "type": "scriptTask", "name": "Send Approval Email"},
        {"id": "no", "type": "scriptTask", "name": "Send Rejection Email"},
        {"id": "end_ok", "type": "endEvent", "name": "Approved"},
        {"id": "end_no", "type": "endEvent", "name": "Rejected"},
    ],
    "flows": [
        {"from": "start", "to": "task_fill", "name": "Begin"},
        {"from": "task_fill", "to": "gw", "name": "Submitted"},
        {"from": "gw", "to": "ok", "name": "Yes", "condition": "approved == true"},
        {"from": "gw", "to": "no", "name": "No", "default": True},
        {"from": "ok", "to": "end_ok", "name": "Done"},
        {"from": "no", "to": "end_no", "name": "Done"},
    ],
}


class TestProsAllyDiagramReading(FrappeTestCase):
    def test_extract_process_name_prefers_participant(self):
        xml = '<bpmn:Participant id="p" name="Leave Flow" /><bpmn:Process id="Process_1" name="ignored" />'
        self.assertEqual(tools.extract_process_name(xml), "Leave Flow")

    def test_extract_process_name_falls_back_to_process(self):
        # Participant named the literal "Process" is treated as unnamed → fall back.
        xml = '<bpmn:Participant id="p" name="Process" /><bpmn:Process id="Process_1" name="Real Name" />'
        self.assertEqual(tools.extract_process_name(xml), "Real Name")

    def test_extract_process_name_empty(self):
        self.assertEqual(tools.extract_process_name(""), "")
        self.assertEqual(tools.extract_process_name("<bpmn:Process id='x' />"), "")

    def test_extract_element_ids_skips_structural(self):
        xml = (
            '<bpmn:process id="Process_1">'
            '<bpmn:startEvent id="StartEvent_1" name="Go" />'
            '<bpmn:userTask id="Task_1" name="Do it" />'
            '<bpmn:laneSet id="LaneSet_1"><bpmn:lane id="Lane_1" name="HR" /></bpmn:laneSet>'
            '</bpmn:process>'
        )
        table = tools.extract_element_ids(xml)
        self.assertIn('startEvent id="StartEvent_1" name="Go"', table)
        self.assertIn('userTask id="Task_1" name="Do it"', table)
        # process / laneSet / lane are structural and must be skipped
        self.assertNotIn('id="Process_1"', table)
        self.assertNotIn('id="LaneSet_1"', table)
        self.assertNotIn('id="Lane_1"', table)

    def test_get_diagram_facts_shape(self):
        xml = '<bpmn:process id="P"><bpmn:laneSet id="L" /><bpmn:userTask id="T_1" name="A" /></bpmn:process>'
        facts = tools.get_diagram_facts(xml)
        self.assertEqual(set(facts), {"process_name", "has_lanes", "element_ids"})
        self.assertTrue(facts["has_lanes"])
        self.assertIn('userTask id="T_1"', facts["element_ids"])

    def test_has_lanes_false_for_flat(self):
        self.assertFalse(tools.has_lanes('<bpmn:process id="P"><bpmn:userTask id="T" /></bpmn:process>'))


class TestProsAllyCompileIr(FrappeTestCase):
    def test_compile_good_ir(self):
        result = tools.compile_ir(_GOOD_IR)
        self.assertTrue(result.get("ok"), msg=f"problems: {result.get('problems')}")
        self.assertTrue(result.get("xml", "").strip().startswith("<?xml"))

    def test_compile_bad_ir_never_raises(self):
        # Garbage IR: must return a structured failure, never throw.
        result = tools.compile_ir({"nodes": "not-a-list", "flows": 123})
        self.assertIn("ok", result)
        self.assertFalse(result["ok"])
        self.assertTrue(result.get("problems"))


class TestProsAllyValidation(FrappeTestCase):
    def test_clean_compile_yields_no_actionable_hints(self):
        # A lint-clean compiled IR raises only `no-bpmndi` (edge DI is added at
        # render time — an intentionally ignorable rule), so there are no
        # actionable fix_hints. fix_hints emptiness is the signal a self-repair
        # loop stops on, not raw `valid`.
        xml = tools.compile_ir(_GOOD_IR)["xml"]
        out = tools.validate_bpmn(xml)
        self.assertEqual(out["fix_hints"], [])

    def test_invalid_xml_reports_violations_and_hints(self):
        out = tools.validate_bpmn("<nonsense/>")
        self.assertFalse(out["valid"])
        self.assertTrue(out["violations"])
        self.assertEqual(len(out["fix_hints"]), len(tools.translate_violations(out["violations"])))

    def test_translate_violations_maps_known_rule(self):
        hints = tools.translate_violations(["[task-type] Node 'x' uses forbidden 'task'"])
        self.assertEqual(len(hints), 1)
        self.assertIn("'task' is forbidden", hints[0])
        self.assertTrue(hints[0].startswith("[task-type]"))

    def test_translate_violations_drops_ignorable_and_dedupes(self):
        hints = tools.translate_violations([
            "[no-bpmndi] compiler adds DI",       # ignorable → dropped
            "[label-required] missing name (A)",
            "[label-required] missing name (B)",  # duplicate rule → deduped
        ])
        self.assertEqual(len(hints), 1)
        self.assertTrue(hints[0].startswith("[label-required]"))

    def test_translate_problems_maps_and_labels_element(self):
        hints = tools.translate_problems([
            {"rule": "lane-orphan", "elementId": "Task_1", "message": "raw"},
            {"rule": "no-bpmndi", "message": "ignored"},
        ])
        self.assertEqual(len(hints), 1)
        self.assertIn("Element 'Task_1'", hints[0])
        self.assertIn("Add a 'lane' field", hints[0])


class TestProsAllyPreserve(FrappeTestCase):
    def test_preserve_returns_expected_shape(self):
        out = tools.preserve_properties("", "<new/>")
        self.assertEqual(set(out), {"merged_xml", "removed_elements"})
        # empty old xml → new xml passes through untouched, nothing removed
        self.assertEqual(out["merged_xml"], "<new/>")
        self.assertEqual(out["removed_elements"], [])


class TestProsAllyRegistry(FrappeTestCase):
    def test_registry_has_four_tools_with_valid_schemas(self):
        names = {t.name for t in tools.PROSALLY_TOOLS}
        self.assertEqual(
            names,
            {"get_diagram_facts", "compile_ir", "validate_bpmn", "preserve_properties"},
        )
        for spec in tools.PROSALLY_TOOLS:
            self.assertTrue(spec.description)
            self.assertIsInstance(spec.parameters, dict)
            self.assertIsInstance(spec.required, list)
            for req in spec.required:
                self.assertIn(req, spec.parameters)

    def test_toolspec_fn_returns_json_string(self):
        by_name = {t.name: t for t in tools.PROSALLY_TOOLS}
        # get_diagram_facts fn should JSON-encode the dict result
        raw = by_name["get_diagram_facts"].fn(xml='<bpmn:userTask id="T" name="A" />')
        self.assertIsInstance(raw, str)
        parsed = json.loads(raw)
        self.assertIn("element_ids", parsed)

    def test_validate_bpmn_tool_fn_roundtrips(self):
        by_name = {t.name: t for t in tools.PROSALLY_TOOLS}
        parsed = json.loads(by_name["validate_bpmn"].fn(xml="<nonsense/>"))
        self.assertFalse(parsed["valid"])
        self.assertIn("fix_hints", parsed)
