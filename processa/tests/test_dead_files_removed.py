import importlib.util
import re
from pathlib import Path

from frappe.tests.utils import FrappeTestCase

REPO_ROOT = Path(__file__).resolve().parents[2]

REMOVED_PATHS = [
	"processa/public/js/bpmn_spiffworkflow.js",
	"processa/api/workflow_actions.py",
	"processa/config/__init__.py",
	"processa/templates/pages/__init__.py",
	"processa/public/.gitkeep",
	"processa/public/css/properties-panel.css",
	"processa/public/css/element-templates.css",
	"processa/exports/document_request.bpmn",
	"processa/exports/document_request_config.json",
]

COMMENTED_HOOK = re.compile(r"^#\s*[a-z_]+\s*=")


class TestDeadFilesRemoved(FrappeTestCase):
	def test_removed_paths_do_not_exist(self):
		for rel_path in REMOVED_PATHS:
			self.assertFalse((REPO_ROOT / rel_path).exists(), rel_path)

	def test_workflow_actions_module_is_not_importable(self):
		self.assertIsNone(importlib.util.find_spec("processa.api.workflow_actions"))

	def test_hooks_has_no_commented_out_hook(self):
		hooks_lines = (REPO_ROOT / "processa" / "hooks.py").read_text(encoding="utf-8").splitlines()
		offenders = [line for line in hooks_lines if COMMENTED_HOOK.match(line)]
		self.assertEqual(offenders, [])
