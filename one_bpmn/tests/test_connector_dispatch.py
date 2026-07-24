# Copyright (c) 2026, one-fm and contributors
# Tests for the Service Task connector layer (serviceType="connector").

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.connectors.registry import connector, get_handler, registered
from one_bpmn.one_bpmn.connectors.manifest import get_operation_spec, load_manifests
from one_bpmn.one_bpmn.integrations.google_common import normalize_drive_id
from one_bpmn.one_bpmn.doctype.bpmn_process_instance.dispatchers import dispatch_connector

_GD = "one_bpmn.one_bpmn.integrations.google_drive"


@connector("__test", "echo")
def _echo(params, ctx):
    return {"got": params, "td_title": ctx["task_data"].get("title")}


def _instance():
    return SimpleNamespace(context_doctype="", context_docname="", name="T", initiated_by="Administrator")


class TestNormalizeDriveId(FrappeTestCase):
    def test_link_forms_and_bare_id(self):
        self.assertEqual(normalize_drive_id("https://docs.google.com/document/d/ABCDEFGHIJ123/edit"), "ABCDEFGHIJ123")
        self.assertEqual(normalize_drive_id("https://drive.google.com/open?id=ZYXWVUT98765"), "ZYXWVUT98765")
        self.assertEqual(normalize_drive_id("PlainBareId_123456"), "PlainBareId_123456")
        self.assertEqual(normalize_drive_id(""), "")


class TestManifestAndRegistry(FrappeTestCase):
    def test_google_drive_registered(self):
        self.assertIn("google_drive", registered())
        for op in ("downloadText", "createFile", "updateFileContent", "setPermissions", "listFiles", "deleteFile"):
            self.assertIsNotNone(get_handler("google_drive", op), f"missing handler {op}")

    def test_manifest_matches_handlers(self):
        manifest = next(m for m in load_manifests() if m["connectorId"] == "google_drive")
        for op in manifest["operations"]:
            self.assertIsNotNone(get_handler("google_drive", op["value"]),
                                 f"manifest op {op['value']} has no handler")
            self.assertTrue(op.get("fields") is not None)

    def test_permission_enums_match_drive_api(self):
        spec = get_operation_spec("google_drive", "setPermissions")
        roles = next(f for f in spec["fields"] if f["name"] == "role")["choices"]
        self.assertEqual({c["value"] for c in roles},
                         {"owner", "organizer", "fileOrganizer", "writer", "commenter", "reader"})


class TestDispatchConnector(FrappeTestCase):
    def test_render_and_result_mapping(self):
        task = SimpleNamespace(data={"title": "Hello"})
        dispatch_connector(_instance(), task, {
            "connectorId": "__test", "operation": "echo", "resultVariable": "echo_out",
            "connectorParams": '{"a": "{{ task_data.title }}", "b": "plain"}',
        }, "t1")
        self.assertEqual(task.data["echo_out"]["got"]["a"], "Hello")
        self.assertEqual(task.data["echo_out"]["got"]["b"], "plain")

    def test_drive_create_file_output_mapped(self):
        task = SimpleNamespace(data={"document_type": "SOP", "title": "My SOP", "sop_markdown": "BODY"})
        with patch(f"{_GD}.resolve_folder_id", return_value="FOLDER") as _r, \
             patch(f"{_GD}.create_file",
                   return_value={"id": "FILE_1", "name": "My SOP", "webViewLink": "http://drive/FILE_1"}) as cf:
            dispatch_connector(_instance(), task, {
                "connectorId": "google_drive", "operation": "createFile", "resultVariable": "drive_file",
                "connectorParams": ('{"documentType": "{{task_data.document_type}}", '
                                    '"filename": "{{task_data.title}}", "content": "{{task_data.sop_markdown}}"}'),
            }, "t2")
        self.assertEqual(task.data["drive_file"]["id"], "FILE_1")
        # rendered inputs reached the underlying function
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
    def test_docs_and_slides_registered(self):
        for op in ("createDocument", "insertText", "appendText", "replaceAllText", "getText"):
            self.assertIsNotNone(get_handler("google_docs", op), f"missing docs {op}")
        for op in ("createPresentation", "replaceAllText", "createSlide", "duplicateSlide", "getText"):
            self.assertIsNotNone(get_handler("google_slides", op), f"missing slides {op}")

    def test_docs_replace_all_text_dispatch(self):
        task = SimpleNamespace(data={"doc_id": "D1", "name": "Acme"})
        with patch(f"{_GDOCS}.replace_all_text", return_value={"documentId": "D1", "occurrencesChanged": 3}) as rp:
            dispatch_connector(_instance(), task, {
                "connectorId": "google_docs", "operation": "replaceAllText", "resultVariable": "r",
                "connectorParams": '{"document": "https://docs.google.com/document/d/DOCID12345/edit", '
                                   '"find": "{{name}}", "replace": "{{ task_data.name }}"}',
            }, "d1")
        self.assertEqual(task.data["r"]["occurrencesChanged"], 3)
        # DriveFile normalized, expression rendered
        self.assertEqual(rp.call_args.args[0], "DOCID12345")
        self.assertEqual(rp.call_args.args[2], "Acme")

    def test_slides_get_text_dispatch(self):
        task = SimpleNamespace(data={})
        with patch(f"{_GSLIDES}.get_text", return_value="## Slide 1\nHello") as gt:
            dispatch_connector(_instance(), task, {
                "connectorId": "google_slides", "operation": "getText", "resultVariable": "deck",
                "connectorParams": '{"presentation": "PRESID987"}',
            }, "s1")
        self.assertEqual(task.data["deck"]["text"], "## Slide 1\nHello")
        self.assertEqual(gt.call_args.args[0], "PRESID987")


class TestManifestValidator(FrappeTestCase):
    def test_all_manifests_valid(self):
        from one_bpmn.one_bpmn.connectors.validator import validate_manifests
        issues = validate_manifests()
        self.assertEqual(issues, [], "manifest issues: " + "; ".join(issues))


class TestRetryAndChoices(FrappeTestCase):
    def test_call_with_retry_retries_transient(self):
        from one_bpmn.one_bpmn.integrations.google_common import call_with_retry
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
        from one_bpmn.one_bpmn.integrations.google_common import call_with_retry

        class _Err(Exception):
            resp = SimpleNamespace(status=404)

        def boom():
            raise _Err()

        with self.assertRaises(_Err):
            call_with_retry(boom, attempts=3, base_delay=0)

    def test_field_choices_document_types(self):
        from one_bpmn.one_bpmn.connectors.api import get_connector_field_choices
        # returns a list (possibly empty if no folder map configured)
        self.assertIsInstance(get_connector_field_choices("driveDocumentTypes"), list)
        self.assertEqual(get_connector_field_choices("__unknown__"), [])
