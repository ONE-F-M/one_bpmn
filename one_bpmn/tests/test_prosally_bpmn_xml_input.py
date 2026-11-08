# Copyright (c) 2026, one-fm and contributors
# WI-004172: ProsAlly parses BPMN 2.0 XML pasted into the chat instead of asking for a step list.
#
# Everything here runs against mocks - no live LLM is called.

from __future__ import annotations

from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import bpmn_xml_input as bx

NS = (
	'xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
	'xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" '
	'xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" '
	'xmlns:di="http://www.omg.org/spec/DD/20100524/DI"'
)

PROCESS = """
  <bpmn:signal id="Signal_1" name="Go"/>
  <bpmn:process id="Process_1" isExecutable="true">
    <bpmn:startEvent id="Start_1" name="Start"/>
    <bpmn:userTask id="Task_1" name="Review request"/>
    <bpmn:exclusiveGateway id="Gw_1" name="Approved?"/>
    <bpmn:userTask id="Task_2" name="Notify"/>
    <bpmn:intermediateCatchEvent id="Catch_1" name="Wait for go">
      <bpmn:signalEventDefinition signalRef="Signal_1"/>
    </bpmn:intermediateCatchEvent>
    <bpmn:endEvent id="End_1" name="Done"/>
    <bpmn:sequenceFlow id="F1" sourceRef="Start_1" targetRef="Task_1"/>
    <bpmn:sequenceFlow id="F2" sourceRef="Task_1" targetRef="Gw_1"/>
    <bpmn:sequenceFlow id="F3" name="yes" sourceRef="Gw_1" targetRef="Task_2"/>
    <bpmn:sequenceFlow id="F4" name="no" sourceRef="Gw_1" targetRef="End_1"/>
    <bpmn:sequenceFlow id="F5" sourceRef="Task_2" targetRef="Catch_1"/>
    <bpmn:sequenceFlow id="F6" sourceRef="Catch_1" targetRef="End_1"/>
  </bpmn:process>
"""
SHAPE = (
	'<bpmndi:BPMNShape id="S{n}" bpmnElement="Task_1">'
	'<dc:Bounds x="1" y="2" width="3" height="4"/></bpmndi:BPMNShape>'
)


def _document(body: str = PROCESS, shapes: int = 2) -> str:
	diagram = (
		'<bpmndi:BPMNDiagram id="D1"><bpmndi:BPMNPlane id="P1" bpmnElement="Process_1">'
		+ "".join(SHAPE.format(n=n) for n in range(shapes))
		+ "</bpmndi:BPMNPlane></bpmndi:BPMNDiagram>"
	)
	return f'<?xml version="1.0" encoding="UTF-8"?>\n<bpmn:definitions {NS} id="Defs_1">{body}{diagram}</bpmn:definitions>'


# A user task opened and never closed: the parser stops at </bpmn:process> on line 5.
MALFORMED = (
	'<?xml version="1.0"?>\n'
	'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">\n'
	'  <bpmn:process id="P1">\n'
	'    <bpmn:userTask id="T1" name="x">\n'
	"  </bpmn:process>\n"
	"</bpmn:definitions>"
)

BROKEN_STRUCTURE = """
  <bpmn:process id="P1">
    <bpmn:startEvent id="Start_1"/>
    <bpmn:exclusiveGateway id="Gw_1"/>
    <bpmn:intermediateCatchEvent id="Catch_1" name="Wait"/>
    <bpmn:userTask id="Task_1" name="Do it"/>
    <bpmn:endEvent id="End_1"/>
    <bpmn:sequenceFlow id="F1" sourceRef="Start_1" targetRef="Gw_1"/>
    <bpmn:sequenceFlow id="F2" sourceRef="Gw_1" targetRef="Catch_1"/>
    <bpmn:sequenceFlow id="F3" sourceRef="Gw_1" targetRef="Task_1"/>
    <bpmn:sequenceFlow id="F4" sourceRef="Catch_1" targetRef="End_9"/>
  </bpmn:process>
"""


def _issues_for(analysis: dict, element_id: str) -> list[str]:
	return [i["message"] + " | " + i["suggestion"] for i in analysis["issues"] if i["element_id"] == element_id]


class TestDetection(FrappeTestCase):
	"""AC1: the message is recognised as BPMN XML, not conversational text."""

	def test_full_document_is_detected(self):
		self.assertTrue(bx.is_bpmn_xml(_document()))

	def test_fragment_and_escaped_text_are_detected(self):
		self.assertTrue(bx.is_bpmn_xml('<bpmn:startEvent id="S"/><bpmn:endEvent id="E"/>'))
		self.assertTrue(bx.is_bpmn_xml("&lt;bpmn:startEvent id=&quot;S&quot;/&gt;&lt;bpmn:endEvent id=&quot;E&quot;/&gt;"))

	def test_prose_is_not_detected(self):
		self.assertFalse(bx.is_bpmn_xml("Please draw an approval process: 1. submit 2. review 3. approve"))
		self.assertFalse(bx.is_bpmn_xml("what does a <task> mean in BPMN?"))
		self.assertFalse(bx.is_bpmn_xml(""))

	def test_fenced_xml_is_extracted_with_the_surrounding_text(self):
		xml, before, after = bx.extract_xml("Please review this:\n```xml\n" + _document() + "\n```\nThanks")
		self.assertTrue(xml.startswith("<?xml"))
		self.assertIn("Please review", before)
		self.assertIn("Thanks", after)
		self.assertNotIn("```", xml)


class TestStructuralParsing(FrappeTestCase):
	"""AC1: tasks, sequence flows, catch/throw events and gateways are read directly."""

	def test_valid_document_is_parsed_without_findings(self):
		analysis = bx.analyze_bpmn_xml(_document())
		self.assertTrue(analysis["ok"])
		self.assertFalse(analysis["partial"])
		self.assertEqual(
			analysis["counts"],
			{
				"startEvent": 1,
				"userTask": 2,
				"exclusiveGateway": 1,
				"intermediateCatchEvent": 1,
				"endEvent": 1,
				"sequenceFlow": 6,
			},
		)
		self.assertEqual([i for i in analysis["issues"] if i["severity"] != "info"], [])
		gateway = next(n for n in analysis["nodes"] if n["id"] == "Gw_1")
		self.assertEqual((gateway["in"], gateway["out"]), (["F2"], ["F3", "F4"]))

	def test_partial_fragment_without_namespaces_is_parsed(self):
		fragment = (
			'<bpmn:startEvent id="S"/><bpmn:userTask id="T" name="A"/>'
			'<bpmn:sequenceFlow id="F" sourceRef="S" targetRef="T"/>'
		)
		analysis = bx.analyze_bpmn_xml(fragment)
		self.assertTrue(analysis["ok"])
		self.assertTrue(analysis["partial"])
		self.assertEqual(analysis["counts"]["sequenceFlow"], 1)
		# An excerpt's loose ends are warnings, not errors.
		self.assertEqual([i for i in analysis["issues"] if i["severity"] == "error"], [])

	def test_layout_is_counted_but_never_listed(self):
		analysis = bx.analyze_bpmn_xml(_document(shapes=3))
		self.assertGreater(analysis["layout_elements"], 0)
		block = bx.build_analysis_block(analysis)
		self.assertIn("Diagram layout (bpmndi)", block)
		self.assertNotIn("BPMNShape", block)
		self.assertIn("bpmn:intermediateCatchEvent Catch_1", block)

	def test_prepare_turn_is_none_for_ordinary_text(self):
		self.assertIsNone(bx.prepare_turn("add an approval step after review"))


class TestActionableFindings(FrappeTestCase):
	"""AC2: findings name the element id, tag and sequence flow, and say how to fix them."""

	def setUp(self):
		self.analysis = bx.analyze_bpmn_xml(_document(BROKEN_STRUCTURE))

	def test_unknown_flow_target_names_the_flow_and_the_closest_id(self):
		found = _issues_for(self.analysis, "F4")
		self.assertTrue(any("targetRef='End_9'" in text and "End_1" in text for text in found), found)

	def test_catch_event_without_definition_is_reported_by_id(self):
		found = _issues_for(self.analysis, "Catch_1")
		self.assertTrue(any("no event definition" in text and "signalEventDefinition" in text for text in found), found)

	def test_catch_event_after_exclusive_gateway_suggests_event_based_gateway(self):
		found = _issues_for(self.analysis, "Catch_1")
		self.assertTrue(any("Gw_1" in text and "F2" in text and "eventBasedGateway" in text for text in found), found)

	def test_gateway_branches_without_condition_name_each_flow(self):
		found = " ".join(_issues_for(self.analysis, "Gw_1"))
		self.assertIn("F2", found)
		self.assertIn("F3", found)
		self.assertIn("conditionExpression", found)

	def test_dead_end_and_unreachable_elements_are_reported(self):
		self.assertTrue(any("dead end" in t for t in _issues_for(self.analysis, "Task_1")))
		self.assertTrue(any("no incoming" in t for t in _issues_for(self.analysis, "End_1")))
		self.assertTrue(all(i["tag"].startswith("bpmn:") for i in self.analysis["issues"] if i["element_id"]))

	def test_findings_reach_the_model_block_errors_first(self):
		block = bx.build_analysis_block(self.analysis)
		self.assertIn("[ERROR] bpmn:sequenceFlow id=F4", block)
		self.assertLess(block.index("[ERROR]"), block.index("Flow elements"))

	def test_duplicate_ids_and_missing_ids_are_reported(self):
		body = (
			'<bpmn:process id="P1"><bpmn:startEvent id="A"/><bpmn:userTask id="A" name="x"/>'
			'<bpmn:userTask name="no id"/><bpmn:endEvent id="E"/></bpmn:process>'
		)
		analysis = bx.analyze_bpmn_xml(_document(body))
		messages = [i["message"] for i in analysis["issues"]]
		self.assertTrue(any("id 'A' is already used" in m for m in messages), messages)
		self.assertTrue(any("has no id attribute" in m for m in messages), messages)

	def test_unresolved_signal_reference_is_reported(self):
		body = (
			'<bpmn:process id="P1"><bpmn:startEvent id="S"/>'
			'<bpmn:intermediateCatchEvent id="C" name="w"><bpmn:signalEventDefinition signalRef="Nope"/>'
			'</bpmn:intermediateCatchEvent><bpmn:endEvent id="E"/>'
			'<bpmn:sequenceFlow id="F1" sourceRef="S" targetRef="C"/>'
			'<bpmn:sequenceFlow id="F2" sourceRef="C" targetRef="E"/></bpmn:process>'
		)
		analysis = bx.analyze_bpmn_xml(_document(body))
		self.assertTrue(any("signalRef='Nope'" in t for t in _issues_for(analysis, "C")))


class TestMalformedXml(FrappeTestCase):
	"""AC3: a parse failure is reported with its line and tag, not turned into a request for a list."""

	def test_error_carries_line_column_and_tag(self):
		analysis = bx.analyze_bpmn_xml(MALFORMED)
		self.assertFalse(analysis["ok"])
		error = analysis["error"]
		self.assertEqual(error["line"], 5)
		self.assertEqual(error["tag"], "bpmn:process")
		self.assertIn("mismatched tag", error["message"])
		self.assertIn("</bpmn:process>", error["source_line"])

	def test_error_text_names_the_location(self):
		text = bx.format_parse_error(bx.analyze_bpmn_xml(MALFORMED)["error"])
		self.assertIn("line 5", text)
		self.assertIn("<bpmn:process>", text)

	def test_unbound_prefix_gets_a_namespace_hint(self):
		analysis = bx.analyze_bpmn_xml('<bpmn:process id="P"><bpmn:task id="T"></bpmn:process>')
		self.assertFalse(analysis["ok"])
		self.assertIn("xmlns:bpmn", analysis["error"]["message"])

	def test_entity_declarations_are_refused(self):
		analysis = bx.analyze_bpmn_xml('<?xml version="1.0"?>\n<!DOCTYPE x [<!ENTITY a "b">]>\n<bpmn:definitions/>')
		self.assertFalse(analysis["ok"])
		self.assertEqual(analysis["error"]["line"], 2)

	def test_block_for_the_model_forbids_a_text_list_fallback(self):
		block = bx.prepare_turn("Here is my model\n" + MALFORMED)["block"]
		self.assertIn("PARSE FAILURE", block)
		self.assertIn("line 5", block)
		self.assertIn("Do NOT fall back to asking for a plain-text list", block)


class TestLargePaste(FrappeTestCase):
	"""Notes (b) and (c): large pastes keep the semantic model and drop layout."""

	def test_small_paste_is_left_as_typed(self):
		self.assertIsNone(bx.prepare_turn(_document())["message_override"])

	def test_large_layout_section_is_cut_from_the_message(self):
		message = "Please review:\n" + _document(shapes=400)
		self.assertGreater(len(message), bx.MAX_RAW_XML_CHARS)
		turn = bx.prepare_turn(message)
		override = turn["message_override"]
		self.assertIsNotNone(override)
		self.assertNotIn("BPMNShape", override)
		self.assertIn("Please review:", override)
		self.assertIn("Catch_1", override)
		self.assertLessEqual(len(override), bx.MAX_RAW_XML_CHARS + 500)
		self.assertTrue(turn["analysis"]["ok"])

	def test_huge_semantic_model_is_summarised_and_capped(self):
		tasks = "".join(f'<bpmn:userTask id="T{n}" name="Step {n}"/>' for n in range(700))
		turn = bx.prepare_turn(_document(f'<bpmn:process id="P1">{tasks}</bpmn:process>'))
		self.assertLessEqual(len(turn["block"]), bx.MAX_ANALYSIS_CHARS)
		self.assertIn("summarised in the parsed analysis", turn["message_override"])
		self.assertNotIn("<bpmn:userTask", turn["message_override"])

	def test_huge_malformed_paste_keeps_the_lines_around_the_failure(self):
		tasks = "\n".join(f'<bpmn:userTask id="T{n}" name="Step {n}"/>' for n in range(700))
		xml = f'<bpmn:definitions {NS}>\n<bpmn:process id="P1">\n{tasks}\n</bpmn:definitions>'
		turn = bx.prepare_turn(xml)
		self.assertFalse(turn["analysis"]["ok"])
		self.assertIn("parse failure", turn["message_override"])
		self.assertLess(len(turn["message_override"]), bx.MAX_RAW_XML_CHARS)


class TestProsAllyWiring(FrappeTestCase):
	"""The chat turn context and the AG-UI stream hand pasted XML to the parser."""

	def test_context_for_a_valid_paste_carries_analysis_and_rules(self):
		from one_bpmn.api import server_script_api

		out = server_script_api.build_prosally_turn_context({"_turn_message": _document(BROKEN_STRUCTURE)})
		text = out["dialog_context"]
		self.assertIn("PASTED BPMN XML ANALYSIS", text)
		self.assertIn("BPMN XML INPUT RULES", text)
		self.assertIn("never ask the user to re-type the steps as a plain list", text)
		self.assertIn("PROSALLY REPLY CONTRACT", text)
		self.assertNotIn("_turn_message", out)
		self.assertNotIn("_message_override", out)

	def test_context_for_a_malformed_paste_reports_the_failure(self):
		from one_bpmn.api import server_script_api

		text = server_script_api.build_prosally_turn_context({"_turn_message": MALFORMED})["dialog_context"]
		self.assertIn("PARSE FAILURE", text)
		self.assertIn("line 5", text)

	def test_context_for_ordinary_text_is_unchanged(self):
		from one_bpmn.api import server_script_api

		out = server_script_api.build_prosally_turn_context({"_turn_message": "add a review step"})
		self.assertNotIn("PASTED BPMN XML", out["dialog_context"])
		self.assertNotIn("BPMN XML INPUT RULES", out["dialog_context"])
		self.assertIn("PROSALLY REPLY CONTRACT", out["dialog_context"])

	def test_context_for_a_large_paste_asks_for_a_shorter_message(self):
		from one_bpmn.api import server_script_api

		out = server_script_api.build_prosally_turn_context({"_turn_message": _document(shapes=400)})
		self.assertNotIn("BPMNShape", out["_message_override"])

	def test_stream_sends_the_agent_the_shortened_message_and_clean_context(self):
		from one_bpmn.agents import agui_stream
		from one_bpmn.api import server_script_api  # registers the ProsAlly context builder  # noqa: F401

		message = "add a step\n" + _document(shapes=400)
		with patch(
			"one_bpmn.api.agent_invocation.invoke_agent",
			return_value={"response": "ok", "conversation": "CONV-1"},
		) as invoke:
			list(agui_stream.agent_event_stream("prosally_agent", message, "CONV-1", {"process_name": "P"}))
		sent_message = invoke.call_args.args[1]
		sent_context = invoke.call_args.kwargs["context"]
		self.assertNotIn("BPMNShape", sent_message)
		self.assertIn("Catch_1", sent_message)
		self.assertIn("PASTED BPMN XML ANALYSIS", sent_context["dialog_context"])
		self.assertEqual(sent_context["process_name"], "P")
		self.assertNotIn("_turn_message", sent_context)
		self.assertNotIn("_message_override", sent_context)

	def test_stream_answers_malformed_xml_with_the_parse_failure_and_no_model_turn(self):
		from one_bpmn.agents import agui_stream
		from one_bpmn.api import server_script_api  # noqa: F401

		with (
			patch("one_bpmn.api.agent_invocation.invoke_agent") as invoke,
			patch("one_bpmn.utils.chat_persistence.save_user_message"),
			patch("one_bpmn.utils.chat_persistence.save_bot_message") as save_bot,
		):
			chunks = "".join(agui_stream.agent_event_stream("prosally_agent", MALFORMED, "CONV-1", {}))
		invoke.assert_not_called()
		self.assertIn("could not be parsed", save_bot.call_args.args[1])
		self.assertIn("could not be parsed", chunks)
		self.assertIn("line 5", chunks)
		self.assertIn("RUN_FINISHED", chunks)

	def test_review_paste_is_answered_directly_with_findings_by_element_id(self):
		reply = bx.prepare_turn("check this xml\n" + _document(BROKEN_STRUCTURE))["direct_reply"]
		self.assertIn("End_9", reply)
		self.assertIn("F4", reply)
		self.assertIn("Catch_1", reply)
		self.assertIn("bpmn:eventBasedGateway", reply)

	def test_paste_with_a_change_request_goes_to_the_model(self):
		for text in ("add a review step after Task_1", "please fix this and update the diagram"):
			self.assertIsNone(bx.prepare_turn(text + "\n" + _document(BROKEN_STRUCTURE))["direct_reply"])

	def test_clean_xml_only_paste_gets_a_summary_reply(self):
		reply = bx.prepare_turn(_document())["direct_reply"]
		self.assertIn("no problems found", reply.lower())

	def test_stream_answers_a_review_paste_without_the_agent_and_saves_the_turn(self):
		from one_bpmn.agents import agui_stream
		from one_bpmn.api import server_script_api  # noqa: F401

		message = "review this\n" + _document(BROKEN_STRUCTURE)
		with (
			patch("one_bpmn.api.agent_invocation.invoke_agent") as invoke,
			patch("one_bpmn.utils.chat_persistence.save_user_message") as save_user,
			patch("one_bpmn.utils.chat_persistence.save_bot_message") as save_bot,
		):
			chunks = "".join(agui_stream.agent_event_stream("prosally_agent", message, "CONV-1", {}))
		invoke.assert_not_called()
		save_user.assert_called_once_with("CONV-1", message)
		self.assertIn("End_9", save_bot.call_args.args[1])
		self.assertIn("End_9", chunks)

	def test_stream_leaves_ordinary_messages_and_other_agents_alone(self):
		from one_bpmn.agents import agui_stream
		from one_bpmn.api import server_script_api  # noqa: F401

		with patch(
			"one_bpmn.api.agent_invocation.invoke_agent",
			return_value={"response": "ok", "conversation": "CONV-1"},
		) as invoke:
			list(agui_stream.agent_event_stream("prosally_agent", "add a review step", "CONV-1", {}))
		self.assertEqual(invoke.call_args.args[1], "add a review step")
		self.assertNotIn("_turn_message", invoke.call_args.kwargs["context"])
