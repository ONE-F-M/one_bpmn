# Copyright (c) 2026, one-fm and contributors
"""Tests for the script security check: each finding carries its category, name, kind and line."""

import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_security.code_checks.script_categories import clear_category_cache
from processa.ai_agent_security.code_checks.script_validator import (
	SYNTAX_ERROR,
	deep_inspect_script,
	inspect_script,
	request_findings,
	validate_script,
)
from processa.patches.v1_0 import seed_script_import_categories

SETTINGS_FIELDS = (
	"section_break_script_security",
	"script_security_intro",
	"column_break_script_security",
	"script_block_while",
	"script_block_functiondef",
	"script_block_lambda",
	"script_strict_builtins",
	"script_strict_frappe_attrs",
	"script_block_all_imports",
	"script_binop_multiply_threshold",
)


def _flags(code):
	return deep_inspect_script(code)


class _CategoryTestCase(FrappeTestCase):
	def setUp(self):
		super().setUp()
		clear_category_cache()
		seed_script_import_categories.execute()

	def tearDown(self):
		frappe.db.rollback()
		clear_category_cache()
		super().tearDown()

	def _set_category(self, name, **values):
		category = frappe.get_doc("Script Import Category", name)
		category.update(values)
		category.save()


class TestFindingsByCategory(_CategoryTestCase):
	def test_an_import_is_reported_with_category_name_kind_and_line(self):
		self.assertEqual(
			inspect_script("x = 1\ny = 2\nimport requests"),
			[
				{
					"category": "Network",
					"name": "requests",
					"kind": "Module",
					"line": 3,
					"message": "requests needs approval (Network)",
				}
			],
		)

	def test_allowed_categories_give_no_findings(self):
		self.assertEqual(inspect_script("import json\ndoc = frappe.get_doc('ToDo', 'x')"), [])

	def test_an_alias_of_frappe_db_is_followed(self):
		findings = inspect_script("db = frappe.db\ndb.sql('select 1')")  # validator input
		self.assertEqual(
			[(f["name"], f["category"], f["line"]) for f in findings],
			[("frappe.db.sql", "Database direct", 2)],
		)

	def test_permission_keyword_through_kwargs(self):
		findings = inspect_script("doc.save(**{'ignore_permissions': True})")
		self.assertEqual([f["category"] for f in findings], ["Identity and permissions"])

	def test_a_module_in_no_category_is_unlisted(self):
		findings = inspect_script("import paramiko")
		self.assertEqual([(f["name"], f["category"]) for f in findings], [("paramiko", "Unlisted")])

	def test_unlisted_frappe_functions_and_builtins_are_not_reported(self):
		self.assertEqual(
			inspect_script("rows = frappe.get_all('ToDo')\nfrappe.log_error('x')\nn = len(rows)"), []
		)

	def test_size_limit_follows_the_category_threshold(self):
		code = "x = 'A' * 60000"
		self.assertEqual([f["category"] for f in inspect_script(code)], ["Size limits"])
		self._set_category("Size limits", threshold=100000)
		self.assertEqual(inspect_script(code), [])

	def test_a_script_that_does_not_parse_is_one_syntax_error(self):
		findings = inspect_script("x = 1\nprint(''")
		self.assertEqual(len(findings), 1)
		self.assertEqual(findings[0]["category"], SYNTAX_ERROR)
		self.assertEqual(findings[0]["line"], 2)

	def test_language_features_need_approval_when_their_category_does(self):
		code = "i = 0\nwhile i < 3:\n    i += 1"
		self.assertEqual(_flags(code), [])
		self._set_category("Language features", allowed_by_default=0)
		self.assertEqual([f["name"] for f in inspect_script(code)], ["while"])

	def test_an_approved_name_is_not_reported(self):
		code = "rows = frappe.db.sql('select name from tabUser')"  # validator input, not a query
		self.assertTrue(_flags(code))
		self.assertEqual(deep_inspect_script(code, frozenset({"frappe.db.sql"})), [])

	def test_processa_settings_has_no_script_security_fields(self):
		meta = frappe.get_meta("Processa Settings")
		for fieldname in SETTINGS_FIELDS:
			with self.subTest(fieldname=fieldname):
				self.assertFalse(meta.has_field(fieldname))


class TestSafeScriptsPass(_CategoryTestCase):
	def test_orm_read_write(self):
		self.assertEqual(_flags("doc = frappe.get_doc('Employee', 'E1')\ndoc.save()"), [])

	def test_get_all_and_msgprint(self):
		self.assertEqual(_flags("users = frappe.get_all('User')\nfrappe.msgprint(str(len(users)))"), [])

	def test_def_lambda_while_class_allowed_by_default(self):
		self.assertEqual(_flags("def f(x):\n    return x\nresult['n'] = f(1)"), [])
		self.assertEqual(_flags("g = lambda x: x + 1\nresult['n'] = g(1)"), [])
		self.assertEqual(_flags("i = 0\nwhile i < 3:\n    i += 1"), [])
		self.assertEqual(_flags("class A:\n    pass"), [])

	def test_soft_builtins_allowed_by_default(self):
		self.assertEqual(_flags("t = type(doc)\nh = hasattr(doc, 'name')"), [])

	def test_small_multiplication_allowed(self):
		self.assertEqual(_flags("s = 'ab' * 1000\nn = 3 * 4"), [])


class TestBannedBuiltins(_CategoryTestCase):
	def test_dynamic_code_and_file_builtins(self):
		for name in (
			"exec",
			"eval",
			"compile",
			"getattr",
			"setattr",
			"delattr",
			"globals",
			"locals",
			"vars",
			"dir",
			"open",
		):
			with self.subTest(builtin=name):
				out = _flags(f"{name}(doc)")
				self.assertTrue(any(name in v for v in out), out)

	def test_dunder_import_call(self):
		self.assertTrue(_flags("__import__('os')"))


class TestBannedAttributes(_CategoryTestCase):
	def test_frame_walking(self):
		for attr in (
			"__class__",
			"__bases__",
			"__subclasses__",
			"__globals__",
			"f_back",
			"f_globals",
			"gi_frame",
			"__mro__",
			"__dict__",
		):
			with self.subTest(attr=attr):
				self.assertTrue(_flags(f"x = obj.{attr}"), attr)

	def test_frappe_permission_internals(self):
		self.assertTrue(_flags("doc.flags.ignore_permissions = True"))
		self.assertTrue(_flags("doc.db_update()"))
		self.assertTrue(_flags("role.add_roles('System Manager')"))

	def test_secrets(self):
		self.assertTrue(_flags("c = frappe.conf"))
		self.assertTrue(_flags("p = settings.get_password('api_key')"))

	def test_bare_builtins_name(self):
		self.assertTrue(_flags("b = __builtins__"))


class TestKwargsPermissionInjection(_CategoryTestCase):
	def test_explicit_kwarg(self):
		self.assertTrue(_flags("doc.save(ignore_permissions=True)"))
		self.assertTrue(_flags("doc.insert(ignore_permissions=True)"))

	def test_dict_unpack(self):
		self.assertTrue(_flags('doc.save(**{"ignore_permissions": True})'))
		self.assertTrue(_flags("doc.save(**{key: True})"))


class TestSubscriptStringLookup(_CategoryTestCase):
	def test_dunder_subscript(self):
		self.assertTrue(_flags('x = frappe["__dict__"]'))
		self.assertTrue(_flags('x = obj["f_back"]'))
		self.assertTrue(_flags('x = obj["__globals__"]'))

	def test_normal_subscript_ok(self):
		self.assertEqual(_flags('x = mydict["name"]'), [])

	def test_session_write(self):
		self.assertTrue(_flags("frappe.session.user = 'Administrator'"))
		self.assertTrue(_flags("frappe.flags.update({'x': 1})"))


class TestImports(_CategoryTestCase):
	def test_approval_module(self):
		self.assertTrue(_flags("import os"))
		self.assertTrue(_flags("from subprocess import run"))
		self.assertTrue(_flags("from urllib.request import urlopen"))

	def test_safe_module_allowed_by_default(self):
		self.assertEqual(_flags("import json\nimport datetime\nfrom urllib.parse import quote"), [])

	def test_star_import(self):
		self.assertTrue(_flags("from frappe.utils import *"))


class TestBuiltinsModuleEscape(_CategoryTestCase):
	"""exec must not come back through a module or an attribute."""

	def test_the_builtins_module_needs_approval(self):
		for code in (
			"import builtins\nbuiltins.exec('x=1')",
			"import builtins as b\nb.eval('1+1')",
			"from builtins import exec\nexec('x=1')",
			"from builtins import exec as e\ne('x=1')",
			"import builtins\nbuiltins.__import__('os').system('id')",
		):
			with self.subTest(code=code):
				self.assertTrue(_flags(code), f"builtins escape not caught: {code!r}")

	def test_modules_that_execute_a_string_need_approval(self):
		for code in (
			"import runpy\nrunpy.run_path('/tmp/x.py')",
			"import code\ncode.InteractiveInterpreter().runsource('x=1')",
			"import codeop\ncodeop.compile_command('x=1')",
			"import timeit\ntimeit.timeit('1')",
			"import pdb\npdb.run('x=1')",
			"import bdb\nbdb.Bdb().run('x=1')",
			"import operator\noperator.attrgetter('__globals__')(frappe)",
			"import asyncio\nasyncio.create_subprocess_shell('id')",
			"import platform\nplatform.popen('id')",
			"import webbrowser\nwebbrowser.open('x')",
		):
			with self.subTest(code=code):
				self.assertTrue(_flags(code), f"code-execution module allowed: {code!r}")

	def test_exec_as_an_attribute_is_caught_whatever_holds_it(self):
		self.assertTrue(_flags("import json\njson.exec('x=1')"))
		self.assertTrue(_flags("obj.eval('1+1')"))
		self.assertTrue(_flags("m.__import__('os')"))

	def test_ordinary_attribute_calls_that_share_a_name_still_pass(self):
		self.assertEqual(_flags("import re\nre.compile('x')"), [])
		self.assertEqual(_flags("import json\nx = json.dumps({'a': 1})"), [])
		self.assertEqual(_flags("rows = frappe.db.get_all('User')\nresult = [r.name for r in rows]"), [])


class TestMemoryBomb(_CategoryTestCase):
	def test_large_multiply_flagged(self):
		self.assertTrue(_flags("x = 'A' * 999999999"))
		self.assertTrue(_flags("x = 999999999 * 'A'"))
		self.assertTrue(_flags("x = [0] * 10000000"))

	def test_threshold_boundary(self):
		self.assertEqual(_flags("x = 'A' * 50000"), [])
		self.assertTrue(_flags("x = 'A' * 50001"))


class TestDestructiveSql(_CategoryTestCase):
	def test_destructive_flagged_even_when_sql_is_approved(self):
		for kw in ("DROP TABLE tabUser", "TRUNCATE tabUser", "ALTER TABLE tabUser ADD x INT"):
			with self.subTest(sql=kw):
				self.assertTrue(deep_inspect_script(f"frappe.db.sql('{kw}')", frozenset({"frappe.db.sql"})))  # validator input, not a query


class TestSyntaxAndWrapper(_CategoryTestCase):
	def test_a_syntax_error_names_its_line_and_reason_and_nothing_else(self):
		self.assertEqual(_flags('x = 1\nprint(""'), ["Syntax error on line 2: '(' was never closed"])

	def test_validate_script_wrapper(self):
		self.assertEqual(
			validate_script("doc = frappe.get_doc('X', 'y')"),
			{"valid": True, "violations": [], "findings": []},
		)
		bad = validate_script("import os")
		self.assertFalse(bad["valid"])
		self.assertTrue(bad["violations"])

	def test_findings_carry_the_category_name_and_offending_line(self):
		code = "x = 1\nfor d in []:\n    d.save(ignore_permissions=True)\nfrappe.db.sql('DROP TABLE tabX')"
		self.assertEqual(
			validate_script(code)["findings"],
			[
				{
					"rule": "ignore_permissions=... needs approval (Identity and permissions)",
					"line": 3,
					"code": "d.save(ignore_permissions=True)",
					"category": "Identity and permissions",
					"name": "permission_kwarg",
				},
				{
					"rule": "frappe.db.sql needs approval (Database direct)",
					"line": 4,
					"code": "frappe.db.sql('DROP TABLE tabX')",  # validator input, not a query
					"category": "Database direct",
					"name": "frappe.db.sql",
				},
				{
					"rule": "Destructive SQL (DROP/TRUNCATE/ALTER/CREATE TABLE) needs approval (Database direct)",
					"line": 4,
					"code": "frappe.db.sql('DROP TABLE tabX')",  # validator input, not a query
					"category": "Database direct",
					"name": "destructive_sql",
				},
			],
		)

	def test_empty_script(self):
		self.assertEqual(_flags(""), [])
		self.assertEqual(_flags(None), [])


def _rules(code, request, language="python"):
	return [f["rule"] for f in request_findings(code, request, language)]


class TestRequestFindings(unittest.TestCase):
	def test_a_name_never_imported_is_reported_with_its_line(self):
		findings = request_findings("x = 1\nrows = json.loads(task_data.get('p'))", "parse the payload")

		self.assertEqual(len(findings), 1)
		self.assertIn("`json` is used but never defined or imported", findings[0]["rule"])
		self.assertEqual(findings[0]["line"], 2)
		self.assertEqual(findings[0]["code"], "rows = json.loads(task_data.get('p'))")

	def test_injected_defined_and_imported_names_pass(self):
		code = (
			"import json\n"
			"def total(rows):\n"
			"    return sum(r['n'] for r in rows)\n"
			"try:\n"
			"    data = json.loads(task_data.get('p'))\n"
			"except ValueError as e:\n"
			"    data = []\n"
			"result['n'] = total(data)\n"
			"frappe.msgprint(context_doctype + context_docname + doc.name + str(e))"
		)
		self.assertEqual(_rules(code, "sum the rows"), [])

	def test_a_number_replaced_by_another_is_reported(self):
		self.assertIn(
			"The request says 5, but the script uses 10 instead. Use the request's numbers exactly.",
			_rules("x = frappe.get_all('ToDo', limit=10)", "list the 5 latest todos"),
		)
		self.assertTrue(_rules("x = frappe.get_all('ToDo', limit=10)", "show 5 todos, not 10"))
		self.assertTrue(_rules("x = frappe.get_all('ToDo', limit=10)", "change the limit from 10 to 5"))

	def test_numbers_that_match_or_only_count_changes_pass(self):
		self.assertEqual(_rules("x = frappe.get_all('ToDo', limit=5)", "list the 5 latest todos"), [])
		self.assertEqual(_rules("x = frappe.get_all('ToDo', limit=5)", "change the limit from 10 to 5"), [])
		self.assertEqual(_rules("for i in range(3):\n    frappe.msgprint(str(i))", "update 2 fields"), [])

	def test_a_server_script_returned_for_a_client_script_request_is_reported(self):
		self.assertTrue(_rules("x = 1", "write a client script that hides the Notes field"))
		self.assertEqual(_rules("frappe.ui.form.on('ToDo', {})", "write a client script", "javascript"), [])
		self.assertTrue(_rules("frappe.ui.form.on('ToDo', {})", "write a server script", "javascript"))
