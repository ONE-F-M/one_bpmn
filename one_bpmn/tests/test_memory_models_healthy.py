# Copyright (c) 2026, one-fm and contributors
"""The patch that moves memory distillation and reconciliation onto a Healthy AI Model."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.memory.model_resolution import resolve_memory_model
from one_bpmn.one_bpmn.patches.v1_0 import memory_models_use_healthy_records as P

PREFIX = "ZZ Memory Models"
DEAD = f"{PREFIX} dead"
OTHER_DEAD = f"{PREFIX} other-dead"
SHARED = f"{PREFIX} shared - claude-haiku-5-5"
KEEP = f"{PREFIX} keep - claude-sonnet-5-5"
AGENT = f"{PREFIX} Agent"
AGENT_ID = frappe.scrub(AGENT)
DISTILL_DEFAULT = "default_memory_distill_model"
RECONCILE_DEFAULT = "default_memory_reconcile_model"


class TestMemoryModelsHealthy(FrappeTestCase):
	def setUp(self):
		self.cleanup()
		self.provider = frappe.db.get_value("AI Provider", {}, "name")
		self.make_model(DEAD, "claude-haiku-4-5", "Unhealthy")
		self.make_model(OTHER_DEAD, "claude-sonnet-4-5", "Unhealthy")
		self.make_model(SHARED, "claude-haiku-5-5", "Healthy")
		self.make_model(KEEP, "claude-sonnet-5-5", "Healthy")
		self.agent = self.make_agent(AGENT, SHARED)
		self.shared_patch = patch.object(P, "SHARED_MODEL", SHARED)
		self.shared_patch.start()

	def tearDown(self):
		self.shared_patch.stop()
		self.cleanup()

	def cleanup(self):
		frappe.db.delete("AI Agent Configuration", {"agent_name": ("like", f"{PREFIX}%")})
		frappe.db.delete("AI Model", {"model_name": ("like", f"{PREFIX}%")})

	def make_model(self, name, api_name, status):
		frappe.get_doc(
			{
				"doctype": "AI Model",
				"model_name": name,
				"provider": self.provider,
				"model_api_name": api_name,
				"enable_model": 0,
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("AI Model", name, {"enable_model": 1, "health_status": status})

	def make_agent(self, name, model, **extra):
		return frappe.get_doc(
			{
				"doctype": "AI Agent Configuration",
				"agent_name": name,
				"agent_id": frappe.scrub(name),
				"agent_type": "Background",
				"agent_framework": "Direct API",
				"enabled": 1,
				"ai_model": model,
				**extra,
			}
		).insert(ignore_permissions=True)

	def value(self, field):
		return frappe.db.get_value("AI Agent Configuration", AGENT, field)

	def set_defaults(self, value):
		for field in (DISTILL_DEFAULT, RECONCILE_DEFAULT):
			frappe.db.set_single_value("Processa Settings", field, value)

	def test_dead_defaults_move_to_the_healthy_model(self):
		self.set_defaults(DEAD)
		P.repoint_defaults()
		for field in (DISTILL_DEFAULT, RECONCILE_DEFAULT):
			self.assertEqual(frappe.db.get_single_value("Processa Settings", field), SHARED)

	def test_healthy_default_is_left_alone(self):
		self.set_defaults(KEEP)
		P.repoint_defaults()
		self.assertEqual(frappe.db.get_single_value("Processa Settings", DISTILL_DEFAULT), KEEP)

	def test_dead_overrides_are_blanked_and_healthy_ones_kept(self):
		frappe.db.set_value(
			"AI Agent Configuration",
			AGENT,
			{"memory_distill_model": DEAD, "memory_reconcile_model": KEEP},
		)
		P.blank_dead_overrides()
		self.assertFalse(self.value("memory_distill_model"))
		self.assertEqual(self.value("memory_reconcile_model"), KEEP)

	def test_disabled_agent_overrides_are_blanked_too(self):
		frappe.db.set_value(
			"AI Agent Configuration", AGENT, {"enabled": 0, "memory_distill_model": DEAD}
		)
		P.blank_dead_overrides()
		self.assertFalse(self.value("memory_distill_model"))

	def test_every_memory_model_resolves_to_a_healthy_record(self):
		self.set_defaults(DEAD)
		frappe.db.set_value(
			"AI Agent Configuration",
			AGENT,
			{"memory_distill_model": OTHER_DEAD, "memory_reconcile_model": ""},
		)
		P.repoint_defaults()
		P.blank_dead_overrides()
		for own, setting in (
			(self.value("memory_distill_model"), DISTILL_DEFAULT),
			(self.value("memory_reconcile_model"), RECONCILE_DEFAULT),
		):
			resolved = resolve_memory_model(own, setting, None)
			self.assertTrue(P.is_healthy(resolved), resolved)

	def test_unscoped_memory_stops_the_patch(self):
		cases = (
			("ENTITY_AGENTS", "memory_scope", "Agent"),
			("PERSONAL_AGENTS", "memory_scope", "Agent"),
			("NO_MEMORY_AGENTS", "long_term_memory", "Enabled"),
		)
		for constant, field, bad in cases:
			with self.subTest(constant), patch.multiple(
				P, ENTITY_AGENTS=(), PERSONAL_AGENTS=(), NO_MEMORY_AGENTS=(), SCRIPT_MARKERS={}
			), patch.object(P, constant, (AGENT_ID,)):
				frappe.db.set_value("AI Agent Configuration", AGENT, field, bad)
				with self.assertRaises(frappe.ValidationError):
					P.check_memory_is_scoped()

	def test_scoped_memory_passes(self):
		frappe.db.set_value("AI Agent Configuration", AGENT, "memory_scope", "Entity")
		with patch.multiple(
			P, ENTITY_AGENTS=(AGENT_ID,), PERSONAL_AGENTS=(), NO_MEMORY_AGENTS=(), SCRIPT_MARKERS={}
		):
			P.check_memory_is_scoped()

	def test_script_without_its_marker_stops_the_patch(self):
		with patch.multiple(
			P, ENTITY_AGENTS=(), PERSONAL_AGENTS=(), NO_MEMORY_AGENTS=(), SCRIPT_MARKERS={"Some Script": "marker"}
		), patch.object(P.frappe.db, "get_value", return_value="code without it"):
			with self.assertRaises(frappe.ValidationError):
				P.check_memory_is_scoped()

	def test_unhealthy_target_stops_the_patch_before_any_change(self):
		frappe.db.set_value("AI Model", SHARED, "health_status", "Unhealthy")
		self.set_defaults(DEAD)
		with patch.object(P, "check_memory_is_scoped"):
			with self.assertRaises(frappe.ValidationError):
				P.execute()
		self.assertEqual(frappe.db.get_single_value("Processa Settings", DISTILL_DEFAULT), DEAD)

	def test_lumina_style_agent_stops_writing(self):
		with patch.object(P, "UNSCOPED_AGENT", AGENT):
			P.stop_unscoped_writes()
		self.assertEqual(self.value("memory_write_mode"), "off")

	def test_execute_runs_every_step_and_a_second_run_changes_nothing(self):
		self.set_defaults(DEAD)
		frappe.db.set_value("AI Agent Configuration", AGENT, "memory_distill_model", DEAD)
		with patch.object(P, "check_memory_is_scoped"), patch.object(
			P, "disable_unused_dead_models"
		) as disable:
			P.execute()
			modified = self.value("modified")
			P.execute()
		self.assertEqual(disable.call_count, 2)
		self.assertEqual(frappe.db.get_single_value("Processa Settings", RECONCILE_DEFAULT), SHARED)
		self.assertFalse(self.value("memory_distill_model"))
		self.assertEqual(self.value("modified"), modified)
