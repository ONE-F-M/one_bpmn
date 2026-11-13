# Copyright (c) 2026, one-fm and contributors

"""No patch file carries a work-item id in a comment or a docstring.

Only comments and module, class and function docstrings are checked. Other string literals, such
as the script and prompt bodies a patch writes to the site, are left alone on purpose.
"""

import ast
import importlib.util
import io
import os
import sys
import tokenize

from frappe.tests.utils import FrappeTestCase

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(ROOT, ".github", "scripts", "check_structure.py")
PATCHES = os.path.join(ROOT, "processa", "patches")

_spec = importlib.util.spec_from_file_location("check_structure", SCRIPT)
cs = importlib.util.module_from_spec(_spec)
# dataclasses looks the module up in sys.modules while the class is built
sys.modules["check_structure"] = cs
_spec.loader.exec_module(cs)


def patch_files():
	found = []
	for folder, _dirs, names in os.walk(PATCHES):
		found.extend(os.path.join(folder, name) for name in names if name.endswith(".py"))
	return sorted(found)


def relative(path):
	return os.path.relpath(path, ROOT)


def read(path):
	with open(path, encoding="utf-8") as handle:
		return handle.read()


def comment_hits(source):
	"""Return (line, text) for every COMMENT token that carries an id."""
	hits = []
	for token in tokenize.generate_tokens(io.StringIO(source).readline):
		if token.type == tokenize.COMMENT and cs.WORK_ITEM_ID.search(token.string):
			hits.append((token.start[0], token.string))
	return hits


def docstring_hits(source):
	"""Return (line, name) for every module, class or function docstring that carries an id."""
	tree = ast.parse(source)
	hits = []
	for node in ast.walk(tree):
		if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
			continue
		docstring = ast.get_docstring(node, clean=False)
		if docstring and cs.WORK_ITEM_ID.search(docstring):
			hits.append((getattr(node, "lineno", 1), getattr(node, "name", "module")))
	return hits


class TestPatchFileIds(FrappeTestCase):
	def test_the_patch_folder_has_python_files(self):
		self.assertTrue(patch_files(), f"no python files found under {PATCHES}")

	def test_no_patch_comment_carries_a_work_item_id(self):
		for path in patch_files():
			for line, text in comment_hits(read(path)):
				self.fail(f"{relative(path)}:{line} has a work-item id in a comment: {text}")

	def test_no_patch_docstring_carries_a_work_item_id(self):
		for path in patch_files():
			for line, name in docstring_hits(read(path)):
				self.fail(f"{relative(path)}:{line} has a work-item id in the docstring of {name}")

	def test_the_scan_catches_an_id_put_back_in_a_comment(self):
		source = "x = 1  # see " + "WI" + "-" + "001234\n"
		self.assertEqual(len(comment_hits(source)), 1)

	def test_the_scan_catches_an_id_put_back_in_a_docstring(self):
		item = "WI" + "-" + "001234"
		source = f'"""{item}: module."""\n\n\nclass A:\n\t"""{item}"""\n\n\ndef f():\n\t"""{item}"""\n'
		self.assertEqual(len(docstring_hits(source)), 3)

	def test_the_scan_ignores_an_id_in_a_plain_string(self):
		source = 'x = "' + "WI" + "-" + '001234"\ny = 1  # an ordinary comment\n'
		self.assertEqual(comment_hits(source), [])
		self.assertEqual(docstring_hits(source), [])
