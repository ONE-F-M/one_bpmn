# Copyright (c) 2026, one-fm and contributors
"""
Tests for the Connector Agent — run against the code that actually ships.

The agent's rules live in its Server Scripts, not in the codebase: only
``connectors/agent_primitives.fetch_url`` stayed in Python, because the script
gate forbids ``requests`` and there is no adequate alternative for a capped,
timed, SSRF-guarded fetch of an attacker-influenced URL.

So these tests load the helpers back OUT of the installed Server Scripts and
exercise them directly. That is deliberate: it tests the deployed source rather
than a copy, and it fails if the inlined code stops being importable — which is
how a mistake in the split-namespace layout would otherwise first appear, halfway
through a live turn.

The load-bearing test is still TestReviewerImporterAgreement. The agent's whole
loop depends on review and write agreeing about what a valid manifest looks like:
a draft that passes review and then fails to import is a reviewer that lies, and
an agent told "approved" and then handed an error re-drafts a perfectly good
connector until its tool budget runs out.
"""

import ast
import json
from types import SimpleNamespace

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.connectors.manifest import clear_manifest_cache
from one_bpmn.one_bpmn.connectors.seed import export_manifest, import_manifest


def _relocated(tool: str) -> SimpleNamespace:
    """Reconstruct one tool script's inlined helpers into a callable namespace.

    The helpers sit inside a single outer ``def _main(...)`` because shape tools
    exec with split globals and locals. Re-executing that function's imports,
    constants and nested defs in a fresh namespace gives the tests the same
    functions the tool runs, from the same source.
    """
    body = frappe.db.get_value("Server Script", f"Connector Agent: Tool {tool}", "script")
    if not body:
        raise AssertionError(f"'Connector Agent: Tool {tool}' is not installed")
    tree = ast.parse(body)
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_main")

    def is_const(node):
        return isinstance(node, ast.Assign) and all(
            isinstance(t, ast.Name) and t.id.lstrip("_").isupper() for t in node.targets
        )

    keep = [n for n in main.body
            if isinstance(n, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef))
            or is_const(n)]
    mod = ast.Module(body=keep, type_ignores=[])
    ns = {"frappe": frappe, "__name__": "connector_agent_relocated"}
    exec(compile(ast.fix_missing_locations(mod), "<relocated>", "exec"), ns)  # noqa: S102
    ns.pop("__builtins__", None)
    return SimpleNamespace(**ns)


A = _relocated("Read API Reference")      # _parse_spec, _strip_markup, summarize_openapi
D = _relocated("Draft Connector")         # openapi_to_manifest and its helpers
R = _relocated("Review Connector")        # validate_manifest and its validators
W = _relocated("Write Connector")         # write_draft_connector
T = _relocated("Test Operation")          # try_operation


def draft_from(spec, connector_id, **kw):
    """Summarise then draft.

    ``openapi_to_manifest`` used to summarise the spec itself. It now takes the
    summary, because read_api_docs already stores one and recomputing it would
    have dragged the whole summarise cluster into a second script.
    """
    summary = A.summarize_openapi(spec, max_operations=1000)
    return D.openapi_to_manifest(summary, connector_id, **kw)

SOURCE = "https://api.example.com/openapi.json"

# A small but realistic spec: a path parameter, a query enum, a JSON body, an
# apiKey header scheme, and a property named `values` (which shadows a dict
# method and must be renamed).
SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Helpdesk API", "version": "2.1", "description": "Tickets."},
    "servers": [{"url": "https://api.example.com/v2"}],
    "components": {
        "securitySchemes": {"key": {"type": "apiKey", "in": "header", "name": "X-Api-Key"}}
    },
    "paths": {
        "/tickets": {
            "post": {
                "operationId": "createTicket",
                "summary": "Create a ticket",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["subject"],
                                "properties": {
                                    "subject": {"type": "string", "description": "Summary"},
                                    "priority": {"type": "string", "enum": ["low", "high"]},
                                    "values": {"type": "string"},
                                },
                            }
                        }
                    }
                },
            },
            "get": {
                "operationId": "listTickets",
                "summary": "List tickets",
                "parameters": [
                    {"name": "status", "in": "query", "schema": {"type": "string", "enum": ["open"]}}
                ],
            },
        },
        "/tickets/{ticketId}": {
            "get": {
                "operationId": "getTicket",
                "summary": "Fetch one ticket",
                "parameters": [
                    {
                        "name": "ticketId",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
            }
        },
    },
}


def _cleanup(connector_id):
    for name in frappe.get_all(
        "BPMN Connector Operation", filters={"connector": connector_id}, pluck="name"
    ):
        frappe.delete_doc("BPMN Connector Operation", name, force=True, ignore_permissions=True)
    if frappe.db.exists("BPMN Connector", connector_id):
        frappe.delete_doc("BPMN Connector", connector_id, force=True, ignore_permissions=True)
    clear_manifest_cache()


class TestSpecSummary(FrappeTestCase):
    def test_summarizes_servers_auth_and_operations(self):
        s = A.summarize_openapi(SPEC)
        self.assertEqual(s["title"], "Helpdesk API")
        self.assertEqual(s["servers"], ["https://api.example.com/v2"])
        self.assertEqual(s["operation_count_total"], 3)
        self.assertEqual(s["security_schemes"][0]["auth_type"], "API Key Header")
        self.assertEqual(s["security_schemes"][0]["header_name"], "X-Api-Key")

    def test_path_parameter_is_marked_required(self):
        s = A.summarize_openapi(SPEC)
        get_one = next(o for o in s["operations"] if o["path"] == "/tickets/{ticketId}")
        self.assertEqual(get_one["parameters"][0]["name"], "ticketId")
        self.assertTrue(get_one["parameters"][0]["required"])

    def test_swagger_2_host_becomes_a_server(self):
        s = A.summarize_openapi(
            {"swagger": "2.0", "host": "api.old.com", "basePath": "/v1", "paths": {}}
        )
        self.assertEqual(s["servers"], ["https://api.old.com/v1"])

    def test_local_refs_are_resolved(self):
        spec = {
            "openapi": "3.0.0",
            "components": {
                "parameters": {
                    "Page": {"name": "page", "in": "query", "schema": {"type": "integer"}}
                }
            },
            "paths": {"/x": {"get": {"parameters": [{"$ref": "#/components/parameters/Page"}]}}},
        }
        s = A.summarize_openapi(spec)
        self.assertEqual(s["operations"][0]["parameters"][0]["name"], "page")

    def test_html_page_is_not_mistaken_for_a_spec(self):
        self.assertIsNone(A._parse_spec("<html><body>docs</body></html>"))
        self.assertIsNone(A._parse_spec('{"info": {}}'))  # no paths
        self.assertIsNotNone(A._parse_spec('{"paths": {}}'))

    def test_markup_is_stripped_to_readable_text(self):
        text = A._strip_markup(
            "<nav>menu</nav><h1>Rates</h1><script>x()</script><p>GET /rates &amp; more</p>"
        )
        self.assertNotIn("menu", text)
        self.assertNotIn("x()", text)
        self.assertIn("GET /rates & more", text)


class TestDeterministicDraft(FrappeTestCase):
    def test_path_parameter_becomes_a_required_field_the_url_references(self):
        m = draft_from(SPEC, "helpdesk", operations=["getTicket"])
        op = m["operations"][0]
        self.assertEqual(op["http"]["url"], "/tickets/{{ params.ticketId }}")
        self.assertEqual(op["fields"][0]["name"], "ticketId")
        self.assertTrue(op["fields"][0]["required"])

    def test_enum_becomes_a_dropdown_with_choices(self):
        m = draft_from(SPEC, "helpdesk", operations=["createTicket"])
        priority = next(f for f in m["operations"][0]["fields"] if f["name"] == "priority")
        self.assertEqual(priority["type"], "Dropdown")
        self.assertEqual([c["value"] for c in priority["choices"]], ["low", "high"])

    def test_dict_method_shadowing_name_is_renamed(self):
        # `params.values` resolves to the dict METHOD, not the field — the single
        # most expensive mistake this configuration format allows.
        m = draft_from(SPEC, "helpdesk", operations=["createTicket"])
        names = [f["name"] for f in m["operations"][0]["fields"]]
        self.assertIn("values_", names)
        self.assertNotIn("values", names)
        self.assertIn("params.values_", m["operations"][0]["http"]["body"])

    def test_auth_scheme_maps_onto_the_connector_enum(self):
        m = draft_from(SPEC, "helpdesk", operations=["getTicket"])
        auth = m["execution"]["auth"]
        self.assertEqual(auth["type"], "API Key Header")
        self.assertEqual(auth["headerName"], "X-Api-Key")
        self.assertNotIn("secret", auth)

    def test_unknown_operation_is_refused_rather_than_guessed(self):
        with self.assertRaises(D.ConnectorAuthoringError):
            draft_from(SPEC, "helpdesk", operations=["deleteEverything"])

    def test_relative_server_url_is_resolved_against_the_spec_url(self):
        spec = dict(SPEC, servers=[{"url": "/api/v3"}])
        m = draft_from(
            spec, "helpdesk", operations=["getTicket"], source_url=SOURCE
        )
        self.assertEqual(m["execution"]["baseUrl"], "https://api.example.com/api/v3")

    def test_relative_server_url_with_nothing_to_resolve_against_is_an_error(self):
        spec = dict(SPEC, servers=[{"url": "/api/v3"}])
        with self.assertRaises(D.ConnectorAuthoringError):
            draft_from(spec, "helpdesk", operations=["getTicket"])


class TestDraftReview(FrappeTestCase):
    def test_a_generated_draft_reviews_clean(self):
        m = draft_from(
            SPEC, "helpdesk", operations=["createTicket", "getTicket", "listTickets"]
        )
        self.assertEqual(R.validate_manifest(m), [])

    def test_template_referencing_an_undeclared_field_is_caught(self):
        draft = _minimal_draft()
        draft["operations"][0]["http"]["body"] = '{"subject": "{{ params.nope }}"}'
        issues = R.validate_manifest(draft)
        self.assertTrue(any("params.nope" in i and "no field named" in i for i in issues))

    def test_declared_but_unused_field_is_caught(self):
        draft = _minimal_draft()
        draft["operations"][0]["fields"].append(
            {"name": "orphan", "label": "Orphan", "type": "String"}
        )
        issues = R.validate_manifest(draft)
        self.assertTrue(any("orphan" in i and "no template uses it" in i for i in issues))

    def test_shadowed_dot_access_is_called_out_specifically(self):
        draft = _minimal_draft()
        draft["operations"][0]["fields"] = [{"name": "values", "label": "V", "type": "String"}]
        draft["operations"][0]["http"]["body"] = '{"v": "{{ params.values }}"}'
        issues = R.validate_manifest(draft)
        self.assertTrue(any("resolves to the dict" in i for i in issues))

    def test_secret_in_a_manifest_is_refused(self):
        draft = _minimal_draft()
        draft["execution"]["auth"] = {"type": "Bearer Token", "secret": "sk_live_oops"}
        issues = R.validate_manifest(draft)
        self.assertTrue(any("must not carry a secret" in i for i in issues))

    def test_bad_connector_id_is_refused(self):
        draft = _minimal_draft()
        draft["connectorId"] = "Not-Valid"
        self.assertTrue(any("connectorId" in i for i in R.validate_manifest(draft)))

    def test_relative_url_without_base_url_is_caught(self):
        draft = _minimal_draft()
        draft["execution"].pop("baseUrl")
        issues = R.validate_manifest(draft)
        self.assertTrue(any("no Base URL" in i for i in issues))

    def test_body_that_stops_being_json_is_caught(self):
        draft = _minimal_draft()
        draft["operations"][0]["http"]["body"] = '{"subject": "{{ params.subject }}",}'
        issues = R.validate_manifest(draft)
        self.assertTrue(any("does not parse as JSON" in i for i in issues))

    def test_get_with_a_body_is_caught(self):
        draft = _minimal_draft()
        draft["operations"][0]["http"]["method"] = "GET"
        issues = R.validate_manifest(draft)
        self.assertTrue(any("request body" in i for i in issues))

    def test_bad_response_map_path_is_caught(self):
        draft = _minimal_draft()
        draft["operations"][0]["http"]["responseMap"] = {"id": "data..id"}
        issues = R.validate_manifest(draft)
        self.assertTrue(any("not a dotted path" in i for i in issues))

    def test_none_literal_expression_is_caught(self):
        draft = _minimal_draft()
        draft["operations"][0]["http"]["body"] = (
            '{"subject": "{{ params.subject }}", "note": "{{ doc.note }}"}'
        )
        issues = R.validate_manifest(draft)
        self.assertTrue(any("renders the literal 'None'" in i for i in issues))

    def test_http_operation_with_no_http_block_is_caught(self):
        draft = _minimal_draft()
        draft["operations"][0].pop("http")
        issues = R.validate_manifest(draft)
        self.assertTrue(any("http.method and http.url" in i for i in issues))

    def test_python_handler_without_a_path_is_caught(self):
        draft = _minimal_draft()
        draft["operations"][0]["executionType"] = "Python Handler"
        draft["operations"][0].pop("http")
        issues = R.validate_manifest(draft)
        self.assertTrue(any("no handler path" in i for i in issues))

    def test_not_json_at_all(self):
        self.assertTrue(R.validate_manifest("{oops"))
        self.assertTrue(R.validate_manifest([1, 2]))


class TestReviewerImporterAgreement(FrappeTestCase):
    """A draft the reviewer approves MUST import, and survive a round trip.

    This is the invariant the agent's loop rests on. See the module docstring.
    """

    def tearDown(self):
        _cleanup("helpdesk_agree")

    def test_approved_draft_imports_and_round_trips(self):
        _cleanup("helpdesk_agree")
        draft = draft_from(
            SPEC, "helpdesk_agree", operations=["createTicket", "getTicket", "listTickets"]
        )
        self.assertEqual(R.validate_manifest(draft), [], "reviewer must approve")

        import_manifest(draft, overwrite=True)

        exported = export_manifest("helpdesk_agree")
        self.assertEqual(
            [o["value"] for o in exported["operations"]],
            [o["value"] for o in draft["operations"]],
        )
        # The exported form must ALSO review clean, or the two spellings have
        # drifted again in the other direction.
        self.assertEqual(R.validate_manifest(exported), [])

    def test_every_generated_operation_reaches_the_database_executable(self):
        _cleanup("helpdesk_agree")
        draft = draft_from(
            SPEC, "helpdesk_agree", operations=["createTicket", "getTicket"]
        )
        import_manifest(draft, overwrite=True)
        for op in draft["operations"]:
            row = frappe.db.get_value(
                "BPMN Connector Operation",
                {"connector": "helpdesk_agree", "operation_id": op["value"]},
                ["http_method", "url_template"],
                as_dict=True,
            )
            self.assertTrue(row, f"{op['value']} did not import")
            self.assertEqual(row.http_method, op["http"]["method"])
            self.assertEqual(row.url_template, op["http"]["url"])


class TestWriteDisabled(FrappeTestCase):
    def tearDown(self):
        _cleanup("helpdesk_write")

    def test_written_connector_is_disabled_and_unusable_until_enabled(self):
        _cleanup("helpdesk_write")
        draft = draft_from(SPEC, "helpdesk_write", operations=["getTicket"])
        out = W.write_draft_connector(draft)

        self.assertTrue(out["written"])
        self.assertFalse(out["enabled"])
        self.assertEqual(frappe.db.get_value("BPMN Connector", "helpdesk_write", "enabled"), 0)

        from one_bpmn.one_bpmn.connectors.api import get_connector_manifests
        from one_bpmn.one_bpmn.connectors.manifest import get_execution_spec

        offered = [m["connectorId"] for m in get_connector_manifests()]
        self.assertNotIn("helpdesk_write", offered, "a disabled draft must not reach the modeler")
        self.assertIsNone(
            get_execution_spec("helpdesk_write", "getTicket"),
            "dispatch must refuse a disabled connector",
        )
        # ...but authoring may still resolve it, which is how test_operation
        # verifies a draft before a person enables it.
        self.assertIsNotNone(
            get_execution_spec("helpdesk_write", "getTicket", allow_disabled=True)
        )

    def test_the_importer_still_refuses_a_draft_the_reviewer_would_have_caught(self):
        """write_draft_connector no longer re-validates — the tool gates on the
        recorded review verdict instead, so there is one validator, not two. The
        importer is the backstop, and it must still refuse rather than write."""
        _cleanup("helpdesk_write")
        draft = draft_from(SPEC, "helpdesk_write", operations=["getTicket"])
        draft["operations"][0]["http"]["url"] = ""
        self.assertTrue(R.validate_manifest(draft), "the reviewer should catch this")
        out = W.write_draft_connector(draft)
        self.assertFalse(out["written"])
        self.assertTrue(out["issues"])
        self.assertFalse(frappe.db.exists("BPMN Connector", "helpdesk_write"))

    def test_existing_connector_is_not_replaced_without_overwrite(self):
        _cleanup("helpdesk_write")
        draft = draft_from(SPEC, "helpdesk_write", operations=["getTicket"])
        self.assertTrue(W.write_draft_connector(draft)["written"])

        again = W.write_draft_connector(draft)
        self.assertFalse(again["written"])
        self.assertTrue(any("already exists" in i for i in again["issues"]))
        self.assertTrue(W.write_draft_connector(draft, overwrite=True)["written"])


class TestTryOperation(FrappeTestCase):
    """Note the exception class comes from T, not D: each tool script defines its
    own ConnectorAuthoringError now that the code is inlined per script. The tool
    bodies catch bare Exception, so this only ever matters to a test."""
    def tearDown(self):
        _cleanup("helpdesk_try")

    def test_unknown_operation_is_reported_not_raised_as_a_mystery(self):
        with self.assertRaises(T.ConnectorAuthoringError):
            T.try_operation("no_such_connector", "nope")

    def test_missing_required_test_input_is_named(self):
        _cleanup("helpdesk_try")
        draft = draft_from(SPEC, "helpdesk_try", operations=["getTicket"])
        W.write_draft_connector(draft)
        with self.assertRaises(T.ConnectorAuthoringError) as caught:
            T.try_operation("helpdesk_try", "getTicket", {})
        self.assertIn("ticketId", str(caught.exception))

    def test_bad_json_test_inputs_are_reported(self):
        with self.assertRaises(T.ConnectorAuthoringError):
            T.try_operation("helpdesk_try", "getTicket", "{not json")


def _minimal_draft():
    """A hand-written draft in the importer's dialect, for negative tests."""
    return {
        "connectorId": "helpdesk_neg",
        "label": "Helpdesk",
        "execution": {
            "type": "HTTP Request",
            "baseUrl": "https://api.example.com/v2",
            "auth": {"type": "None"},
        },
        "operations": [
            {
                "value": "createTicket",
                "label": "Create ticket",
                "executionType": "HTTP Request",
                "http": {
                    "method": "POST",
                    "url": "/tickets",
                    "contentType": "application/json",
                    "body": '{"subject": "{{ params.subject }}"}',
                },
                "fields": [
                    {"name": "subject", "label": "Subject", "type": "String", "required": True}
                ],
            }
        ],
    }


# ── handler authoring ────────────────────────────────────────────────────────
# Same posture: the screening, validation, module rendering and pull-request
# wording all moved into the propose_python_handler tool script, so they are
# loaded back out of it and exercised directly.

H = _relocated("Propose Python Handler")

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
			H.handler_path("Acme CRM", "fetch_rate"),
			"one_bpmn.one_bpmn.connectors.generated.acme_crm_ops.fetch_rate",
		)
		self.assertEqual(
			H.repo_path("Acme CRM"),
			"one_bpmn/one_bpmn/connectors/generated/acme_crm_ops.py",
		)

	def test_the_generated_package_is_importable(self):
		"""A handler is resolved with frappe.get_attr, which imports the package."""
		import importlib

		self.assertTrue(importlib.import_module(H.dotted_module("x").rsplit(".", 1)[0]))

	def test_the_file_path_and_the_dotted_module_agree(self):
		"""Written somewhere it cannot be imported from is the one failure mode
		that produces a green pull request and a dead connector."""
		for app in (None, "one_bpmn"):
			path = H.repo_path("Acme CRM", app)
			dotted = H.dotted_module("Acme CRM", app)
			# The repo-relative path already starts at the package directory, so
			# the whole thing converts — nothing is stripped.
			from_path = path.replace("/", ".")[: -len(".py")]
			self.assertEqual(from_path, dotted, f"path and module disagree for app={app!r}")

	def test_the_configured_app_decides_the_repository(self):
		"""The app is a setting, not a constant — a fork or a move must not need a
		code change — and blank means switched off rather than 'guess'."""
		self.assertEqual(H.handler_app(), "one_bpmn")
		previous = frappe.db.get_single_value("Processa Settings", "connector_handler_app")
		try:
			frappe.db.set_single_value("Processa Settings", "connector_handler_app", "")
			frappe.clear_cache(doctype="Processa Settings")
			self.assertEqual(H.handler_app(), "", "blank must mean 'switched off'")
			result = H.propose_python_handler(
				connector_id="anything", operation="op", function_name="fetch_rate", code=GOOD,
			)
			self.assertFalse(result["ok"])
			self.assertIn("switched off", result["errors"][0])
			self.assertIs(result.get("retryable"), False)
		finally:
			frappe.db.set_single_value("Processa Settings", "connector_handler_app", previous)
			frappe.clear_cache(doctype="Processa Settings")


class TestHandlerValidation(FrappeTestCase):
	def test_a_usable_handler_passes(self):
		self.assertEqual(H.validate_handler(GOOD, "fetch_rate"),
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
		self.assertTrue(H.validate_handler(code, "f")["ok"])

	def test_signature_must_be_params_ctx(self):
		result = H.validate_handler("def f(a, b):\n    return {}\n", "f")
		self.assertFalse(result["ok"])
		self.assertIn("must take exactly", result["errors"][0])

	def test_async_is_refused(self):
		result = H.validate_handler("async def f(params, ctx):\n    return {}\n", "f")
		self.assertFalse(result["ok"])
		self.assertIn("async", result["errors"][0])

	def test_the_named_function_must_be_defined(self):
		result = H.validate_handler("def other(params, ctx):\n    return {}\n", "f")
		self.assertFalse(result["ok"])
		self.assertIn("not 'f'", result["errors"][0])

	def test_no_return_is_a_warning_not_an_error(self):
		"""It is legal and occasionally intended, but the output variable will be
		empty — which is the kind of thing a reviewer wants told to them."""
		result = H.validate_handler("def f(params, ctx):\n    pass\n", "f")
		self.assertTrue(result["ok"])
		self.assertTrue(result["warnings"])

	def test_unparseable_code_is_reported_not_raised(self):
		result = H.validate_handler("def f(params, ctx)\n    return {}\n", "f")
		self.assertFalse(result["ok"])
		self.assertIn("does not parse", result["errors"][0])


class TestMaliciousConstructScreen(FrappeTestCase):
	"""Each of these must be refused. The screen is narrow on purpose, so the
	list it does cover has to actually hold."""

	def _blocked(self, code, needle):
		result = H.validate_handler(code, "f")
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
		module = H.merge_module(None, "acme", "Acme", "fetch_rate", GOOD)
		tree = ast.parse(module)
		self.assertTrue(ast.get_docstring(tree), "the module must explain itself")
		self.assertEqual(
			[n.name for n in tree.body if isinstance(n, ast.FunctionDef)], ["fetch_rate"]
		)

	def test_a_second_operation_appends(self):
		"""Two operations on one connector share a module, so the second must not
		replace the first — that would silently delete a working handler."""
		first = H.merge_module(None, "acme", "Acme", "fetch_rate", GOOD)
		second = H.merge_module(
			first, "acme", "Acme", "list_symbols",
			"def list_symbols(params, ctx):\n    return {'symbols': []}\n",
		)
		names = [n.name for n in ast.parse(second).body if isinstance(n, ast.FunctionDef)]
		self.assertEqual(sorted(names), ["fetch_rate", "list_symbols"])

	def test_re_proposing_replaces_rather_than_duplicating(self):
		"""Two functions of the same name in one module would make the handler
		that runs depend on file order."""
		first = H.merge_module(None, "acme", "Acme", "fetch_rate", GOOD)
		again = H.merge_module(
			first, "acme", "Acme", "fetch_rate",
			"def fetch_rate(params, ctx):\n    return {'rate': 1}\n",
		)
		names = [n.name for n in ast.parse(again).body if isinstance(n, ast.FunctionDef)]
		self.assertEqual(names, ["fetch_rate"])
		self.assertIn("'rate': 1", again)

	def test_merged_output_always_parses(self):
		module = H.merge_module(None, "acme", "Acme", "fetch_rate", GOOD)
		for i in range(3):
			module = H.merge_module(
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
		result = H.propose_python_handler(
			connector_id="no_such_connector_zz",
			operation="whatever",
			function_name="f",
			code="def f(params, ctx):\n    return eval('1')\n",
		)
		self.assertFalse(result["ok"])
		self.assertTrue(any("eval" in e for e in result["errors"]))
		self.assertNotIn("pull_request", result)

	def test_an_unknown_connector_is_refused(self):
		result = H.propose_python_handler(
			connector_id="no_such_connector_zz",
			operation="whatever",
			function_name="fetch_rate",
			code=GOOD,
		)
		self.assertFalse(result["ok"])
		self.assertTrue(any("no_such_connector_zz" in e for e in result["errors"]))
		self.assertNotIn("pull_request", result)

	def test_a_credential_failure_is_classified_as_permanent(self):
		"""A rejected token will be rejected identically next time.

		Observed live: the agent retried a 401 four times before giving up, which
		spent four tool turns learning what the first answer already said.

		Deliberately tests the CLASSIFIER and not a real delivery. An earlier
		version of this test called propose_python_handler against the live `a2a`
		connector, which was harmless only while the bench token was dead — with a
		working token it would open a real pull request, repoint a real operation
		at a handler that does not exist yet, and disable the connector that every
		A2A delegation on the site depends on. A test must not be one credential
		renewal away from breaking production.
		"""
		for permanent in (
			"GitHub API error (401) on /repos/ONE-F-M/one_bpmn: Bad credentials",
			"GitHub API error (403) on /repos/ONE-F-M/one_bpmn: Forbidden",
			"GitHub Access Token is not configured in Processa Settings.",
		):
			self.assertTrue(
				H.is_permanent_delivery_failure(permanent),
				f"should be permanent: {permanent!r}",
			)

		for transient in (
			"('Connection aborted.', RemoteDisconnected('Remote end closed connection'))",
			"GitHub API error (502) on /repos/ONE-F-M/one_bpmn: Bad gateway",
			"HTTPSConnectionPool(host='api.github.com', port=443): Read timed out.",
		):
			self.assertFalse(
				H.is_permanent_delivery_failure(transient),
				f"should be worth retrying: {transient!r}",
			)

	def test_an_unknown_operation_is_refused(self):
		"""A handler needs an operation to attach to. Writing the code without
		one would produce a pull request nothing references."""
		connector = frappe.db.get_value("BPMN Connector", {"connector_id": "a2a"}, "connector_id")
		if not connector:
			self.skipTest("no connector available on this site to test against")
		result = H.propose_python_handler(
			connector_id=connector,
			operation="zz_operation_that_does_not_exist",
			function_name="fetch_rate",
			code=GOOD,
		)
		self.assertFalse(result["ok"])
		self.assertTrue(any("zz_operation_that_does_not_exist" in e for e in result["errors"]))
		self.assertNotIn("pull_request", result)


class TestBaseBranchResolution(FrappeTestCase):
	"""Which branch a generated handler's pull request targets.

	Left to itself ``github_sync`` targets the repository's default branch, which on
	one_bpmn is ``version-15``. That put generated handlers on a different route to
	production than every hand-written change, which branches off staging. These
	tests pin the preference AND its fallback — the receiving repo is configurable,
	so "there is no staging branch" has to stay a supported answer rather than a
	failed pull request.

	The probe is stubbed throughout: resolution must be decidable without a token
	or a network, which is the whole reason it is a separate function.
	"""

	def _with_probe(self, probe):
		from one_bpmn.api import github_sync

		original = github_sync.branch_exists
		github_sync.branch_exists = probe
		self.addCleanup(lambda: setattr(github_sync, "branch_exists", original))

	def test_staging_is_preferred_when_the_repo_has_one(self):
		seen = {}

		def probe(*, token, repo, branch):
			seen.update(repo=repo, branch=branch)
			return True

		self._with_probe(probe)
		self.assertEqual(H.resolve_base_branch("ONE-F-M/one_bpmn", "tok"), "staging")
		self.assertEqual(seen["branch"], "staging")
		self.assertEqual(seen["repo"], "ONE-F-M/one_bpmn")

	def test_falls_back_to_the_repo_default_when_staging_is_absent(self):
		"""None is not a failure — it means "you choose", and github_sync then
		uses the default branch, the only one guaranteed to exist."""
		self._with_probe(lambda *, token, repo, branch: False)
		self.assertIsNone(H.resolve_base_branch("someone/no-staging-here", "tok"))

	def test_a_broken_probe_does_not_block_delivery(self):
		"""A rate limit or a dead network must cost us the nicer base branch, not
		the handler. Anything else would make delivery less reliable than before
		the preference existed."""

		def probe(*, token, repo, branch):
			raise RuntimeError("GitHub API error (403): rate limited")

		self._with_probe(probe)
		self.assertIsNone(H.resolve_base_branch("ONE-F-M/one_bpmn", "tok"))

	def test_an_explicit_base_branch_is_never_overridden(self):
		"""A caller that names a base means it; the preference only fills a blank."""

		def probe(*, token, repo, branch):
			raise AssertionError("the probe must not run when a base was given")

		self._with_probe(probe)
		result = H.propose_python_handler(
			connector_id="no-such-connector-for-base-test",
			operation="anything",
			function_name="anything",
			code=GOOD,
			base_branch="release-1.2",
		)
		# Refused at the connector gate, long before any branch resolution — which
		# is exactly the point: the probe never ran.
		self.assertTrue(result["errors"])


# ── the tool bodies themselves ───────────────────────────────────────────────
class TestToolBodiesRun(FrappeTestCase):
    """Execute each tool script the way a shape tool does.

    The unit tests above call the relocated helpers directly, which is where the
    logic is — but it means the tool BODY around them is never executed. That gap
    let a real bug ship: the review tool fingerprinted its draft with
    ``frappe.utils.md5``, which does not exist. Syntax, the security gate and a
    static name check all passed it, because none of them resolve an attribute on
    a module. Running the body does.
    """

    TURN = "_test_connector_tool_bodies"

    def _run(self, tool, task_data=None):
        from one_bpmn.agents.turn_state import get_turn

        body = frappe.db.get_value("Server Script", f"Connector Agent: Tool {tool}", "script")
        self.assertTrue(body, f"'Connector Agent: Tool {tool}' is not installed")
        result = {}
        local_vars = dict(task_data or {})
        local_vars.update({
            "frappe": frappe, "result": result, "task_data": dict(task_data or {}),
            "context_doctype": "A2A Task", "context_docname": self.TURN,
            "doc": frappe._dict(), "instance": None, "bpmn_id": "", "shape_config": {},
            "ai_agent_config": "",
        })
        exec(body, {"frappe": frappe, "__builtins__": __builtins__}, local_vars)  # noqa: S102
        _ = get_turn
        return result

    def setUp(self):
        from one_bpmn.agents.turn_state import set_turn

        set_turn(self.TURN, {"work_order": "test", "a2a_task": self.TURN})
        _cleanup("tool_body_probe")

    def tearDown(self):
        from one_bpmn.agents.turn_state import clear_turn

        clear_turn(self.TURN)
        _cleanup("tool_body_probe")

    def test_review_runs_and_approves_a_generated_draft(self):
        from one_bpmn.agents.turn_state import set_turn

        set_turn(self.TURN, {"draft": draft_from(SPEC, "tool_body_probe", operations=["getTicket"])})
        out = self._run("Review Connector")
        self.assertTrue(out["approved"], out.get("issues"))
        self.assertEqual(out["issue_count"], 0)

    def test_review_reports_issues_rather_than_raising(self):
        from one_bpmn.agents.turn_state import set_turn

        bad = draft_from(SPEC, "tool_body_probe", operations=["getTicket"])
        bad["operations"][0]["http"]["url"] = ""
        set_turn(self.TURN, {"draft": bad})
        out = self._run("Review Connector")
        self.assertFalse(out["approved"])
        self.assertTrue(out["issues"])

    def test_write_refuses_a_draft_whose_review_found_issues(self):
        from one_bpmn.agents.turn_state import set_turn

        bad = draft_from(SPEC, "tool_body_probe", operations=["getTicket"])
        bad["operations"][0]["http"]["url"] = ""
        set_turn(self.TURN, {"draft": bad})
        self._run("Review Connector")
        out = self._run("Write Connector")
        self.assertIn("issue", out["error"])
        self.assertFalse(frappe.db.exists("BPMN Connector", "tool_body_probe"))

    def test_write_refuses_a_draft_changed_after_a_clean_review(self):
        """The hole this fingerprint closes: review clean, redraft, then write."""
        from one_bpmn.agents.turn_state import get_turn, set_turn, update_turn

        good = draft_from(SPEC, "tool_body_probe", operations=["getTicket"])
        set_turn(self.TURN, {"draft": good})
        self.assertTrue(self._run("Review Connector")["approved"])

        swapped = draft_from(SPEC, "tool_body_probe", operations=["createTicket"])
        update_turn(self.TURN, draft=swapped)
        out = self._run("Write Connector")
        self.assertIn("changed after it was reviewed", out["error"])
        self.assertFalse(frappe.db.exists("BPMN Connector", "tool_body_probe"))
        _ = get_turn

    def test_write_writes_a_reviewed_draft_disabled(self):
        from one_bpmn.agents.turn_state import set_turn

        set_turn(self.TURN, {"draft": draft_from(SPEC, "tool_body_probe", operations=["getTicket"])})
        self.assertTrue(self._run("Review Connector")["approved"])
        out = self._run("Write Connector")
        self.assertTrue(out.get("written"), out.get("error") or out.get("issues"))
        self.assertEqual(frappe.db.get_value("BPMN Connector", "tool_body_probe", "enabled"), 0)

    def test_draft_needs_a_connector_id(self):
        self.assertIn("connector_id is required", self._run("Draft Connector")["error"])

    def test_draft_builds_from_a_stored_spec_summary(self):
        from one_bpmn.agents.turn_state import set_turn

        set_turn(self.TURN, {"spec_summary": A.summarize_openapi(SPEC, max_operations=1000),
                             "reference_url": SOURCE})
        out = self._run("Draft Connector", {"connector_id": "tool_body_probe",
                                            "operations": ["getTicket"]})
        self.assertEqual(out.get("source"), "openapi")
        self.assertTrue(out.get("operations"))

    def test_read_api_docs_needs_a_url(self):
        self.assertIn("No url", self._run("Read API Reference")["error"])

    def test_test_operation_needs_a_written_connector(self):
        self.assertIn("Write the connector first", self._run("Test Operation")["error"])

    def test_propose_handler_refuses_before_touching_anything(self):
        out = self._run("Propose Python Handler", {"connector_id": "tool_body_probe",
                                                   "operation": "getTicket",
                                                   "function_name": "get_ticket",
                                                   "code": ""})
        self.assertIn("code is required", out["error"])
