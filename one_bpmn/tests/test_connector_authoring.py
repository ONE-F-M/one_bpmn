# Copyright (c) 2026, one-fm and contributors
# Tests for the Connector Agent's authoring library: reading a
# provider's spec, building a connector manifest mechanically, reviewing a draft
# before it is written, and writing it disabled.
#
# The load-bearing test is TestReviewerImporterAgreement. The agent's whole loop
# depends on review and write agreeing about what a valid manifest looks like: a
# draft that passes review and then fails to import is a reviewer that lies, and
# an agent told "approved" and then handed an error has nothing to act on — it
# re-drafts a perfectly good connector until its tool budget runs out. That
# happened during development (the first version invented an "execution" block
# per operation where the importer reads a nested "http" one), so the invariant
# is pinned here rather than left to be rediscovered.

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.connectors import authoring
from one_bpmn.one_bpmn.connectors.manifest import clear_manifest_cache
from one_bpmn.one_bpmn.connectors.seed import export_manifest, import_manifest

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
        s = authoring.summarize_openapi(SPEC)
        self.assertEqual(s["title"], "Helpdesk API")
        self.assertEqual(s["servers"], ["https://api.example.com/v2"])
        self.assertEqual(s["operation_count_total"], 3)
        self.assertEqual(s["security_schemes"][0]["auth_type"], "API Key Header")
        self.assertEqual(s["security_schemes"][0]["header_name"], "X-Api-Key")

    def test_path_parameter_is_marked_required(self):
        s = authoring.summarize_openapi(SPEC)
        get_one = next(o for o in s["operations"] if o["path"] == "/tickets/{ticketId}")
        self.assertEqual(get_one["parameters"][0]["name"], "ticketId")
        self.assertTrue(get_one["parameters"][0]["required"])

    def test_swagger_2_host_becomes_a_server(self):
        s = authoring.summarize_openapi(
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
        s = authoring.summarize_openapi(spec)
        self.assertEqual(s["operations"][0]["parameters"][0]["name"], "page")

    def test_html_page_is_not_mistaken_for_a_spec(self):
        self.assertIsNone(authoring._parse_spec("<html><body>docs</body></html>"))
        self.assertIsNone(authoring._parse_spec('{"info": {}}'))  # no paths
        self.assertIsNotNone(authoring._parse_spec('{"paths": {}}'))

    def test_markup_is_stripped_to_readable_text(self):
        text = authoring._strip_markup(
            "<nav>menu</nav><h1>Rates</h1><script>x()</script><p>GET /rates &amp; more</p>"
        )
        self.assertNotIn("menu", text)
        self.assertNotIn("x()", text)
        self.assertIn("GET /rates & more", text)


class TestDeterministicDraft(FrappeTestCase):
    def test_path_parameter_becomes_a_required_field_the_url_references(self):
        m = authoring.openapi_to_manifest(SPEC, "helpdesk", operations=["getTicket"])
        op = m["operations"][0]
        self.assertEqual(op["http"]["url"], "/tickets/{{ params.ticketId }}")
        self.assertEqual(op["fields"][0]["name"], "ticketId")
        self.assertTrue(op["fields"][0]["required"])

    def test_enum_becomes_a_dropdown_with_choices(self):
        m = authoring.openapi_to_manifest(SPEC, "helpdesk", operations=["createTicket"])
        priority = next(f for f in m["operations"][0]["fields"] if f["name"] == "priority")
        self.assertEqual(priority["type"], "Dropdown")
        self.assertEqual([c["value"] for c in priority["choices"]], ["low", "high"])

    def test_dict_method_shadowing_name_is_renamed(self):
        # `params.values` resolves to the dict METHOD, not the field — the single
        # most expensive mistake this configuration format allows.
        m = authoring.openapi_to_manifest(SPEC, "helpdesk", operations=["createTicket"])
        names = [f["name"] for f in m["operations"][0]["fields"]]
        self.assertIn("values_", names)
        self.assertNotIn("values", names)
        self.assertIn("params.values_", m["operations"][0]["http"]["body"])

    def test_auth_scheme_maps_onto_the_connector_enum(self):
        m = authoring.openapi_to_manifest(SPEC, "helpdesk", operations=["getTicket"])
        auth = m["execution"]["auth"]
        self.assertEqual(auth["type"], "API Key Header")
        self.assertEqual(auth["headerName"], "X-Api-Key")
        self.assertNotIn("secret", auth)

    def test_unknown_operation_is_refused_rather_than_guessed(self):
        with self.assertRaises(authoring.ConnectorAuthoringError):
            authoring.openapi_to_manifest(SPEC, "helpdesk", operations=["deleteEverything"])

    def test_relative_server_url_is_resolved_against_the_spec_url(self):
        spec = dict(SPEC, servers=[{"url": "/api/v3"}])
        m = authoring.openapi_to_manifest(
            spec, "helpdesk", operations=["getTicket"], source_url=SOURCE
        )
        self.assertEqual(m["execution"]["baseUrl"], "https://api.example.com/api/v3")

    def test_relative_server_url_with_nothing_to_resolve_against_is_an_error(self):
        spec = dict(SPEC, servers=[{"url": "/api/v3"}])
        with self.assertRaises(authoring.ConnectorAuthoringError):
            authoring.openapi_to_manifest(spec, "helpdesk", operations=["getTicket"])


class TestDraftReview(FrappeTestCase):
    def test_a_generated_draft_reviews_clean(self):
        m = authoring.openapi_to_manifest(
            SPEC, "helpdesk", operations=["createTicket", "getTicket", "listTickets"]
        )
        self.assertEqual(authoring.validate_manifest(m), [])

    def test_template_referencing_an_undeclared_field_is_caught(self):
        draft = _minimal_draft()
        draft["operations"][0]["http"]["body"] = '{"subject": "{{ params.nope }}"}'
        issues = authoring.validate_manifest(draft)
        self.assertTrue(any("params.nope" in i and "no field named" in i for i in issues))

    def test_declared_but_unused_field_is_caught(self):
        draft = _minimal_draft()
        draft["operations"][0]["fields"].append(
            {"name": "orphan", "label": "Orphan", "type": "String"}
        )
        issues = authoring.validate_manifest(draft)
        self.assertTrue(any("orphan" in i and "no template uses it" in i for i in issues))

    def test_shadowed_dot_access_is_called_out_specifically(self):
        draft = _minimal_draft()
        draft["operations"][0]["fields"] = [{"name": "values", "label": "V", "type": "String"}]
        draft["operations"][0]["http"]["body"] = '{"v": "{{ params.values }}"}'
        issues = authoring.validate_manifest(draft)
        self.assertTrue(any("resolves to the dict" in i for i in issues))

    def test_secret_in_a_manifest_is_refused(self):
        draft = _minimal_draft()
        draft["execution"]["auth"] = {"type": "Bearer Token", "secret": "sk_live_oops"}
        issues = authoring.validate_manifest(draft)
        self.assertTrue(any("must not carry a secret" in i for i in issues))

    def test_bad_connector_id_is_refused(self):
        draft = _minimal_draft()
        draft["connectorId"] = "Not-Valid"
        self.assertTrue(any("connectorId" in i for i in authoring.validate_manifest(draft)))

    def test_relative_url_without_base_url_is_caught(self):
        draft = _minimal_draft()
        draft["execution"].pop("baseUrl")
        issues = authoring.validate_manifest(draft)
        self.assertTrue(any("no Base URL" in i for i in issues))

    def test_body_that_stops_being_json_is_caught(self):
        draft = _minimal_draft()
        draft["operations"][0]["http"]["body"] = '{"subject": "{{ params.subject }}",}'
        issues = authoring.validate_manifest(draft)
        self.assertTrue(any("does not parse as JSON" in i for i in issues))

    def test_get_with_a_body_is_caught(self):
        draft = _minimal_draft()
        draft["operations"][0]["http"]["method"] = "GET"
        issues = authoring.validate_manifest(draft)
        self.assertTrue(any("request body" in i for i in issues))

    def test_bad_response_map_path_is_caught(self):
        draft = _minimal_draft()
        draft["operations"][0]["http"]["responseMap"] = {"id": "data..id"}
        issues = authoring.validate_manifest(draft)
        self.assertTrue(any("not a dotted path" in i for i in issues))

    def test_none_literal_expression_is_caught(self):
        draft = _minimal_draft()
        draft["operations"][0]["http"]["body"] = (
            '{"subject": "{{ params.subject }}", "note": "{{ doc.note }}"}'
        )
        issues = authoring.validate_manifest(draft)
        self.assertTrue(any("renders the literal 'None'" in i for i in issues))

    def test_http_operation_with_no_http_block_is_caught(self):
        draft = _minimal_draft()
        draft["operations"][0].pop("http")
        issues = authoring.validate_manifest(draft)
        self.assertTrue(any("http.method and http.url" in i for i in issues))

    def test_python_handler_without_a_path_is_caught(self):
        draft = _minimal_draft()
        draft["operations"][0]["executionType"] = "Python Handler"
        draft["operations"][0].pop("http")
        issues = authoring.validate_manifest(draft)
        self.assertTrue(any("no handler path" in i for i in issues))

    def test_not_json_at_all(self):
        self.assertTrue(authoring.validate_manifest("{oops"))
        self.assertTrue(authoring.validate_manifest([1, 2]))


class TestReviewerImporterAgreement(FrappeTestCase):
    """A draft the reviewer approves MUST import, and survive a round trip.

    This is the invariant the agent's loop rests on. See the module docstring.
    """

    def tearDown(self):
        _cleanup("helpdesk_agree")

    def test_approved_draft_imports_and_round_trips(self):
        _cleanup("helpdesk_agree")
        draft = authoring.openapi_to_manifest(
            SPEC, "helpdesk_agree", operations=["createTicket", "getTicket", "listTickets"]
        )
        self.assertEqual(authoring.validate_manifest(draft), [], "reviewer must approve")

        import_manifest(draft, overwrite=True)

        exported = export_manifest("helpdesk_agree")
        self.assertEqual(
            [o["value"] for o in exported["operations"]],
            [o["value"] for o in draft["operations"]],
        )
        # The exported form must ALSO review clean, or the two spellings have
        # drifted again in the other direction.
        self.assertEqual(authoring.validate_manifest(exported), [])

    def test_every_generated_operation_reaches_the_database_executable(self):
        _cleanup("helpdesk_agree")
        draft = authoring.openapi_to_manifest(
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
        draft = authoring.openapi_to_manifest(SPEC, "helpdesk_write", operations=["getTicket"])
        out = authoring.write_draft_connector(draft)

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

    def test_a_draft_with_issues_is_not_written(self):
        _cleanup("helpdesk_write")
        draft = authoring.openapi_to_manifest(SPEC, "helpdesk_write", operations=["getTicket"])
        draft["operations"][0]["http"]["url"] = ""
        out = authoring.write_draft_connector(draft)
        self.assertFalse(out["written"])
        self.assertTrue(out["issues"])
        self.assertFalse(frappe.db.exists("BPMN Connector", "helpdesk_write"))

    def test_existing_connector_is_not_replaced_without_overwrite(self):
        _cleanup("helpdesk_write")
        draft = authoring.openapi_to_manifest(SPEC, "helpdesk_write", operations=["getTicket"])
        self.assertTrue(authoring.write_draft_connector(draft)["written"])

        again = authoring.write_draft_connector(draft)
        self.assertFalse(again["written"])
        self.assertTrue(any("already exists" in i for i in again["issues"]))
        self.assertTrue(authoring.write_draft_connector(draft, overwrite=True)["written"])


class TestTryOperation(FrappeTestCase):
    def tearDown(self):
        _cleanup("helpdesk_try")

    def test_unknown_operation_is_reported_not_raised_as_a_mystery(self):
        with self.assertRaises(authoring.ConnectorAuthoringError):
            authoring.try_operation("no_such_connector", "nope")

    def test_missing_required_test_input_is_named(self):
        _cleanup("helpdesk_try")
        draft = authoring.openapi_to_manifest(SPEC, "helpdesk_try", operations=["getTicket"])
        authoring.write_draft_connector(draft)
        with self.assertRaises(authoring.ConnectorAuthoringError) as caught:
            authoring.try_operation("helpdesk_try", "getTicket", {})
        self.assertIn("ticketId", str(caught.exception))

    def test_bad_json_test_inputs_are_reported(self):
        with self.assertRaises(authoring.ConnectorAuthoringError):
            authoring.try_operation("helpdesk_try", "getTicket", "{not json")


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
