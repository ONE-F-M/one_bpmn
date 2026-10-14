# Copyright (c) 2026, one-fm and contributors
"""The production deploy's failure trap must be set before `bench setup requirements` and must restart the web group.

bench setup requirements upgrades Python packages in place. If a later step fails, the workers are started again
but a web server running with --preload keeps the old packages in memory, so the trap has to restart it too.
"""

import os

from frappe.tests.utils import FrappeTestCase

# one_bpmn/tests/<this file> -> repo root is three levels up.
WORKFLOW = os.path.join(
	os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
	".github",
	"workflows",
	"deploy-production.yml",
)
SETUP_REQUIREMENTS = "bench setup requirements one_bpmn"
WEB_RESTART = "supervisorctl restart $NAME-web:"


class TestDeployProductionWorkflow(FrappeTestCase):
	def _lines(self):
		with open(WORKFLOW) as f:
			return f.read().splitlines()

	def _trap_indexes(self, lines):
		return [i for i, line in enumerate(lines) if line.strip().startswith("trap ") and line.rstrip().endswith("EXIT")]

	def test_failure_trap_is_set_before_bench_setup_requirements(self):
		lines = self._lines()
		setup = [i for i, line in enumerate(lines) if line.strip() == SETUP_REQUIREMENTS]
		self.assertEqual(len(setup), 1, "expected exactly one 'bench setup requirements' line")
		traps = self._trap_indexes(lines)
		self.assertEqual(len(traps), 1, "expected exactly one EXIT trap in the deploy script")
		self.assertLess(traps[0], setup[0], "the trap must be set before bench setup requirements")

	def test_failure_trap_restarts_the_web_group_and_starts_the_workers(self):
		lines = self._lines()
		traps = self._trap_indexes(lines)
		self.assertEqual(len(traps), 1, "expected exactly one EXIT trap in the deploy script")
		trap = lines[traps[0]]
		self.assertIn(WEB_RESTART, trap)
		self.assertIn("supervisorctl start $WORKERS", trap)
