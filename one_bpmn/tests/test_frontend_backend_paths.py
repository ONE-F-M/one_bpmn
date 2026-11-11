# Copyright (c) 2026, one-fm and contributors
"""Every backend Python path named in the frontend source points at a file that exists."""

import os
import re

from frappe.tests.utils import FrappeTestCase

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SOURCE = os.path.join(ROOT, "frontend", "src")
PY_PATH = re.compile(r"(?<![\w/.])(?:one_bpmn/)?[a-z_]+(?:/[a-z_0-9]+)+\.py\b")


def named_paths():
	found = []
	for folder, _dirs, names in os.walk(SOURCE):
		for name in names:
			if not name.endswith((".js", ".vue", ".css", ".ts")):
				continue
			path = os.path.join(folder, name)
			with open(path, encoding="utf-8") as handle:
				for number, line in enumerate(handle, 1):
					found.extend((os.path.relpath(path, ROOT), number, m) for m in PY_PATH.findall(line))
	return found


class TestFrontendBackendPaths(FrappeTestCase):
	def test_the_frontend_names_backend_paths(self):
		self.assertTrue(named_paths())

	def test_every_named_backend_path_exists(self):
		for source, number, named in named_paths():
			relative = named.removeprefix("one_bpmn/")
			self.assertTrue(
				os.path.isfile(os.path.join(ROOT, "one_bpmn", relative)),
				f"{source}:{number} names {named}, which does not exist",
			)
