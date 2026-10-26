# Copyright (c) 2026, one-fm and contributors
"""An agent whose AI Model is absent must not be told the model is disabled.

``frappe.db.get_value`` answers None for a record that does not exist and for
one that exists with the switch off, so a single check reported both as
"The linked AI Model is disabled." On a fresh site the catalogue seeds every
model disabled and carries no API keys, so this is the first message anyone
setting an agent up sees — and it sent them looking for a switch to flip on a
record their site did not have.

The config is stubbed rather than inserted: saving an AI Agent Configuration
runs provisioning, which makes a live provider call.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import agent_provisioning

ABSENT = "no-such-model-fbb1c0"


def _stub(ai_model: str, provider: str):
	"""The fields validate_agent_config reads, and nothing else."""
	return frappe._dict(
		agent_id="stub_agent",
		system_prompt="You are a stub.",
		ai_model=ai_model,
		ai_provider=provider,
		agent_type="Background",
		chat_mode_label=None,
		process_model=None,
	)


def _validate(cfg):
	with patch.object(frappe, "get_doc", return_value=cfg):
		return agent_provisioning.validate_agent_config("stub", test_provider=False)


class TestAgentModelMissingVsDisabled(FrappeTestCase):
	def setUp(self):
		self.provider = frappe.db.get_value("AI Provider", {}, "name")
		if not self.provider:
			self.skipTest("no AI Provider on this site")

	def _errors(self, ai_model):
		return _validate(_stub(ai_model, self.provider))["errors"]

	def test_a_model_that_does_not_exist_says_so(self):
		errors = self._errors(ABSENT)
		joined = " ".join(errors)
		self.assertIn("does not exist", joined)
		self.assertNotIn("disabled", joined)
		self.assertIn(ABSENT, joined, "the message must name the model that is missing")

	def test_a_model_that_is_switched_off_says_disabled(self):
		off = frappe.db.get_value("AI Model", {"enable_model": 0}, "name")
		if not off:
			self.skipTest("no disabled AI Model on this site")
		joined = " ".join(self._errors(off))
		self.assertIn("disabled", joined)
		self.assertNotIn("does not exist", joined)
		self.assertIn(off, joined)

	def test_an_enabled_model_raises_neither(self):
		on = frappe.db.get_value("AI Model", {"enable_model": 1}, ["name", "provider"], as_dict=True)
		if not on or not on.provider:
			self.skipTest("no enabled AI Model with a provider on this site")
		joined = " ".join(_validate(_stub(on.name, on.provider))["errors"])
		self.assertNotIn("does not exist", joined)
		self.assertNotIn("disabled", joined)
