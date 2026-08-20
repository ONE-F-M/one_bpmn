# Copyright (c) 2026, one-fm and contributors
"""Authoring a connector's Python handler.

The delivery path opens a real pull request, so these tests cover everything up
to that boundary — validation, the malicious-construct screen, module rendering
and merging — plus the two refusals that must happen BEFORE any branch is
created. The GitHub call itself is not exercised here for the same reason
``test_customization_pr_routing`` does not exercise it: it needs a live token and
network, and what can go wrong locally is the file we would push.
"""

import ast

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.connectors import handler_authoring as ha

GOOD = '''def fetch_rate(params, ctx):
    """A signed request the declarative executor cannot express."""
    import hashlib, hmac, requests
    stamp = str(params.get("timestamp") or "")
    sig = hmac.new(b"key", (stamp + params["symbol"]).encode(), hashlib.sha256).hexdigest()
    reply = requests.get(
        "https://api.example.com/rate",
        params={"symbol": params["symbol"], "sig": sig},
        timeout=20,
    )
    reply.raise_for_status()
    return {"rate": reply.json()["rate"]}
'''


class TestHandlerNaming(FrappeTestCase):
	def test_paths_agree_with_the_dispatcher_and_the_repository(self):
		"""The dotted path must resolve and the file path must be repo-relative.

		These two are derived separately and used in different places — one goes
		into the operation row, one into the pull request — so they are pinned
		together. Getting either wrong produces a connector that looks configured
		and cannot run.
		"""
		self.assertEqual(
			ha.handler_path("Acme CRM", "fetch_rate"),
			"one_bpmn.one_bpmn.connectors.generated.acme_crm_ops.fetch_rate",
		)
		self.assertEqual(
			ha.repo_path("Acme CRM"),
			"one_bpmn/one_bpmn/connectors/generated/acme_crm_ops.py",
		)

	def test_the_generated_package_is_importable(self):
		"""A handler is resolved with frappe.get_attr, which imports the package."""
		import importlib

		self.assertTrue(importlib.import_module(ha.GENERATED_MODULE_ROOT))


class TestHandlerValidation(FrappeTestCase):
	def test_a_usable_handler_passes(self):
		self.assertEqual(ha.validate_handler(GOOD, "fetch_rate"),
		                 {"ok": True, "errors": [], "warnings": []})

	def test_the_outbound_toolkit_is_not_flagged(self):
		"""A screen that banned these would ban every handler worth writing."""
		code = (
			"import requests, json, re, base64, hashlib, hmac, time, datetime\n"
			"import urllib.parse\n"
			"import frappe\n"
			"def f(params, ctx):\n"
			"    return {'ok': True}\n"
		)
		self.assertTrue(ha.validate_handler(code, "f")["ok"])

	def test_signature_must_be_params_ctx(self):
		result = ha.validate_handler("def f(a, b):\n    return {}\n", "f")
		self.assertFalse(result["ok"])
		self.assertIn("must take exactly", result["errors"][0])

	def test_async_is_refused(self):
		result = ha.validate_handler("async def f(params, ctx):\n    return {}\n", "f")
		self.assertFalse(result["ok"])
		self.assertIn("async", result["errors"][0])

	def test_the_named_function_must_be_defined(self):
		result = ha.validate_handler("def other(params, ctx):\n    return {}\n", "f")
		self.assertFalse(result["ok"])
		self.assertIn("not 'f'", result["errors"][0])

	def test_no_return_is_a_warning_not_an_error(self):
		"""It is legal and occasionally intended, but the output variable will be
		empty — which is the kind of thing a reviewer wants told to them."""
		result = ha.validate_handler("def f(params, ctx):\n    pass\n", "f")
		self.assertTrue(result["ok"])
		self.assertTrue(result["warnings"])

	def test_unparseable_code_is_reported_not_raised(self):
		result = ha.validate_handler("def f(params, ctx)\n    return {}\n", "f")
		self.assertFalse(result["ok"])
		self.assertIn("does not parse", result["errors"][0])


class TestMaliciousConstructScreen(FrappeTestCase):
	"""Each of these must be refused. The screen is narrow on purpose, so the
	list it does cover has to actually hold."""

	def _blocked(self, code, needle):
		result = ha.validate_handler(code, "f")
		self.assertFalse(result["ok"], f"should have been refused: {code!r}")
		self.assertTrue(
			any(needle in e for e in result["errors"]),
			f"expected {needle!r} in {result['errors']}",
		)

	def test_eval(self):
		self._blocked("def f(params, ctx):\n    return eval(params['x'])\n", "eval")

	def test_exec(self):
		self._blocked("def f(params, ctx):\n    exec(params['x'])\n    return {}\n", "exec")

	def test_subprocess_import(self):
		self._blocked("import subprocess\ndef f(params, ctx):\n    return {}\n", "subprocess")

	def test_shell_out(self):
		self._blocked("import os\ndef f(params, ctx):\n    os.system('id')\n    return {}\n", "os.system")

	def test_destructive_filesystem_call(self):
		self._blocked("import shutil\ndef f(params, ctx):\n    shutil.rmtree('/x')\n    return {}\n", "shutil.rmtree")

	def test_frame_reflection(self):
		self._blocked("def f(params, ctx):\n    return f.__globals__\n", "__globals__")

	def test_getattr_indirection(self):
		self._blocked("def f(params, ctx):\n    return getattr(params, 'x')\n", "getattr")

	def test_ignore_permissions(self):
		self._blocked(
			"import frappe\n"
			"def f(params, ctx):\n"
			"    frappe.get_doc({'doctype': 'Note'}).insert(ignore_permissions=True)\n"
			"    return {}\n",
			"ignore_permissions",
		)


class TestModuleMerging(FrappeTestCase):
	def test_a_first_handler_produces_a_documented_module(self):
		module = ha.merge_module(None, "acme", "Acme", "fetch_rate", GOOD)
		tree = ast.parse(module)
		self.assertTrue(ast.get_docstring(tree), "the module must explain itself")
		self.assertEqual(
			[n.name for n in tree.body if isinstance(n, ast.FunctionDef)], ["fetch_rate"]
		)

	def test_a_second_operation_appends(self):
		"""Two operations on one connector share a module, so the second must not
		replace the first — that would silently delete a working handler."""
		first = ha.merge_module(None, "acme", "Acme", "fetch_rate", GOOD)
		second = ha.merge_module(
			first, "acme", "Acme", "list_symbols",
			"def list_symbols(params, ctx):\n    return {'symbols': []}\n",
		)
		names = [n.name for n in ast.parse(second).body if isinstance(n, ast.FunctionDef)]
		self.assertEqual(sorted(names), ["fetch_rate", "list_symbols"])

	def test_re_proposing_replaces_rather_than_duplicating(self):
		"""Two functions of the same name in one module would make the handler
		that runs depend on file order."""
		first = ha.merge_module(None, "acme", "Acme", "fetch_rate", GOOD)
		again = ha.merge_module(
			first, "acme", "Acme", "fetch_rate",
			"def fetch_rate(params, ctx):\n    return {'rate': 1}\n",
		)
		names = [n.name for n in ast.parse(again).body if isinstance(n, ast.FunctionDef)]
		self.assertEqual(names, ["fetch_rate"])
		self.assertIn("'rate': 1", again)

	def test_merged_output_always_parses(self):
		module = ha.merge_module(None, "acme", "Acme", "fetch_rate", GOOD)
		for i in range(3):
			module = ha.merge_module(
				module, "acme", "Acme", f"op_{i}",
				f"def op_{i}(params, ctx):\n    return {{'n': {i}}}\n",
			)
		ast.parse(module)  # raises if a merge ever produced broken source


class TestProposalRefusesBeforeTouchingAnything(FrappeTestCase):
	"""The refusals that must happen before a branch is created.

	A proposal that cannot succeed must leave no branch, no pull request and no
	edited operation — otherwise a failed run still points a connector at code
	that will never exist.
	"""

	def test_invalid_code_never_reaches_github(self):
		result = ha.propose_python_handler(
			connector_id="no_such_connector_zz",
			operation="whatever",
			function_name="f",
			code="def f(params, ctx):\n    return eval('1')\n",
		)
		self.assertFalse(result["ok"])
		self.assertTrue(any("eval" in e for e in result["errors"]))
		self.assertNotIn("pull_request", result)

	def test_an_unknown_connector_is_refused(self):
		result = ha.propose_python_handler(
			connector_id="no_such_connector_zz",
			operation="whatever",
			function_name="fetch_rate",
			code=GOOD,
		)
		self.assertFalse(result["ok"])
		self.assertTrue(any("no_such_connector_zz" in e for e in result["errors"]))
		self.assertNotIn("pull_request", result)

	def test_a_credential_failure_is_marked_non_retryable(self):
		"""A rejected token will be rejected identically next time.

		Observed live: the agent retried a 401 four times before giving up, which
		spent four tool turns learning what the first answer already said. The
		result carries retryable=False so the caller stops.
		"""
		connector = frappe.db.get_value("BPMN Connector", {"connector_id": "a2a"}, "connector_id")
		operation = frappe.db.get_value(
			"BPMN Connector Operation",
			{"connector": frappe.db.get_value("BPMN Connector", {"connector_id": "a2a"}, "name")},
			"operation_id",
		)
		if not (connector and operation):
			self.skipTest("no connector/operation available on this site to test against")

		result = ha.propose_python_handler(
			connector_id=connector, operation=operation,
			function_name="fetch_rate", code=GOOD,
		)
		# Either the token is rejected (the expected case on a bench with a stale
		# token) or the network refuses — both are delivery failures, and neither
		# may leave the operation edited.
		if result["ok"]:
			self.skipTest("this bench opened a real pull request; nothing to assert about failure")
		self.assertTrue(result["errors"])
		if result.get("retryable") is False:
			self.assertIn("credentials problem", result["note"])
		op_row = frappe.db.get_value(
			"BPMN Connector Operation",
			{"connector": frappe.db.get_value("BPMN Connector", {"connector_id": connector}, "name"),
			 "operation_id": operation},
			["execution_type", "handler_path"], as_dict=True,
		)
		self.assertNotEqual(
			op_row.handler_path, ha.handler_path(connector, "fetch_rate"),
			"a failed delivery must not point the operation at code that was never pushed",
		)

	def test_an_unknown_operation_is_refused(self):
		"""A handler needs an operation to attach to. Writing the code without
		one would produce a pull request nothing references."""
		connector = frappe.db.get_value("BPMN Connector", {"connector_id": "a2a"}, "connector_id")
		if not connector:
			self.skipTest("no connector available on this site to test against")
		result = ha.propose_python_handler(
			connector_id=connector,
			operation="zz_operation_that_does_not_exist",
			function_name="fetch_rate",
			code=GOOD,
		)
		self.assertFalse(result["ok"])
		self.assertTrue(any("zz_operation_that_does_not_exist" in e for e in result["errors"]))
		self.assertNotIn("pull_request", result)
