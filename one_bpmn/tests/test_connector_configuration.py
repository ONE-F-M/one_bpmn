# Copyright (c) 2026, one-fm and contributors
# Tests for connectors-as-configuration: the BPMN Connector / Operation / Field
# DocTypes, the manifest projection built from them, the declarative HTTP
# executor, and the JSON import/export round trip.
#
# The load-bearing test is TestSeedParity: it asserts that importing the shipped
# JSON manifests and projecting them back out of the database reproduces the same
# manifests. That is what makes moving the storage from files to DocTypes safe for
# every existing connector Service Task.

import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.connectors import http_ops
from one_bpmn.one_bpmn.connectors.manifest import (
    clear_manifest_cache,
    field_transforms,
    get_execution_spec,
    load_manifests,
    load_seed_manifests,
    parse_choices,
)
from one_bpmn.one_bpmn.connectors.seed import export_manifest, import_manifest, import_seed_manifests
from one_bpmn.one_bpmn.doctype.bpmn_process_instance.dispatchers import dispatch_connector

# A literal public IP keeps the host allow-list check off DNS, so these tests do
# not depend on name resolution.
_PUBLIC = "https://93.184.216.34"


def _instance():
    return SimpleNamespace(
        context_doctype="", context_docname="", name="T", initiated_by="Administrator"
    )


def _normalize_field(f):
    """Compare fields by meaning, not by which optional keys were written out."""
    return {
        "name": f.get("name"),
        "label": f.get("label") or f.get("name"),
        "type": f.get("type") or "String",
        "required": bool(f.get("required")),
        # An absent 'expression' means "expressions allowed" downstream.
        "expression": f.get("expression") is not False,
        # "" / false / absent all mean "no default" to the panel, which reads a
        # Boolean as `v === true || v === "true"`.
        "default": f.get("default") if f.get("default") not in (None, "", False) else None,
        "choices": [
            {"label": c.get("label"), "value": c.get("value")} if isinstance(c, dict) else {"label": c, "value": c}
            for c in (f.get("choices") or [])
        ],
        "dynamicChoices": bool(f.get("dynamicChoices")),
        "condition": f.get("condition"),
        "help": f.get("help"),
    }


def _normalize_manifest(m):
    return {
        "connectorId": m.get("connectorId"),
        "label": m.get("label"),
        "description": m.get("description"),
        "icon": m.get("icon"),
        "api": m.get("api") or {},
        "operations": [
            {
                "value": op.get("value"),
                "label": op.get("label") or op.get("value"),
                "method": op.get("method"),
                "output": op.get("output"),
                "fields": [_normalize_field(f) for f in op.get("fields") or []],
            }
            for op in m.get("operations") or []
        ],
    }


def _by_id(manifests):
    return {m["connectorId"]: _normalize_manifest(m) for m in manifests}


class TestSeedParity(FrappeTestCase):
    """The DocTypes must reproduce the shipped manifests exactly."""

    def test_db_projection_matches_seed_files(self):
        import_seed_manifests(overwrite=True)
        clear_manifest_cache()

        from_db = _by_id(load_manifests())
        from_files = _by_id(load_seed_manifests())

        for cid, expected in from_files.items():
            self.assertIn(cid, from_db, f"{cid} missing from the database projection")
            self.assertEqual(
                from_db[cid],
                expected,
                f"{cid}: database projection differs from the seed manifest",
            )

    def test_seed_import_is_idempotent(self):
        import_seed_manifests(overwrite=True)
        again = import_seed_manifests(overwrite=False)
        self.assertTrue(again, "no seed manifests were found")
        self.assertTrue(
            all(state == "skipped" for state in again.values()),
            f"a second import was not a no-op: {again}",
        )

    def test_seed_google_connectors_are_python_handlers(self):
        """Seeds are SDK-backed, so they must not be treated as HTTP connectors."""
        import_seed_manifests(overwrite=True)
        spec = get_execution_spec("google_drive", "createFile")
        self.assertIsNotNone(spec)
        self.assertEqual(spec.execution_type, "Python Handler")


class TestFieldProjection(FrappeTestCase):
    """A configured field row must project into the manifest field schema."""

    def setUp(self):
        _make_connector("cfg_test", execution_type="HTTP Request", base_url=_PUBLIC)

    def test_choices_condition_and_required_projection(self):
        _make_operation(
            "cfg_test",
            "doThing",
            url_template="/thing",
            fields=[
                {
                    "field_name": "mode",
                    "field_label": "Mode",
                    "field_type": "Dropdown",
                    "required": 1,
                    "choices": "User|user\nGroup|group\nplain",
                },
                {
                    "field_name": "email",
                    "field_label": "Email",
                    "field_type": "String",
                    "condition_field": "mode",
                    "condition_operator": "one of",
                    "condition_value": "user, group",
                    "help_text": "Who to notify",
                },
                {
                    "field_name": "raw",
                    "field_type": "Text",
                    "expression": 0,
                    "default_value": "x",
                },
            ],
        )
        clear_manifest_cache()

        op = next(
            o
            for m in load_manifests()
            if m["connectorId"] == "cfg_test"
            for o in m["operations"]
            if o["value"] == "doThing"
        )
        mode, email, raw = op["fields"]

        self.assertEqual(mode["type"], "Dropdown")
        self.assertTrue(mode["required"])
        self.assertEqual(
            mode["choices"],
            [
                {"label": "User", "value": "user"},
                {"label": "Group", "value": "group"},
                {"label": "plain", "value": "plain"},
            ],
        )
        self.assertEqual(email["condition"], {"field": "mode", "oneOf": ["user", "group"]})
        self.assertEqual(email["help"], "Who to notify")
        # label falls back to the field name; expression off is carried through
        self.assertEqual(raw["label"], "raw")
        self.assertFalse(raw["expression"])
        self.assertEqual(raw["default"], "x")

    def test_icon_projection(self):
        conn = frappe.get_doc("BPMN Connector", "cfg_test")
        conn.icon_svg_path = "M1 2h3v4z"
        conn.icon_color = "#ff0000"
        conn.save(ignore_permissions=True)
        clear_manifest_cache()

        manifest = next(m for m in load_manifests() if m["connectorId"] == "cfg_test")
        self.assertEqual(
            manifest["icon"], {"path": "M1 2h3v4z", "color": "#ff0000", "label": "Cfg Test"}
        )

    def test_parse_choices_forms(self):
        self.assertEqual(
            parse_choices("A|a\n\n bare \nB|b"),
            [
                {"label": "A", "value": "a"},
                {"label": "bare", "value": "bare"},
                {"label": "B", "value": "b"},
            ],
        )


class TestValueTransform(FrappeTestCase):
    """Provider-specific input handling must be configuration, not code.

    The generic dispatcher used to hardcode "if the field type is DriveFile or
    DriveFolder, run Google's normaliser". Now a field names its own transform.
    """

    def setUp(self):
        _make_connector("tf_test", execution_type="HTTP Request", base_url=_PUBLIC)
        _make_operation(
            "tf_test",
            "send",
            url_template="/send",
            body_template='{"file": "{{ params.file }}", "raw": "{{ params.raw }}"}',
            fields=[
                {
                    "field_name": "file",
                    "field_type": "String",
                    "value_transform": (
                        "one_bpmn.one_bpmn.integrations.google_common.normalize_drive_id"
                    ),
                },
                {"field_name": "raw", "field_type": "String"},
            ],
        )
        clear_manifest_cache()

    def test_transform_applied_only_to_the_field_that_declares_it(self):
        link = "https://docs.google.com/document/d/ABCDEFGHIJ123/edit"
        task = SimpleNamespace(data={})
        with patch("requests.request", return_value=_fake_response({})) as req:
            dispatch_connector(
                _instance(),
                task,
                {
                    "connectorId": "tf_test",
                    "operation": "send",
                    "connectorParams": json.dumps({"file": link, "raw": link}),
                    "failOnError": "1",
                },
                "tf1",
            )
        sent = req.call_args.kwargs["json"]
        self.assertEqual(sent["file"], "ABCDEFGHIJ123")  # normalised
        self.assertEqual(sent["raw"], link)  # untouched

    def test_transform_path_is_not_exposed_in_the_public_manifest(self):
        """The manifest goes to the browser; a code path should not."""
        blob = json.dumps(load_manifests())
        self.assertNotIn("normalize_drive_id", blob)
        self.assertNotIn("value_transform", blob)

    def test_broken_transform_degrades_instead_of_killing_the_workflow(self):
        op = frappe.get_doc(
            "BPMN Connector Operation", {"connector": "tf_test", "operation_id": "send"}
        )
        op.fields[0].value_transform = f"{__name__}.exploding_transform"
        op.save(ignore_permissions=True)
        clear_manifest_cache()

        task = SimpleNamespace(data={})
        with patch("requests.request", return_value=_fake_response({})) as req:
            dispatch_connector(
                _instance(),
                task,
                {
                    "connectorId": "tf_test",
                    "operation": "send",
                    "connectorParams": '{"file": "not json", "raw": "x"}',
                    "failOnError": "1",
                },
                "tf2",
            )
        # the original value is used rather than the request being abandoned
        self.assertEqual(req.call_args.kwargs["json"]["file"], "not json")

    def test_google_seed_fields_carry_the_drive_transform(self):
        import_seed_manifests(overwrite=True)
        transforms = field_transforms("google_drive", "createFile")
        self.assertEqual(
            transforms.get("folder"),
            "one_bpmn.one_bpmn.integrations.google_common.normalize_drive_id",
        )
        # and the Google-named field types are gone from the generic enum
        specs = frappe.get_all(
            "BPMN Connector Field",
            filters={"field_type": ("in", ("DriveFile", "DriveFolder"))},
            pluck="name",
        )
        self.assertEqual(specs, [])


class TestDynamicChoices(FrappeTestCase):
    """Dynamic dropdowns resolve their function from configuration, never input."""

    def setUp(self):
        _make_connector("dyn_test", execution_type="HTTP Request", base_url=_PUBLIC)
        _make_operation(
            "dyn_test",
            "pick",
            url_template="/pick",
            fields=[
                {"field_name": "folder", "field_type": "String"},
                {
                    "field_name": "file",
                    "field_type": "Dropdown",
                    "choices_source_path": f"{__name__}.sample_choices",
                },
            ],
        )
        clear_manifest_cache()

    def test_manifest_flags_the_dropdown_without_leaking_the_path(self):
        op = next(
            o
            for m in load_manifests()
            if m["connectorId"] == "dyn_test"
            for o in m["operations"]
            if o["value"] == "pick"
        )
        field = next(f for f in op["fields"] if f["name"] == "file")
        self.assertTrue(field["dynamicChoices"])
        self.assertNotIn("choicesSourcePath", field)
        self.assertNotIn(__name__, json.dumps(op))

    def test_choices_receive_sibling_field_values(self):
        from one_bpmn.one_bpmn.connectors.api import get_connector_field_choices

        got = get_connector_field_choices(
            "dyn_test", "pick", "file", context={"folder": "F1", "unused": "x"}
        )
        self.assertEqual(got, [{"label": "in F1", "value": "F1-1"}])

    def test_caller_cannot_name_the_function_to_run(self):
        """The endpoint takes a field, not a path — the path comes from the DB."""
        from one_bpmn.one_bpmn.connectors.api import get_connector_field_choices

        # A field with no configured path yields [], whatever the caller passes.
        self.assertEqual(get_connector_field_choices("dyn_test", "pick", "folder"), [])
        self.assertEqual(
            get_connector_field_choices("dyn_test", "pick", "folder", context={"folder": "F1"}), []
        )

    def test_failing_choices_function_returns_empty(self):
        from one_bpmn.one_bpmn.connectors.api import get_connector_field_choices

        op = frappe.get_doc(
            "BPMN Connector Operation", {"connector": "dyn_test", "operation_id": "pick"}
        )
        op.fields[1].choices_source_path = f"{__name__}.exploding_choices"
        op.save(ignore_permissions=True)
        clear_manifest_cache()

        self.assertEqual(get_connector_field_choices("dyn_test", "pick", "file"), [])


def sample_choices(folder=None):
    """Stand-in for a real dynamic-choices function (e.g. Drive file listing)."""
    if not folder:
        return []
    return [{"label": f"in {folder}", "value": f"{folder}-1"}]


def exploding_choices(**_kwargs):
    raise RuntimeError("provider unreachable")


def exploding_transform(_value):
    """A transform that blows up, to prove a bad one degrades gracefully."""
    raise RuntimeError("cannot normalise that")


NOT_CALLABLE = "importable, but not a function"


class TestConfigValidation(FrappeTestCase):
    """The DocTypes must refuse configurations that could only fail at runtime."""

    def test_bad_connector_id_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            _make_connector("Not An Id")

    def test_icon_markup_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            _make_connector("icon_test", icon_svg_path="<svg><path d='M1 1'/></svg>")

    def test_dropdown_without_choices_rejected(self):
        _make_connector("dd_test", base_url=_PUBLIC)
        with self.assertRaises(frappe.ValidationError):
            _make_operation(
                "dd_test",
                "op",
                url_template="/x",
                fields=[{"field_name": "pick", "field_type": "Dropdown"}],
            )

    def test_condition_on_unknown_field_rejected(self):
        _make_connector("cond_test", base_url=_PUBLIC)
        with self.assertRaises(frappe.ValidationError):
            _make_operation(
                "cond_test",
                "op",
                url_template="/x",
                fields=[
                    {
                        "field_name": "a",
                        "field_type": "String",
                        "condition_field": "nope",
                        "condition_operator": "equals",
                        "condition_value": "1",
                    }
                ],
            )

    def test_relative_url_without_base_url_rejected(self):
        _make_connector("rel_test")  # no base_url
        with self.assertRaises(frappe.ValidationError):
            _make_operation("rel_test", "op", url_template="/relative")

    def test_http_operation_without_url_rejected(self):
        _make_connector("nourl_test", base_url=_PUBLIC)
        with self.assertRaises(frappe.ValidationError):
            _make_operation("nourl_test", "op", url_template="")

    def test_unimportable_value_transform_rejected(self):
        _make_connector("vt_test", base_url=_PUBLIC)
        with self.assertRaises(frappe.ValidationError):
            _make_operation(
                "vt_test",
                "op",
                url_template="/x",
                fields=[{"field_name": "a", "value_transform": "no.such.module.fn"}],
            )

    def test_non_callable_value_transform_rejected(self):
        _make_connector("vt2_test", base_url=_PUBLIC)
        with self.assertRaises(frappe.ValidationError):
            _make_operation(
                "vt2_test",
                "op",
                url_template="/x",
                fields=[{"field_name": "a", "value_transform": f"{__name__}.NOT_CALLABLE"}],
            )

    def test_unimportable_handler_path_rejected(self):
        _make_connector("hp_test", execution_type="Python Handler")
        with self.assertRaises(frappe.ValidationError):
            _make_operation(
                "hp_test", "op", execution_type="Python Handler", handler_path="no.such.module.fn"
            )


class TestHttpExecutor(FrappeTestCase):
    """An HTTP connector must run end to end with no Python handler at all."""

    def setUp(self):
        _make_connector("httpbin_test", execution_type="HTTP Request", base_url=_PUBLIC)
        _make_operation(
            "httpbin_test",
            "createThing",
            http_method="POST",
            url_template="/v1/things/{{ params.parent }}",
            headers_json='{"X-Trace": "{{ task_data.trace }}"}',
            query_params_json='{"fields": "id,name", "blank": "{{ params.missing }}"}',
            body_template='{"name": "{{ params.name }}", "note": "{{ doc.note }}"}',
            response_map_json='{"id": "data.id", "first": "data.items[0].label"}',
            fields=[
                {"field_name": "parent", "field_type": "String", "required": 1},
                {"field_name": "name", "field_type": "String", "required": 1},
            ],
        )
        clear_manifest_cache()

    def _dispatch(self, params, task_data=None, response=None, status=200):
        task = SimpleNamespace(data=dict(task_data or {}))
        fake = _fake_response(response if response is not None else {}, status=status)
        with patch("requests.request", return_value=fake) as req:
            dispatch_connector(
                _instance(),
                task,
                {
                    "connectorId": "httpbin_test",
                    "operation": "createThing",
                    "resultVariable": "out",
                    "connectorParams": json.dumps(params),
                    "failOnError": "1",
                },
                "http1",
            )
        return task, req

    def test_renders_url_headers_query_body_and_maps_response(self):
        task, req = self._dispatch(
            {"parent": "P1", "name": "Widget"},
            task_data={"trace": "abc123"},
            response={"data": {"id": "T9", "items": [{"label": "first!"}]}},
        )

        method, url = req.call_args.args
        kwargs = req.call_args.kwargs
        self.assertEqual(method, "POST")
        # base_url + rendered path, with the query string appended
        self.assertTrue(url.startswith(f"{_PUBLIC}/v1/things/P1?"), url)
        self.assertIn("fields=id%2Cname", url)
        # a query value that rendered empty is dropped rather than sent blank
        self.assertNotIn("blank=", url)
        self.assertEqual(kwargs["headers"]["X-Trace"], "abc123")
        # A None-valued field renders as the literal "None" — Frappe's Jinja
        # behaviour, matched here on purpose so the HTTP executor and the existing
        # connectorParams rendering path do not disagree. See the README.
        self.assertEqual(kwargs["json"], {"name": "Widget", "note": "None"})

        # response projected through the response map
        self.assertEqual(task.data["out"], {"id": "T9", "first": "first!"})

    def test_undefined_reference_renders_empty_not_debug_text(self):
        """Frappe renders an unknown name as "{{ no such element: … }}"."""
        _, req = self._dispatch({"parent": "P", "name": "N"}, response={})
        url = req.call_args.args[1]
        self.assertNotIn("no such element", url)
        self.assertNotIn("blank=", url)

    def test_missing_response_path_is_none_not_an_error(self):
        task, _ = self._dispatch({"parent": "P", "name": "N"}, response={"data": {}})
        self.assertEqual(task.data["out"], {"id": None, "first": None})

    def test_no_response_map_returns_whole_payload(self):
        op = frappe.get_doc(
            "BPMN Connector Operation",
            {"connector": "httpbin_test", "operation_id": "createThing"},
        )
        op.response_map_json = None
        op.save(ignore_permissions=True)
        clear_manifest_cache()

        task, _ = self._dispatch({"parent": "P", "name": "N"}, response={"anything": 1})
        self.assertEqual(task.data["out"], {"anything": 1})

    def test_http_error_propagates_when_fail_on_error(self):
        import requests

        err = requests.HTTPError("boom")
        err.response = _fake_response({"error": "nope"}, status=400)
        with patch("requests.request", side_effect=err):
            with self.assertRaises(http_ops.ConnectorHTTPError):
                dispatch_connector(
                    _instance(),
                    SimpleNamespace(data={}),
                    {
                        "connectorId": "httpbin_test",
                        "operation": "createThing",
                        "resultVariable": "out",
                        "connectorParams": '{"parent": "P", "name": "N"}',
                        "failOnError": "1",
                    },
                    "http2",
                )

    def test_failure_is_non_fatal_by_default(self):
        task = SimpleNamespace(data={})
        with patch("requests.request", side_effect=OSError("network down")):
            dispatch_connector(
                _instance(),
                task,
                {
                    "connectorId": "httpbin_test",
                    "operation": "createThing",
                    "resultVariable": "out",
                    "connectorParams": '{"parent": "P", "name": "N"}',
                },
                "http3",
            )
        # logged, workflow continues, nothing useful written
        self.assertIsNone(task.data.get("out"))

    def test_bearer_token_applied(self):
        conn = frappe.get_doc("BPMN Connector", "httpbin_test")
        conn.auth_type = "Bearer Token"
        conn.auth_settings_doctype = "System Settings"
        conn.auth_secret_field = "some_secret"
        conn.save(ignore_permissions=True)
        clear_manifest_cache()

        with patch.object(http_ops, "_read_secret", return_value="s3cret"):
            _, req = self._dispatch({"parent": "P", "name": "N"}, response={})
        self.assertEqual(req.call_args.kwargs["headers"]["Authorization"], "Bearer s3cret")

    def test_missing_secret_is_an_error_not_an_unauthenticated_call(self):
        conn = frappe.get_doc("BPMN Connector", "httpbin_test")
        conn.auth_type = "Bearer Token"
        conn.auth_settings_doctype = "System Settings"
        conn.auth_secret_field = "some_secret"
        conn.save(ignore_permissions=True)
        clear_manifest_cache()

        with patch.object(http_ops, "_read_secret", return_value=None):
            with patch("requests.request") as req:
                with self.assertRaises(http_ops.ConnectorHTTPError):
                    dispatch_connector(
                        _instance(),
                        SimpleNamespace(data={}),
                        {
                            "connectorId": "httpbin_test",
                            "operation": "createThing",
                            "connectorParams": '{"parent": "P", "name": "N"}',
                            "failOnError": "1",
                        },
                        "http4",
                    )
        req.assert_not_called()


class TestCredentialOnConnector(FrappeTestCase):
    """A connector holds its own credential — no Customize Form detour.

    The secret is an encrypted Password field on BPMN Connector. These tests pin
    down the part that matters: it authenticates the call, and it escapes through
    none of the read paths.
    """

    SECRET = "tok-on-connector-987"

    def setUp(self):
        _make_connector(
            "cred_test",
            execution_type="HTTP Request",
            base_url=_PUBLIC,
            auth_type="Bearer Token",
            credential_source="On this connector",
            auth_secret=self.SECRET,
        )
        _make_operation("cred_test", "ping", http_method="GET", url_template="/ping")
        clear_manifest_cache()

    def _dispatch(self):
        task = SimpleNamespace(data={})
        with patch("requests.request", return_value=_fake_response({"ok": True})) as req:
            dispatch_connector(
                _instance(),
                task,
                {
                    "connectorId": "cred_test",
                    "operation": "ping",
                    "resultVariable": "r",
                    "failOnError": "1",
                    "connectorParams": "{}",
                },
                "cred1",
            )
        return req

    def test_on_connector_secret_authenticates_the_call(self):
        req = self._dispatch()
        self.assertEqual(
            req.call_args.kwargs["headers"].get("Authorization"), f"Bearer {self.SECRET}"
        )

    def test_plaintext_is_not_in_the_table(self):
        stored = frappe.db.get_value("BPMN Connector", "cred_test", "auth_secret")
        self.assertNotEqual(stored, self.SECRET)

    def test_secret_escapes_no_read_path(self):
        for label, payload in (
            ("document", frappe.get_doc("BPMN Connector", "cred_test").as_dict()),
            ("get_all *", frappe.get_all("BPMN Connector", filters={"name": "cred_test"}, fields=["*"])),
            ("manifest", load_manifests()),
            ("export", export_manifest("cred_test")),
            ("execution spec", dict(get_execution_spec("cred_test", "ping"))),
        ):
            self.assertNotIn(self.SECRET, json.dumps(payload, default=str), f"leaked via {label}")

    def test_export_keeps_the_source_so_it_can_be_re_entered(self):
        auth = export_manifest("cred_test")["execution"]["auth"]
        self.assertEqual(auth["source"], "On this connector")
        self.assertEqual(auth["type"], "Bearer Token")

    def test_settings_doctype_source_still_works(self):
        """Shared credentials — several connectors, one key, one rotation."""
        conn = frappe.get_doc("BPMN Connector", "cred_test")
        conn.credential_source = "From a settings DocType"
        conn.auth_settings_doctype = "Processa Settings"
        conn.auth_secret_field = "google_drive_service_account_json"
        conn.save(ignore_permissions=True)
        clear_manifest_cache()

        with patch.object(http_ops, "_read_secret", return_value="shared-key") as rs:
            req = self._dispatch()
        self.assertTrue(rs.called)
        self.assertEqual(req.call_args.kwargs["headers"].get("Authorization"), "Bearer shared-key")

    def test_settings_source_rejects_a_non_password_field(self):
        """A plain Data field would store the secret unencrypted."""
        conn = frappe.get_doc("BPMN Connector", "cred_test")
        conn.credential_source = "From a settings DocType"
        conn.auth_settings_doctype = "Processa Settings"
        conn.auth_secret_field = "name"  # exists, but is not a Password field
        with self.assertRaises(frappe.ValidationError):
            conn.save(ignore_permissions=True)

    def test_settings_source_rejects_an_unknown_field(self):
        conn = frappe.get_doc("BPMN Connector", "cred_test")
        conn.credential_source = "From a settings DocType"
        conn.auth_settings_doctype = "Processa Settings"
        conn.auth_secret_field = "no_such_field_anywhere"
        with self.assertRaises(frappe.ValidationError):
            conn.save(ignore_permissions=True)

    def test_missing_on_connector_secret_errors_rather_than_calling_bare(self):
        conn = frappe.get_doc("BPMN Connector", "cred_test")
        conn.auth_secret = ""
        conn.save(ignore_permissions=True)
        frappe.db.sql(
            "delete from `__Auth` where doctype=%s and name=%s", ("BPMN Connector", "cred_test")
        )
        clear_manifest_cache()

        with patch("requests.request") as req:
            with self.assertRaises(http_ops.ConnectorHTTPError):
                dispatch_connector(
                    _instance(),
                    SimpleNamespace(data={}),
                    {
                        "connectorId": "cred_test",
                        "operation": "ping",
                        "failOnError": "1",
                        "connectorParams": "{}",
                    },
                    "cred2",
                )
        req.assert_not_called()


class TestHttpSafety(FrappeTestCase):
    def test_internal_hosts_refused_by_default(self):
        for url in (
            "http://127.0.0.1/x",
            "http://10.0.0.5/x",
            "http://169.254.169.254/latest/meta-data",
            "http://192.168.1.1/x",
        ):
            with self.assertRaises(http_ops.ConnectorHTTPError, msg=url):
                http_ops._assert_host_allowed(url, allow_internal=False)

    def test_internal_hosts_allowed_when_opted_in(self):
        http_ops._assert_host_allowed("http://10.0.0.5/x", allow_internal=True)

    def test_public_host_allowed(self):
        http_ops._assert_host_allowed(f"{_PUBLIC}/x", allow_internal=False)

    def test_non_http_scheme_refused(self):
        for url in ("file:///etc/passwd", "gopher://x/1", "ftp://example.com/x"):
            with self.assertRaises(http_ops.ConnectorHTTPError, msg=url):
                http_ops._assert_host_allowed(url, allow_internal=True)

    def test_oversized_response_refused(self):
        big = _fake_response({}, raw=b"x" * (http_ops._MAX_RESPONSE_BYTES + 1))
        with self.assertRaises(http_ops.ConnectorHTTPError):
            http_ops._parse_response(big)

    def test_dig_walks_dicts_and_lists(self):
        data = {"a": {"b": [{"c": 7}]}}
        self.assertEqual(http_ops.dig(data, "a.b[0].c"), 7)
        self.assertIsNone(http_ops.dig(data, "a.b[3].c"))
        self.assertIsNone(http_ops.dig(data, "a.x.y"))
        self.assertIsNone(http_ops.dig(data, "a.b.c"))  # list indexed as a dict


class TestExportImportRoundTrip(FrappeTestCase):
    def test_export_then_import_reproduces_the_connector(self):
        import_seed_manifests(overwrite=True)
        exported = export_manifest("google_drive")

        exported["connectorId"] = "google_drive_copy"
        import_manifest(exported, overwrite=True)
        clear_manifest_cache()

        original = next(m for m in load_manifests() if m["connectorId"] == "google_drive")
        copy = next(m for m in load_manifests() if m["connectorId"] == "google_drive_copy")

        a, b = _normalize_manifest(original), _normalize_manifest(copy)
        a.pop("connectorId"), b.pop("connectorId")
        self.assertEqual(b, a)

    def test_export_carries_execution_but_never_a_secret(self):
        _make_connector(
            "sec_test",
            execution_type="HTTP Request",
            base_url=_PUBLIC,
            auth_type="Bearer Token",
            auth_settings_doctype="System Settings",
            auth_secret_field="some_secret",
        )
        _make_operation("sec_test", "op", url_template="/x")

        exported = export_manifest("sec_test")
        self.assertEqual(exported["execution"]["type"], "HTTP Request")
        self.assertEqual(exported["execution"]["auth"]["secretField"], "some_secret")
        blob = json.dumps(exported)
        self.assertNotIn("password", blob.lower())


class TestCacheInvalidation(FrappeTestCase):
    def test_saving_a_connector_refreshes_the_manifests(self):
        _make_connector("cache_test", base_url=_PUBLIC, execution_type="HTTP Request")
        _make_operation("cache_test", "opOne", url_template="/one")

        before = next(m for m in load_manifests() if m["connectorId"] == "cache_test")
        self.assertEqual([o["value"] for o in before["operations"]], ["opOne"])

        # No explicit cache clear here — the DocType hooks must do it.
        _make_operation("cache_test", "opTwo", url_template="/two", sort_order=2)
        after = next(m for m in load_manifests() if m["connectorId"] == "cache_test")
        self.assertEqual([o["value"] for o in after["operations"]], ["opOne", "opTwo"])

    def test_disabled_connector_disappears_from_the_modeler(self):
        _make_connector("off_test", base_url=_PUBLIC, execution_type="HTTP Request")
        _make_operation("off_test", "op", url_template="/x")
        self.assertTrue(any(m["connectorId"] == "off_test" for m in load_manifests()))

        conn = frappe.get_doc("BPMN Connector", "off_test")
        conn.enabled = 0
        conn.save(ignore_permissions=True)

        self.assertFalse(any(m["connectorId"] == "off_test" for m in load_manifests()))
        # ...and refuses to dispatch
        self.assertIsNone(get_execution_spec("off_test", "op"))


# ── Builders ─────────────────────────────────────────────────────────────────
def _drop_connector(connector_id):
    """Remove a connector and its operations if a previous test left them behind.

    Some helpers here (the seed importer) commit, so the per-test rollback cannot
    be relied on to clean up between tests in the same class.
    """
    for name in frappe.get_all(
        "BPMN Connector Operation", filters={"connector": connector_id}, pluck="name"
    ):
        frappe.delete_doc("BPMN Connector Operation", name, ignore_permissions=True, force=True)
    if frappe.db.exists("BPMN Connector", connector_id):
        frappe.delete_doc("BPMN Connector", connector_id, ignore_permissions=True, force=True)
    clear_manifest_cache()


def _make_connector(connector_id, **kwargs):
    _drop_connector(connector_id)
    doc = frappe.get_doc(
        {
            "doctype": "BPMN Connector",
            "connector_id": connector_id,
            "label": connector_id.replace("_", " ").title(),
            "enabled": 1,
            "execution_type": kwargs.pop("execution_type", "HTTP Request"),
            **kwargs,
        }
    )
    doc.insert(ignore_permissions=True)
    return doc


def _make_operation(connector, operation_id, fields=None, **kwargs):
    existing = frappe.db.get_value(
        "BPMN Connector Operation", {"connector": connector, "operation_id": operation_id}, "name"
    )
    if existing:
        frappe.delete_doc(
            "BPMN Connector Operation", existing, ignore_permissions=True, force=True
        )
    doc = frappe.get_doc(
        {
            "doctype": "BPMN Connector Operation",
            "connector": connector,
            "operation_id": operation_id,
            "label": operation_id,
            "enabled": 1,
            "http_method": kwargs.pop("http_method", "POST"),
            **kwargs,
        }
    )
    for row in fields or []:
        doc.append("fields", {"expression": 1, "field_type": "String", **row})
    doc.insert(ignore_permissions=True)
    return doc


def _fake_response(payload, status=200, raw=None):
    """A stand-in for requests.Response, enough for the executor's needs."""
    content = raw if raw is not None else json.dumps(payload).encode("utf-8")
    return SimpleNamespace(
        content=content,
        text=content.decode("utf-8", errors="replace"),
        status_code=status,
        encoding="utf-8",
        headers={"Content-Type": "application/json"},
        raise_for_status=lambda: None,
    )
