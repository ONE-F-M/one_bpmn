# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
The sample connector — the claim "a REST integration needs no Python", tested.

If this file ever needs a Python handler to pass, the claim has stopped being
true. That is really what it guards: not the weather, but the absence of code
behind it.

Network is not required. The one test that does call Open-Meteo skips itself
when the host is unreachable, so a CI box without egress stays green rather
than failing for the wrong reason.
"""

import json
import unittest
from types import SimpleNamespace

import frappe

from one_bpmn.one_bpmn.connectors.manifest import (
	field_specs,
	get_execution_spec,
	load_manifests,
)

CONNECTOR = "open_meteo"


def _reachable():
	"""Is the public API callable from here?"""
	import urllib.request

	try:
		urllib.request.urlopen(
			"https://api.open-meteo.com/v1/forecast?latitude=0&longitude=0&current=temperature_2m",
			timeout=8,
		)
		return True
	except Exception:
		return False


class TestItIsPureConfiguration(unittest.TestCase):
	"""The point of the sample."""

	def test_the_connector_has_no_python_anywhere(self):
		for op in next(m for m in load_manifests() if m["connectorId"] == CONNECTOR)["operations"]:
			spec = get_execution_spec(CONNECTOR, op["value"])
			with self.subTest(operation=op["value"]):
				self.assertEqual(spec.execution_type, "HTTP Request")
				self.assertFalse(spec.handler_path, "no operation may name a handler")

	def test_it_needs_no_credential(self):
		"""So it demonstrates on any site with nothing to set up first."""
		self.assertEqual(frappe.db.get_value("BPMN Connector", CONNECTOR, "auth_type"), "None")

	def test_it_appears_in_the_modeler(self):
		manifests = {m["connectorId"]: m for m in load_manifests()}
		self.assertIn(CONNECTOR, manifests)
		self.assertEqual(
			[o["value"] for o in manifests[CONNECTOR]["operations"]],
			["currentConditions", "dailyOutlook"],
		)

	def test_it_carries_an_icon_so_the_canvas_shows_it(self):
		manifest = next(m for m in load_manifests() if m["connectorId"] == CONNECTOR)
		icon = manifest.get("icon") or {}
		self.assertTrue(icon.get("path"))
		self.assertTrue(icon.get("color"))


class TestItRunsWithoutBeingConfigured(unittest.TestCase):
	"""Defaults matter for a demo: a sample that needs three inputs first is a
	poor one."""

	def test_location_defaults_to_kuwait_city(self):
		fields = field_specs(CONNECTOR, "currentConditions")
		self.assertEqual(fields["latitude"]["default"], "29.3759")
		self.assertEqual(fields["longitude"]["default"], "47.9774")
		self.assertEqual(fields["timezone"]["default"], "Asia/Kuwait")

	def test_the_days_field_offers_choices_rather_than_free_text(self):
		days = field_specs(CONNECTOR, "dailyOutlook")["days"]
		self.assertEqual(days["type"], "Dropdown")
		self.assertEqual([c["value"] for c in days["choices"]], ["1", "3", "7", "14"])


class TestTheResponseIsReducedToSomethingUsable(unittest.TestCase):
	"""A raw forecast is 40 keys deep; a workflow variable should be five."""

	def test_current_conditions_maps_to_flat_keys(self):
		mapping = json.loads(get_execution_spec(CONNECTOR, "currentConditions").response_map_json)
		self.assertEqual(
			sorted(mapping), ["humidity", "observedAt", "temperature", "unit", "windSpeed"]
		)
		self.assertEqual(mapping["temperature"], "current.temperature_2m")

	def test_todays_peak_is_lifted_out_of_the_list(self):
		"""So an exclusive gateway can branch on it without a Script Task —
		which is the whole argument for response mapping."""
		mapping = json.loads(get_execution_spec(CONNECTOR, "dailyOutlook").response_map_json)
		self.assertEqual(mapping["peakToday"], "daily.temperature_2m_max[0]")


class TestAgainstTheLiveApi(unittest.TestCase):
	"""One end-to-end call, through the real dispatcher."""

	@classmethod
	def setUpClass(cls):
		if not _reachable():
			raise unittest.SkipTest("api.open-meteo.com is not reachable from here")

	def _run(self, operation, params, result_var):
		from one_bpmn.one_bpmn.doctype.bpmn_process_instance.dispatchers import dispatch_connector

		task = SimpleNamespace(data={})
		dispatch_connector(
			SimpleNamespace(context_doctype=None, context_docname=None, name="T-1"),
			task,
			{
				"connectorId": CONNECTOR,
				"operation": operation,
				"resultVariable": result_var,
				"connectorParams": json.dumps(params),
				"failOnError": "1",
			},
			"t1",
		)
		return task.data[result_var]

	def test_current_conditions_returns_a_usable_reading(self):
		out = self._run(
			"currentConditions", {"latitude": "29.3759", "longitude": "47.9774"}, "weather"
		)
		self.assertIsInstance(out["temperature"], (int, float))
		self.assertEqual(out["unit"], "°C")
		self.assertTrue(out["observedAt"])

	def test_daily_outlook_returns_aligned_lists_and_a_scalar_peak(self):
		out = self._run(
			"dailyOutlook",
			{"latitude": "29.3759", "longitude": "47.9774", "days": "3"},
			"outlook",
		)
		self.assertEqual(len(out["dates"]), 3)
		self.assertEqual(len(out["maxTemps"]), 3)
		# The indexed key must equal the first element — that is the mapping
		# feature this operation exists to show.
		self.assertEqual(out["peakToday"], out["maxTemps"][0])
