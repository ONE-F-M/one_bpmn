# Copyright (c) 2026, one-fm and contributors
# Tests for the Service Task connector layer (serviceType="connector").

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.connectors.manifest import get_operation_spec, load_manifests
from one_bpmn.one_bpmn.integrations.google_common import normalize_drive_id
from one_bpmn.one_bpmn.doctype.bpmn_process_instance.dispatchers import dispatch_connector

_GD = "one_bpmn.one_bpmn.integrations.google_drive"


def _echo(params, ctx):
    """Handler for the throwaway test connector.

    Reached by its dotted path from the operation row — the same way every real
    Python operation is now resolved. There is no registry to register with.
    """
    return {"got": params, "td_title": ctx["task_data"].get("title")}


def _ensure_echo_connector():
    """A real configured connector, because that is the only kind there is."""
    if not frappe.db.exists("BPMN Connector", "test_echo"):
        frappe.get_doc({
            "doctype": "BPMN Connector",
            "connector_id": "test_echo",
            "label": "Test Echo",
            "enabled": 1,
            "execution_type": "Python Handler",
        }).insert(ignore_permissions=True)
    if not frappe.db.exists("BPMN Connector Operation", {"connector": "test_echo", "operation_id": "echo"}):
        op = frappe.get_doc({
            "doctype": "BPMN Connector Operation",
            "connector": "test_echo",
            "operation_id": "echo",
            "label": "Echo",
            "enabled": 1,
            "execution_type": "Python Handler",
            "handler_path": "one_bpmn.tests.test_connector_dispatch._echo",
        })
        for name in ("a", "b"):
            op.append("fields", {"field_name": name, "field_type": "String", "expression": 1})
        op.insert(ignore_permissions=True)
    from one_bpmn.one_bpmn.connectors.manifest import clear_manifest_cache

    clear_manifest_cache()


def _instance():
    return SimpleNamespace(context_doctype="", context_docname="", name="T", initiated_by="Administrator")


class TestNormalizeDriveId(FrappeTestCase):
    def test_link_forms_and_bare_id(self):
        self.assertEqual(normalize_drive_id("https://docs.google.com/document/d/ABCDEFGHIJ123/edit"), "ABCDEFGHIJ123")
        self.assertEqual(normalize_drive_id("https://drive.google.com/open?id=ZYXWVUT98765"), "ZYXWVUT98765")
        self.assertEqual(normalize_drive_id("PlainBareId_123456"), "PlainBareId_123456")
        self.assertEqual(normalize_drive_id(""), "")


class TestManifestAndRegistry(FrappeTestCase):
    def test_only_the_operations_that_need_python_name_a_handler(self):
        """Everything an HTTP template can express is configuration now.

        What is left needs multipart upload, binary parsing, or several calls
        with reasoning in between — see the google_connectors_to_http patch.
        """
        from one_bpmn.one_bpmn.connectors.manifest import get_execution_spec, load_manifests

        manifest = next(m for m in load_manifests() if m["connectorId"] == "google_drive")
        python_ops = {
            op["value"]
            for op in manifest["operations"]
            if (get_execution_spec("google_drive", op["value"]) or frappe._dict()).handler_path
        }
        self.assertEqual(
            python_ops,
            {"downloadText", "createFile", "updateFileContent", "setPermissions", "revokePermissions"},
        )


    def test_every_manifest_operation_resolves_to_an_executor(self):
        """The real invariant: an operation must be runnable — by a configured
        HTTP request or by a named handler. There is no third way any more."""
        from one_bpmn.one_bpmn.connectors.manifest import get_execution_spec

        manifest = next(m for m in load_manifests() if m["connectorId"] == "google_drive")
        for op in manifest["operations"]:
            name = op["value"]
            spec = get_execution_spec("google_drive", name)
            self.assertIsNotNone(spec, f"{name} has no execution configuration")
            runnable = bool(
                (spec.execution_type == "HTTP Request" and spec.url_template) or spec.handler_path
            )
            self.assertTrue(runnable, f"manifest op {name} cannot be run by anything")
            self.assertIsNotNone(op.get("fields"))


    def test_permission_enums_match_drive_api(self):
        spec = get_operation_spec("google_drive", "setPermissions")
        roles = next(f for f in spec["fields"] if f["name"] == "role")["choices"]
        self.assertEqual({c["value"] for c in roles},
                         {"owner", "organizer", "fileOrganizer", "writer", "commenter", "reader"})


class TestDispatchConnector(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _ensure_echo_connector()

    def test_render_and_result_mapping(self):
        task = SimpleNamespace(data={"title": "Hello"})
        dispatch_connector(_instance(), task, {
            "connectorId": "test_echo", "operation": "echo", "resultVariable": "echo_out",
            "connectorParams": '{"a": "{{ task_data.title }}", "b": "plain"}',
        }, "t1")
        self.assertEqual(task.data["echo_out"]["got"]["a"], "Hello")
        self.assertEqual(task.data["echo_out"]["got"]["b"], "plain")

    def test_drive_create_file_output_mapped(self):
        task = SimpleNamespace(data={"title": "My SOP", "sop_markdown": "BODY"})
        with patch(f"{_GD}.create_file",
                   return_value={"id": "FILE_1", "name": "My SOP", "webViewLink": "http://drive/FILE_1"}) as cf:
            dispatch_connector(_instance(), task, {
                "connectorId": "google_drive", "operation": "createFile", "resultVariable": "drive_file",
                "connectorParams": ('{"folder": "https://drive.google.com/drive/folders/FOLDER_ABC123", '
                                    '"filename": "{{task_data.title}}", "content": "{{task_data.sop_markdown}}"}'),
            }, "t2")
        self.assertEqual(task.data["drive_file"]["id"], "FILE_1")
        # folder link normalized to id, and rendered inputs reached the function
        self.assertEqual(cf.call_args.kwargs["folder_id"], "FOLDER_ABC123")
        self.assertEqual(cf.call_args.kwargs["filename"], "My SOP")
        self.assertEqual(cf.call_args.kwargs["content"], "BODY")

    def test_drive_file_link_normalized_before_handler(self):
        task = SimpleNamespace(data={})
        with patch(f"{_GD}.download_file_text", side_effect=lambda file, mime_type=None: f"C:{file}") as dl:
            dispatch_connector(_instance(), task, {
                "connectorId": "google_drive", "operation": "downloadText", "resultVariable": "tpl",
                "connectorParams": '{"file": "https://docs.google.com/document/d/ABCDEFGHIJ123/edit"}',
            }, "t3")
        self.assertEqual(dl.call_args.args[0], "ABCDEFGHIJ123")
        self.assertEqual(task.data["tpl"]["text"], "C:ABCDEFGHIJ123")

    def test_fail_on_error_raises_for_unknown(self):
        with self.assertRaises(Exception):
            dispatch_connector(_instance(), SimpleNamespace(data={}),
                               {"connectorId": "nope", "operation": "x", "failOnError": "1"}, "t4")

    def test_unknown_connector_non_fatal_by_default(self):
        task = SimpleNamespace(data={})
        dispatch_connector(_instance(), task, {"connectorId": "nope", "operation": "x"}, "t5")
        # no exception, no result written
        self.assertNotIn("x", task.data)


_GDOCS = "one_bpmn.one_bpmn.integrations.google_docs"
_GSLIDES = "one_bpmn.one_bpmn.integrations.google_slides"


class TestDocsSlidesConnectors(FrappeTestCase):
    def test_only_the_multi_call_operations_name_a_handler(self):
        from one_bpmn.one_bpmn.connectors.manifest import get_execution_spec, load_manifests

        for connector_id, expected in (
            ("google_docs", {"appendText", "getText", "fillTemplate", "fillBrandedTemplate"}),
            ("google_slides", {"getText"}),
        ):
            manifest = next(m for m in load_manifests() if m["connectorId"] == connector_id)
            named = {
                op["value"]
                for op in manifest["operations"]
                if (get_execution_spec(connector_id, op["value"]) or frappe._dict()).handler_path
            }
            with self.subTest(connector=connector_id):
                self.assertEqual(named, expected)


    def test_sheets_needs_no_python_at_all(self):
        """Every Sheets operation is plain REST, so the module is gone."""
        from one_bpmn.one_bpmn.connectors.manifest import get_execution_spec, load_manifests

        manifest = next(m for m in load_manifests() if m["connectorId"] == "google_sheets")
        for op in manifest["operations"]:
            spec = get_execution_spec("google_sheets", op["value"])
            with self.subTest(operation=op["value"]):
                self.assertFalse(spec.handler_path, "Sheets must need no Python")



class TestManifestValidator(FrappeTestCase):
    def test_all_manifests_valid(self):
        from one_bpmn.one_bpmn.connectors.validator import validate_manifests
        issues = validate_manifests()
        self.assertEqual(issues, [], "manifest issues: " + "; ".join(issues))


class TestRetryAndChoices(FrappeTestCase):
    def test_call_with_retry_retries_transient(self):
        from one_bpmn.one_bpmn.integrations.retry import call_with_retry
        calls = {"n": 0}

        class _Err(Exception):
            resp = SimpleNamespace(status=503)

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise _Err()
            return "ok"

        self.assertEqual(call_with_retry(flaky, attempts=3, base_delay=0), "ok")
        self.assertEqual(calls["n"], 3)

    def test_call_with_retry_reraises_non_transient(self):
        from one_bpmn.one_bpmn.integrations.retry import call_with_retry

        class _Err(Exception):
            resp = SimpleNamespace(status=404)

        def boom():
            raise _Err()

        with self.assertRaises(_Err):
            call_with_retry(boom, attempts=3, base_delay=0)

    def test_field_choices_unconfigured_is_empty(self):
        """A field with no Choices From path yields [] rather than an error."""
        from one_bpmn.one_bpmn.connectors.api import get_connector_field_choices
        self.assertEqual(get_connector_field_choices("google_drive", "createFile", "folder"), [])
        self.assertEqual(get_connector_field_choices("__nope__", "__nope__", "__nope__"), [])


class TestSheetsIsPureConfiguration(FrappeTestCase):
    """Sheets was the proof that a whole provider can be configuration.

    Its Python module is gone: every operation is a Jinja-templated REST call on
    its own row. These assert the templates, because there is nothing else left
    to assert — and a broken template is exactly what would otherwise reach
    Google as a malformed body.
    """

    def _spec(self, operation):
        from one_bpmn.one_bpmn.connectors.manifest import get_execution_spec

        spec = get_execution_spec("google_sheets", operation)
        self.assertIsNotNone(spec, f"{operation} has no execution configuration")
        self.assertEqual(spec.execution_type, "HTTP Request")
        return spec

    def test_every_sheets_operation_is_http(self):
        for op in ("createSpreadsheet", "getValues", "updateValues",
                   "appendValues", "clearValues", "addSheet"):
            with self.subTest(operation=op):
                self.assertTrue(self._spec(op).url_template)

    def test_create_spreadsheet_posts_to_drive_not_sheets(self):
        """sheets.create puts the file in the service account's own storage,
        which has no quota — it must go through Drive with a parent folder."""
        spec = self._spec("createSpreadsheet")
        self.assertTrue(spec.url_template.startswith("https://www.googleapis.com/drive/v3/files"))
        self.assertIn("vnd.google-apps.spreadsheet", spec.body_template)
        self.assertIn("parents", spec.body_template)

    def test_update_values_uses_bracket_access_for_the_values_field(self):
        """`values` shadows dict.values(), so params.values would render the
        METHOD into the body. This is the regression guard for that."""
        spec = self._spec("updateValues")
        self.assertIn('params["values"]', spec.body_template)
        self.assertNotIn("params.values", spec.body_template)

    def test_the_validator_catches_that_mistake(self):
        from one_bpmn.one_bpmn.connectors.validator import _shadowed_field_access

        broken = frappe._dict(body_template='{"values": {{ params.values }}}',
                              url_template="x", query_params_json="", headers_json="")
        self.assertTrue(_shadowed_field_access("google_sheets", "updateValues", broken))
        self.assertFalse(_shadowed_field_access("google_sheets", "updateValues", self._spec("updateValues")))

