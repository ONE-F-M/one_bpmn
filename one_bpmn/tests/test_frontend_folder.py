# Copyright (c) 2026, one-fm and contributors
"""The Vue app lives in frontend/, and no maintained file points at the old spiff/ folder."""

import os
import re
import subprocess

from frappe.tests.utils import FrappeTestCase

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OLD_FOLDER = re.compile(r"(?<![A-Za-z_.])spiff/")
# Patches and their test keep the paths they ran with; workflow files change in their own PR.
SKIPPED = (
	"one_bpmn/one_bpmn/patches/",
	"one_bpmn/patches.txt",
	"one_bpmn/tests/test_frontend_agent_eval_cases_follow_the_pages_folder_patch.py",
	".github/workflows/",
)


class TestFrontendFolder(FrappeTestCase):
	def test_the_app_is_in_frontend(self):
		self.assertTrue(os.path.isfile(os.path.join(ROOT, "frontend", "package.json")))
		self.assertFalse(os.path.exists(os.path.join(ROOT, "spiff")))

	def test_no_maintained_file_names_the_old_folder(self):
		tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
		offenders = []
		for path in tracked:
			if path.startswith(SKIPPED) or path.endswith(("yarn.lock", ".png", ".svg", ".ico", ".woff2")):
				continue
			with open(os.path.join(ROOT, path), encoding="utf-8", errors="ignore") as f:
				if OLD_FOLDER.search(f.read()):
					offenders.append(path)
		self.assertEqual(offenders, [])
