# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Tests for deployment gating — _check_eval_suite_gating returns advisory
warnings based on the latest run of any gate_deployment eval suite linked
to a model. The check is non-blocking; it only produces warning strings.
"""
from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.compilation import _check_eval_suite_gating
from one_bpmn.agents._eval_test_factories import make_eval_run, make_eval_suite


def _model_name():
    """A unique fake BPMN Process Model name (links are ignored in factories)."""
    return "_Test Model " + frappe.generate_hash(length=8)


class TestEvalGating(FrappeTestCase):

    def test_no_warning_when_last_run_passed(self):
        """(a) a passing last run produces no warnings."""
        model = _model_name()
        suite = make_eval_suite(process_model=model, gate_deployment=1)
        make_eval_run(suite.name, status="Passed")

        self.assertEqual(_check_eval_suite_gating(model), [])

    def test_warning_when_last_run_failed(self):
        """(b) a failing last run produces a warning."""
        model = _model_name()
        suite = make_eval_suite(process_model=model, gate_deployment=1)
        make_eval_run(suite.name, status="Failed")

        warnings = _check_eval_suite_gating(model)
        self.assertEqual(len(warnings), 1)
        self.assertIn("failed", warnings[0].lower())

    def test_warning_when_suite_never_run(self):
        """(c) a gated suite with no runs produces a warning."""
        model = _model_name()
        make_eval_suite(process_model=model, gate_deployment=1)

        warnings = _check_eval_suite_gating(model)
        self.assertEqual(len(warnings), 1)
        self.assertIn("never been run", warnings[0].lower())

    def test_no_warning_when_no_suite_linked(self):
        """(d) no gated suite linked to the model produces no warnings."""
        # A model with no suites at all.
        self.assertEqual(_check_eval_suite_gating(_model_name()), [])

        # A linked suite that is not gating deployment is also ignored.
        model = _model_name()
        suite = make_eval_suite(process_model=model, gate_deployment=0)
        make_eval_run(suite.name, status="Failed")
        self.assertEqual(_check_eval_suite_gating(model), [])
