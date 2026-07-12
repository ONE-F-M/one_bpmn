# Copyright (c) 2026, one-fm and contributors
"""
Unit tests for the structural AST script validator
(``one_bpmn.security.script_validator.deep_inspect_script``).

Pure Python — no Frappe / DB required — so these run standalone and cover
every edge case in the BPMN Script-Task security spec (section 2.1 / 4.1).
"""

import unittest

from one_bpmn.security.script_validator import (
	ValidatorOptions,
	deep_inspect_script,
	validate_script,
)


def _flags(code, **opts):
	return deep_inspect_script(code, ValidatorOptions(**opts) if opts else None)


class TestSafeScriptsPass(unittest.TestCase):
	def test_orm_read_write(self):
		self.assertEqual(_flags("doc = frappe.get_doc('Employee', 'E1')\ndoc.save()"), [])

	def test_db_read_sql(self):
		self.assertEqual(_flags("rows = frappe.db.sql('select name from tabUser')"), [])

	def test_get_all_and_msgprint(self):
		self.assertEqual(
			_flags("users = frappe.get_all('User')\nfrappe.msgprint(str(len(users)))"), []
		)

	def test_def_lambda_while_allowed_by_default(self):
		self.assertEqual(_flags("def f(x):\n    return x\nresult['n'] = f(1)"), [])
		self.assertEqual(_flags("g = lambda x: x + 1\nresult['n'] = g(1)"), [])
		self.assertEqual(_flags("i = 0\nwhile i < 3:\n    i += 1"), [])

	def test_soft_builtins_allowed_by_default(self):
		self.assertEqual(_flags("t = type(doc)\nh = hasattr(doc, 'name')"), [])

	def test_small_multiplication_allowed(self):
		self.assertEqual(_flags("s = 'ab' * 1000\nn = 3 * 4"), [])


class TestBannedBuiltins(unittest.TestCase):
	def test_hard_banned(self):
		for name in ("exec", "eval", "compile", "getattr", "setattr", "delattr",
					 "globals", "locals", "vars", "dir", "open"):
			with self.subTest(builtin=name):
				out = _flags(f"{name}(doc)")
				self.assertTrue(any(name in v for v in out), out)

	def test_dunder_import_call(self):
		self.assertTrue(_flags("__import__('os')"))

	def test_soft_builtins_only_blocked_in_strict(self):
		self.assertEqual(_flags("hasattr(doc, 'x')"), [])
		self.assertTrue(_flags("hasattr(doc, 'x')", strict_builtins=True))
		self.assertTrue(_flags("type(doc)", strict_builtins=True))


class TestBannedAttributes(unittest.TestCase):
	def test_frame_walking(self):
		for attr in ("__class__", "__bases__", "__subclasses__", "__globals__",
					 "f_back", "f_globals", "gi_frame", "__mro__", "__dict__"):
			with self.subTest(attr=attr):
				self.assertTrue(_flags(f"x = obj.{attr}"), attr)

	def test_frappe_permission_internals(self):
		self.assertTrue(_flags("doc.flags.ignore_permissions = True"))
		self.assertTrue(_flags("doc.db_update()"))
		self.assertTrue(_flags("role.add_roles('System Manager')"))

	def test_soft_frappe_attrs_only_blocked_in_strict(self):
		self.assertEqual(_flags("frappe.db.sql('select 1')"), [])
		self.assertTrue(_flags("frappe.db.sql('select 1')", strict_frappe_attrs=True))
		self.assertTrue(_flags("c = frappe.conf", strict_frappe_attrs=True))


class TestKwargsPermissionInjection(unittest.TestCase):
	def test_explicit_kwarg(self):
		self.assertTrue(_flags("doc.save(ignore_permissions=True)"))
		self.assertTrue(_flags("doc.insert(ignore_permissions=True)"))

	def test_dict_unpack(self):
		self.assertTrue(_flags('doc.save(**{"ignore_permissions": True})'))


class TestSubscriptStringLookup(unittest.TestCase):
	def test_dunder_subscript(self):
		self.assertTrue(_flags('x = frappe["__dict__"]'))
		self.assertTrue(_flags('x = obj["f_back"]'))
		self.assertTrue(_flags('x = obj["__globals__"]'))

	def test_normal_subscript_ok(self):
		self.assertEqual(_flags('x = mydict["name"]'), [])


class TestImports(unittest.TestCase):
	def test_forbidden_module(self):
		self.assertTrue(_flags("import os"))
		self.assertTrue(_flags("from subprocess import run"))

	def test_safe_module_allowed_by_default(self):
		self.assertEqual(_flags("import json\nimport datetime"), [])

	def test_block_all_imports_strict(self):
		self.assertTrue(_flags("import json", block_all_imports=True))
		self.assertTrue(_flags("from datetime import datetime", block_all_imports=True))


class TestControlFlowGated(unittest.TestCase):
	def test_while_gate(self):
		self.assertEqual(_flags("while True:\n    break"), [])
		self.assertTrue(_flags("while True:\n    break", block_while=True))

	def test_functiondef_gate(self):
		self.assertEqual(_flags("def f():\n    pass"), [])
		self.assertTrue(_flags("def f():\n    pass", block_functiondef=True))

	def test_lambda_gate(self):
		self.assertEqual(_flags("f = lambda: 1"), [])
		self.assertTrue(_flags("f = lambda: 1", block_lambda=True))


class TestMemoryBomb(unittest.TestCase):
	def test_large_multiply_flagged(self):
		self.assertTrue(_flags("x = 'A' * 999999999"))
		self.assertTrue(_flags("x = 999999999 * 'A'"))
		self.assertTrue(_flags("x = [0] * 10000000"))

	def test_threshold_boundary(self):
		self.assertEqual(_flags("x = 'A' * 50000"), [])
		self.assertTrue(_flags("x = 'A' * 50001"))

	def test_custom_threshold(self):
		self.assertTrue(_flags("x = 'A' * 200", binop_multiply_threshold=100))


class TestDestructiveSql(unittest.TestCase):
	def test_destructive_flagged(self):
		for kw in ("DROP TABLE tabUser", "TRUNCATE tabUser", "ALTER TABLE tabUser ADD x INT"):
			with self.subTest(sql=kw):
				self.assertTrue(_flags(f"frappe.db.sql('{kw}')"))

	def test_select_allowed(self):
		self.assertEqual(_flags("frappe.db.sql('select name from tabUser')"), [])


class TestSyntaxAndWrapper(unittest.TestCase):
	def test_syntax_error(self):
		out = _flags("def broken(:\n    pass")
		self.assertEqual(len(out), 1)
		self.assertIn("Syntax error", out[0])

	def test_validate_script_wrapper(self):
		self.assertEqual(validate_script("doc = frappe.get_doc('X', 'y')"), {"valid": True, "violations": []})
		bad = validate_script("import os")
		self.assertFalse(bad["valid"])
		self.assertTrue(bad["violations"])

	def test_empty_script(self):
		self.assertEqual(_flags(""), [])
		self.assertEqual(_flags(None), [])


if __name__ == "__main__":
	unittest.main()
