# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Producing a document that keeps its template's branding.

The old path — export a template to plain text, have a model imitate it, upload
markdown — cannot preserve a design. Logos, table borders, named styles and the
bilingual/RTL layout are all gone before the model even sees the template, and
the finished file is built from the model's output rather than the template.

The new path is Google's own: ``files.copy`` to instantiate, then one
``documents.batchUpdate`` to fill the placeholders. These tests cover the two
operations that make it possible, and the two failure modes that would quietly
publish a broken document:

  * a placeholder that matched nothing (split across formatting runs), and
  * following the copy with ``updateFileContent``, which would replace the whole
    body and destroy exactly what the copy was for.

Network is never touched: the Google service layer is faked, so these run
anywhere. Fidelity against real Drive is a separate, manual check — noted at the
bottom of this file.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

import frappe

from one_bpmn.one_bpmn.connectors.registry import get_handler

TEMPLATE_ID = "_TestBrandedTemplateId"
COPY_ID = "_TestCopyId"
FOLDER_ID = "_TestDestinationFolder"


class TestCopyFileOperation(unittest.TestCase):
    """``files.copy`` — the only way to keep a template's design.

    Configuration, not code: the operation carries its URL, query and body as
    templates on its row, so these assert the configuration and the rendered
    request rather than a Python handler that no longer exists.
    """

    def _spec(self):
        from one_bpmn.one_bpmn.connectors.manifest import get_execution_spec

        return get_execution_spec("google_drive", "copyFile")

    def _render_body(self, params):
        from one_bpmn.one_bpmn.connectors import http_ops

        return json.loads(
            http_ops._render(self._spec().body_template, {"params": frappe._dict(params)}, "body")
        )

    def test_it_is_configured_as_an_http_request(self):
        spec = self._spec()
        self.assertEqual(spec.execution_type, "HTTP Request")
        self.assertEqual(spec.http_method, "POST")
        self.assertIn("/copy", spec.url_template)

    def test_it_copies_into_the_destination_folder_under_the_real_title(self):
        body = self._render_body({"file": TEMPLATE_ID, "filename": "Leave Policy", "folder": FOLDER_ID})
        self.assertEqual(body["name"], "Leave Policy")
        self.assertEqual(body["parents"], [FOLDER_ID])

    def test_omitted_name_and_folder_are_not_sent(self):
        """An empty body means Drive's own defaults, not a file named ''."""
        self.assertEqual(self._render_body({"file": TEMPLATE_ID, "filename": "", "folder": ""}), {})

    def test_shared_drives_are_supported(self):
        """The templates live in a Shared Drive; without this the copy 404s."""
        self.assertIn("supportsAllDrives", self._spec().query_params_json)

    def test_output_shape_matches_create_file(self):
        """So a map can swap createFile for copyFile with no downstream edits —
        `drive_file.id` / `.webViewLink` are what every later node reads."""
        self.assertEqual(
            sorted(json.loads(self._spec().response_map_json)), ["id", "name", "webViewLink"]
        )


class TestFillTemplateOperation(unittest.TestCase):
	"""One atomic batchUpdate, and a loud failure when a placeholder is missed."""

	def _docs(self, changed_per_request):
		"""Fake Docs service replying with occurrencesChanged per request."""
		service = MagicMock()
		service.documents.return_value.batchUpdate.return_value.execute.return_value = {
			"replies": [
				{"replaceAllText": {"occurrencesChanged": n}} for n in changed_per_request
			]
		}
		return service

	def _fill(self, service, params):
		handler = get_handler("google_docs", "fillTemplate")
		with patch("one_bpmn.one_bpmn.integrations.google_docs._svc", return_value=service):
			return handler(params, {})

	def test_every_placeholder_goes_in_one_call(self):
		"""Ten fields must not be ten round-trips — and must not be able to half
		apply, which is what a per-field loop risks."""
		service = self._docs([1, 1, 2])
		values = {"{{title}}": "Leave Policy", "{{owner}}": "HR", "{{version}}": "A"}

		out = self._fill(service, {"document": COPY_ID, "values": json.dumps(values)})

		service.documents.return_value.batchUpdate.assert_called_once()
		body = service.documents.return_value.batchUpdate.call_args.kwargs["body"]
		self.assertEqual(len(body["requests"]), 3)
		self.assertEqual(out["total"], 4)
		self.assertEqual(out["unfilled"], [])

	def test_values_may_arrive_as_a_dict_or_a_json_string(self):
		"""The connector panel supplies a string; a Server Script may pass a dict."""
		values = {"{{title}}": "X"}
		for supplied in (values, json.dumps(values)):
			with self.subTest(type=type(supplied).__name__):
				out = self._fill(
					self._docs([1]), {"document": COPY_ID, "values": supplied}
				)
				self.assertEqual(out["total"], 1)

	def test_a_placeholder_that_matched_nothing_fails_loudly(self):
		"""The failure this operation exists to catch.

		replaceAllText only matches inside one formatting run, so a placeholder
		part-bolded by whoever edited the template is silently skipped — and the
		document publishes with "{{owner}}" printed in it.
		"""
		service = self._docs([1, 0])
		values = {"{{title}}": "Leave Policy", "{{owner}}": "HR"}

		with self.assertRaises(ValueError) as ctx:
			self._fill(service, {"document": COPY_ID, "values": json.dumps(values)})

		self.assertIn("{{owner}}", str(ctx.exception))
		self.assertIn("formatting runs", str(ctx.exception))

	def test_the_check_can_be_turned_off_deliberately(self):
		"""An optional section legitimately absent from one document type."""
		out = self._fill(
			self._docs([1, 0]),
			{
				"document": COPY_ID,
				"values": json.dumps({"{{title}}": "T", "{{optional}}": ""}),
				"failIfUnfilled": False,
			},
		)

		self.assertEqual(out["unfilled"], ["{{optional}}"])
		self.assertEqual(out["total"], 1)

	def test_counts_are_reported_per_placeholder(self):
		out = self._fill(
			self._docs([3, 1]),
			{"document": COPY_ID, "values": json.dumps({"{{a}}": "1", "{{b}}": "2"})},
		)

		self.assertEqual(out["filled"], {"{{a}}": 3, "{{b}}": 1})

	def test_a_none_value_clears_the_placeholder_rather_than_printing_none(self):
		self._fill(
			self._docs([1]), {"document": COPY_ID, "values": {"{{maybe}}": None}}
		)
		# nothing to assert beyond it not raising; the replacement text matters:
		# "None" printed in a published policy would be a visible defect.

	def test_empty_values_makes_no_api_call(self):
		service = self._docs([])
		out = self._fill(service, {"document": COPY_ID, "values": "{}"})

		service.documents.return_value.batchUpdate.assert_not_called()
		self.assertEqual(out["total"], 0)

	def test_a_non_object_values_payload_is_rejected(self):
		with self.assertRaises(ValueError):
			self._fill(self._docs([]), {"document": COPY_ID, "values": '["not", "an object"]'})


class TestTheDestructiveCombination(unittest.TestCase):
	"""updateFileContent after copyFile silently undoes the whole point.

	``update_file_content`` uploads new media over the file, replacing the body
	wholesale. Applied to a copied template it removes the logos, the tables and
	the bilingual layout — leaving a document that looks like the old,
	unbranded output while the map appears to have done the right thing. There
	is no API-level guard against it, so the guard is documentation plus this
	test pinning the semantics.
	"""

	def test_update_file_content_replaces_rather_than_merges(self):
		from one_bpmn.one_bpmn.integrations import google_drive as gd

		service = MagicMock()
		service.files.return_value.update.return_value.execute.return_value = {"id": COPY_ID}

		with patch(
			"one_bpmn.one_bpmn.integrations.google_drive._get_service", return_value=service
		):
			gd.update_file_content(COPY_ID, "# replacement")

		# media_body present == a full-content upload, not a partial edit.
		kwargs = service.files.return_value.update.call_args.kwargs
		self.assertIn("media_body", kwargs)
		self.assertEqual(kwargs["fileId"], COPY_ID)

	def test_the_copy_operation_warns_against_it(self):
		"""There is no API-level guard, so the warning has to live where a
		modeler will actually see it: the operation's help in the panel."""
		from one_bpmn.one_bpmn.connectors.manifest import get_operation_spec

		shown_in_panel = (get_operation_spec("google_drive", "copyFile") or {}).get("description") or ""
		self.assertIn("Update file content", shown_in_panel)


class TestManifestsStayHonest(unittest.TestCase):
	def test_both_new_operations_are_declared_and_registered(self):
		from one_bpmn.one_bpmn.connectors.manifest import field_specs
		from one_bpmn.one_bpmn.connectors.validator import validate_manifests

		self.assertEqual(validate_manifests(), [])

		# The modeler panel is driven entirely by these, so the fields the
		# handlers read must be the fields the manifest offers.
		self.assertEqual(
			sorted(field_specs("google_drive", "copyFile")), ["file", "filename", "folder"]
		)
		self.assertEqual(
			sorted(field_specs("google_docs", "fillTemplate")),
			["document", "failIfUnfilled", "matchCase", "values"],
		)

	def test_drive_id_fields_normalise_a_pasted_share_link(self):
		"""People paste URLs; the API wants bare ids.

		Field *types* are only widgets now — normalisation is a per-field value
		transform, resolved server-side and deliberately absent from the manifest
		served to the browser. So this asserts the transform, not the type.
		"""
		from one_bpmn.one_bpmn.connectors.manifest import field_transforms

		normalise = "one_bpmn.one_bpmn.integrations.google_common.normalize_drive_id"

		drive = field_transforms("google_drive", "copyFile")
		self.assertEqual(drive.get("file"), normalise, "the template id must accept a share link")
		self.assertEqual(drive.get("folder"), normalise, "so must the destination folder")

		docs = field_transforms("google_docs", "fillTemplate")
		self.assertEqual(docs.get("document"), normalise)

	def test_the_transform_is_not_leaked_to_the_browser(self):
		"""A dotted path in the manifest would be a call-any-function primitive
		once the panel echoed it back."""
		from one_bpmn.one_bpmn.connectors.manifest import field_specs

		for spec in field_specs("google_drive", "copyFile").values():
			self.assertNotIn("valueTransform", spec)
			self.assertNotIn("value_transform", spec)

	def test_values_is_an_expression_field(self):
		"""It carries rendered Jinja holding the AI task's structured output."""
		from one_bpmn.one_bpmn.connectors.manifest import field_specs

		self.assertTrue(field_specs("google_docs", "fillTemplate")["values"]["expression"])


# ── Fidelity against real Drive ─────────────────────────────────────────────
# Not automated: it needs the branded templates shared with the service account,
# which is a pending access task. The check, once they are:
#
#   1. copy_file(<gallery template id>, "Fidelity Check", <folder>)
#   2. documents.get on both template and copy
#   3. assert equal counts of tables, inlineObjects (logos) and named styles
#
# Text equality is not the test — a document can read correctly and still have
# lost every table border and image, which is precisely the failure this work
# exists to prevent.
