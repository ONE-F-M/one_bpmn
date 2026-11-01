# Copyright (c) 2026, one-fm and contributors
# ProsAlly reads message and signal links across process maps: extractor, resolver and gaps.

from unittest.mock import patch

import frappe
from frappe.model.document import Document
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import process_digest, process_links

PREFIX = "zz_process_links_"
DOCTYPE = "BPMN Process Model"

XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
  <bpmn:signal id="sig" name="{signal}"/>
  <bpmn:message id="msg" name="{message}"/>
  <bpmn:process id="{process_id}" isExecutable="false">
    {body}
  </bpmn:process>
</bpmn:definitions>"""

CATCH_SIGNAL = (
	'<bpmn:intermediateCatchEvent id="c1" name="Wait"><bpmn:signalEventDefinition signalRef="sig"/>'
	"</bpmn:intermediateCatchEvent>"
)
THROW_SIGNAL = (
	'<bpmn:intermediateThrowEvent id="t1" name="Send"><bpmn:signalEventDefinition signalRef="sig"/>'
	"</bpmn:intermediateThrowEvent>"
)
CATCH_MESSAGE = (
	'<bpmn:intermediateCatchEvent id="c2" name="Wait msg"><bpmn:messageEventDefinition messageRef="msg"/>'
	"</bpmn:intermediateCatchEvent>"
)
THROW_MESSAGE = (
	'<bpmn:intermediateThrowEvent id="t2" name="Send msg"><bpmn:messageEventDefinition messageRef="msg"/>'
	"</bpmn:intermediateThrowEvent>"
)


def _xml(slug: str, body: str = "", signal: str = "unused signal", message: str = "unused message") -> str:
	return XML.format(process_id=f"{PREFIX}{slug}", body=body, signal=signal, message=message)


def _model(slug: str, body: str = "", **names) -> str:
	return (
		frappe.get_doc(
			{
				"doctype": DOCTYPE,
				"title": f"{PREFIX}{slug}",
				"process_id": f"{PREFIX}{slug}",
				"is_active": 1,
				"bpmn_xml": _xml(slug, body, **names),
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _kinds(model: str) -> list[str]:
	return [gap["kind"] for gap in process_links.get_process_links(model)["gaps"]]


class TestProcessLinks(FrappeTestCase):
	def test_extract_reads_events_tasks_calls_and_multi_instance(self):
		body = (
			CATCH_SIGNAL
			+ THROW_MESSAGE
			+ '<bpmn:receiveTask id="r1" name="Receive" messageRef="msg"/>'
			+ '<bpmn:callActivity id="ca1" name="Run child" calledElement="child_pid">'
			+ "<bpmn:multiInstanceLoopCharacteristics/></bpmn:callActivity>"
		)
		links = process_links.extract_links(_xml("extract", body, signal="Extract signal", message="Extract message"))

		self.assertEqual(
			[(c["kind"], c["name"], c["step"]) for c in links["catches"]],
			[("signal", "Extract signal", "intermediateCatchEvent"), ("message", "Extract message", "receiveTask")],
		)
		self.assertEqual([(t["kind"], t["name"]) for t in links["throws"]], [("message", "Extract message")])
		self.assertEqual(links["calls"][0]["called"], "child_pid")
		self.assertTrue(links["calls"][0]["multi_instance"])
		self.assertFalse(links["catches"][0]["multi_instance"])

	def test_catch_inside_multi_instance_scope_is_flagged(self):
		body = (
			'<bpmn:subProcess id="sp1"><bpmn:multiInstanceLoopCharacteristics/>' + CATCH_SIGNAL + "</bpmn:subProcess>"
		)
		links = process_links.extract_links(_xml("mi", body, signal="MI signal"))
		self.assertTrue(links["catches"][0]["multi_instance"])

	def test_unreadable_diagram_has_no_links(self):
		self.assertEqual(process_links.extract_links("<not xml"), {"catches": [], "throws": [], "calls": []})

	def test_signal_caught_only_in_another_map_is_a_gap(self):
		catcher = _model("sig_catcher", CATCH_SIGNAL, signal="Other map signal")
		thrower = _model("sig_thrower", THROW_SIGNAL, signal="Other map signal")

		gaps = process_links.get_process_links(catcher)["gaps"]

		self.assertEqual([gap["kind"] for gap in gaps], ["signal_other_process"])
		self.assertEqual(gaps[0]["element"], "c1")
		self.assertIn(thrower, gaps[0]["message"])

	def test_signal_thrown_and_caught_in_one_map_is_not_a_gap(self):
		self.assertEqual(_kinds(_model("sig_same", CATCH_SIGNAL + THROW_SIGNAL, signal="Same map signal")), [])

	def test_catch_without_throw_is_reported(self):
		self.assertEqual(_kinds(_model("lonely_catch", CATCH_SIGNAL, signal="Lonely catch signal")), ["no_throw"])

	def test_throw_without_catch_is_reported(self):
		self.assertEqual(_kinds(_model("lonely_throw", THROW_MESSAGE, message="Lonely throw message")), ["no_catch"])

	def test_message_thrown_in_another_map_is_not_a_gap(self):
		catcher = _model("msg_catcher", CATCH_MESSAGE, message="Cross map message")
		_model("msg_thrower", THROW_MESSAGE, message="Cross map message")
		self.assertEqual(_kinds(catcher), [])

	def test_names_differing_only_in_case_are_reported_as_a_mismatch(self):
		catcher = _model("near_catcher", CATCH_SIGNAL, signal="Near miss approved")
		_model("near_thrower", THROW_SIGNAL, signal="near MISS approved")

		gaps = process_links.get_process_links(catcher)["gaps"]

		self.assertEqual([gap["kind"] for gap in gaps], ["name_mismatch"])
		self.assertIn("near MISS approved", gaps[0]["message"])

	def test_call_to_a_missing_process_is_reported(self):
		body = '<bpmn:callActivity id="ca1" name="Run child" calledElement="zz_process_links_no_such_process"/>'
		self.assertEqual(_kinds(_model("call_missing", body)), ["call_target_missing"])

	def test_called_map_is_related_and_not_a_gap(self):
		child = _model("call_child", THROW_MESSAGE, message="Child message")
		body = f'<bpmn:callActivity id="ca1" name="Run child" calledElement="{PREFIX}call_child"/>'
		parent = _model("call_parent", body)

		result = process_links.get_process_links(parent)

		self.assertEqual(result["gaps"], [])
		self.assertEqual(result["related"], [{"process_model": child, "reason": "called by Run child"}])

	def test_called_map_the_user_cannot_read_is_reported_not_shown(self):
		_model("hidden_child", THROW_MESSAGE, message="Hidden message")
		body = f'<bpmn:callActivity id="ca1" name="Run child" calledElement="{PREFIX}hidden_child"/>'
		parent = _model("hidden_parent", body)

		with patch.object(process_links.frappe, "has_permission", return_value=False):
			result = process_links.get_process_links(parent)

		self.assertEqual([gap["kind"] for gap in result["gaps"]], ["call_target_not_visible"])
		self.assertEqual(result["related"], [])

	def test_related_maps_come_from_the_permission_aware_list(self):
		catcher = _model("list_catcher", CATCH_SIGNAL, signal="Listed signal")
		_model("list_thrower", THROW_SIGNAL, signal="Listed signal")

		with patch.object(process_links.frappe, "get_list", return_value=[]):
			result = process_links.get_process_links(catcher)

		self.assertEqual(result["related"], [])
		self.assertEqual([gap["kind"] for gap in result["gaps"]], ["no_throw"])

	def test_reading_related_maps_changes_nothing(self):
		catcher = _model("ro_catcher", CATCH_SIGNAL, signal="Read only signal")
		thrower = _model("ro_thrower", THROW_SIGNAL, signal="Read only signal")
		before = frappe.db.get_value(DOCTYPE, thrower, ["modified", "bpmn_xml"])

		process_links.get_process_links(catcher)
		process_links.find_related_processes(catcher)

		self.assertEqual(frappe.db.get_value(DOCTYPE, thrower, ["modified", "bpmn_xml"]), before)

	def test_related_maps_are_capped_and_flagged(self):
		catcher = _model("cap_catcher", CATCH_SIGNAL, signal="Capped signal")
		for index in range(3):
			_model(f"cap_thrower_{index}", THROW_SIGNAL, signal="Capped signal")

		with patch.object(process_links, "MAX_RELATED_MODELS", 2):
			result = process_links.get_process_links(catcher)

		self.assertEqual(len(result["related"]), 2)
		self.assertTrue(result["truncated"])

	def test_find_related_lists_title_and_reason(self):
		catcher = _model("find_catcher", CATCH_SIGNAL, signal="Findable signal")
		thrower = _model("find_thrower", THROW_SIGNAL, signal="Findable signal")

		result = process_links.find_related_processes(catcher)

		self.assertEqual(
			result["results"],
			[{"process_model": thrower, "title": f"{PREFIX}find_thrower", "reason": "uses 'Findable signal'"}],
		)

	def test_unknown_model_is_an_error(self):
		self.assertIn("error", process_links.get_process_links(f"{PREFIX}missing"))
		self.assertIn("error", process_links.find_related_processes(f"{PREFIX}missing"))

	def test_both_tools_require_read_permission(self):
		name = _model("secret", CATCH_SIGNAL, signal="Secret signal")
		with patch.object(Document, "check_permission", side_effect=frappe.PermissionError):
			with self.assertRaises(frappe.PermissionError):
				process_links.get_process_links(name)
			with self.assertRaises(frappe.PermissionError):
				process_links.find_related_processes(name)

	def test_links_are_cached_until_the_map_changes(self):
		name = _model("cache", CATCH_SIGNAL, signal="Cache signal")

		with patch.object(process_links, "extract_links", wraps=process_links.extract_links) as extract:
			process_links.links_of(name)
			process_links.links_of(name)
		self.assertEqual(extract.call_count, 1)

		frappe.db.set_value(DOCTYPE, name, "bpmn_xml", _xml("cache", THROW_SIGNAL, signal="Cache signal"))
		self.assertEqual(len(process_links.links_of(name)["throws"]), 1)

	def test_digest_shows_event_kind_and_name(self):
		name = _model("digest", CATCH_SIGNAL + THROW_MESSAGE, signal="Digest signal", message="Digest message")
		digest = process_digest.get_process_model_digest(name)["digest"]
		self.assertIn("- intermediateCatchEvent: Wait [signal: Digest signal]", digest)
		self.assertIn("- intermediateThrowEvent: Send msg [message: Digest message]", digest)
