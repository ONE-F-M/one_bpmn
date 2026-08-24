# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Which model a Direct eval actually calls (WI-001751 follow-up).

A Direct eval is supposed to exercise the agent under test — its prompt, its
credentials, and its model. The runner used to read the model from
``AI Provider.default_model``, a field WI-001655 removed, so it
tested whatever stale value survived on that site (or errored where the column
had been dropped) and never the agent's own catalog pick.

Nothing caught it because the model only shows up inside the executor call, and
the executor is mocked in every other test. These tests read it back off the
ExecutorConfig the runner hands over.

The executor is mocked throughout — no real LLM call is made.
"""
from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents._eval_test_factories import (
    make_agent_configuration,
    make_eval_case,
    make_eval_run,
    make_eval_suite,
    patch_executor,
    success_result,
)
from one_bpmn.agents.eval_runner import _execute_eval_suite


class TestDirectEvalModel(FrappeTestCase):
    def setUp(self):
        self.credentials = self._make_credentials()

    def _make_credentials(self):
        name = f"_Test Eval Creds {frappe.generate_hash(length=6)}"
        doc = frappe.get_doc({
            "doctype": "AI Provider",
            "provider": name,
            "provider_type": "Anthropic",
            "api_key": "sk-test-not-a-real-key",
            "enabled": 1,
        })
        doc.flags.ignore_mandatory = True
        doc.insert(ignore_permissions=True)
        return doc.name

    def _make_model(self, model_id: str):
        doc = frappe.get_doc({
            "doctype": "AI Model",
            "enable_model": 1,
            "model_name": model_id,
            "provider": self.credentials,
        })
        doc.flags.ignore_mandatory = True
        doc.flags.ignore_links = True
        return doc.insert(ignore_permissions=True).name

    def _model_used_by_direct_eval(self, agent) -> str:
        """Run a one-case Direct suite and return the model the runner asked
        the executor for."""
        suite = make_eval_suite(agent_configuration=agent.name, eval_type="Direct")
        make_eval_case(suite=suite.name)
        run = make_eval_run(suite.name)

        seen = {}

        def handler(config, context):
            seen["model"] = config.model
            return success_result("ok")

        with patch_executor(handler):
            _execute_eval_suite(run.name)

        return seen.get("model", "<executor never called>")

    def test_uses_the_agents_own_model(self):
        """The agent's catalog pick is what gets called — not anything derived
        from its credentials record."""
        model_id = self._make_model(f"_test-model-{frappe.generate_hash(length=6)}")
        agent = make_agent_configuration(
            ai_provider=self.credentials, ai_model=model_id
        )

        self.assertEqual(self._model_used_by_direct_eval(agent), model_id)

    def test_falls_back_to_a_catalog_model_for_a_legacy_agent(self):
        """An agent with no ai_model (pre-WI-001655) still resolves to a real
        model linked to its credentials, rather than an empty string."""
        model_id = self._make_model(f"_test-legacy-{frappe.generate_hash(length=6)}")
        agent = make_agent_configuration(ai_provider=self.credentials)
        # derive_provider_from_model only fills the provider FROM a model, so an
        # agent with no model keeps its credentials link and an empty ai_model.
        self.assertFalse(agent.get("ai_model"))

        self.assertEqual(self._model_used_by_direct_eval(agent), model_id)

    def test_does_not_read_the_removed_credentials_field(self):
        """The regression itself: a Direct eval must not consult
        AI Provider for a model.

        Asserted by making any read of that doctype's removed field fail loudly
        — on a site where the column was dropped this is exactly what happened,
        and the runner turned every Direct case into an Error result.
        """
        model_id = self._make_model(f"_test-guard-{frappe.generate_hash(length=6)}")
        agent = make_agent_configuration(
            ai_provider=self.credentials, ai_model=model_id
        )

        real_get_value = frappe.db.get_value

        def guarded(doctype, *args, **kwargs):
            fieldname = args[1] if len(args) > 1 else kwargs.get("fieldname")
            if doctype == "AI Provider" and fieldname == "default_model":
                raise AssertionError(
                    "eval_runner read AI Provider.default_model, "
                    "which WI-001655 removed."
                )
            return real_get_value(doctype, *args, **kwargs)

        frappe.db.get_value = guarded
        try:
            self.assertEqual(self._model_used_by_direct_eval(agent), model_id)
        finally:
            frappe.db.get_value = real_get_value
