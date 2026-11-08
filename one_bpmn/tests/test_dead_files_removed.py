import importlib.util
import re
from pathlib import Path

from frappe.tests.utils import FrappeTestCase

REPO_ROOT = Path(__file__).resolve().parents[2]

REMOVED_PATHS = [
	"one_bpmn/public/js/bpmn_spiffworkflow.js",
	"one_bpmn/api/workflow_actions.py",
	"one_bpmn/config/__init__.py",
	"one_bpmn/templates/pages/__init__.py",
	"one_bpmn/public/.gitkeep",
	"one_bpmn/public/css/properties-panel.css",
	"one_bpmn/public/css/element-templates.css",
	"one_bpmn/exports/document_request.bpmn",
	"one_bpmn/exports/document_request_config.json",
]

COMMENTED_HOOK = re.compile(r"^#\s*[a-z_]+\s*=")


class TestDeadFilesRemoved(FrappeTestCase):
	def test_removed_paths_do_not_exist(self):
		for rel_path in REMOVED_PATHS:
			self.assertFalse((REPO_ROOT / rel_path).exists(), rel_path)

	def test_workflow_actions_module_is_not_importable(self):
		self.assertIsNone(importlib.util.find_spec("one_bpmn.api.workflow_actions"))

	def test_hooks_has_no_commented_out_hook(self):
		hooks_lines = (REPO_ROOT / "one_bpmn" / "hooks.py").read_text(encoding="utf-8").splitlines()
		offenders = [line for line in hooks_lines if COMMENTED_HOOK.match(line)]
		self.assertEqual(offenders, [])
