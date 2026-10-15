# Copyright (c) 2026, kartiksharma9319@gmail.com and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


STAGING_FIELDS = [
	"section_break_staging",
	"enable_staging_sync",
	"staging_site_url",
	"staging_api_key",
	"staging_api_secret",
]


class TestProcessaSettings(FrappeTestCase):
	def test_staging_site_fields(self):
		meta = frappe.get_meta("Processa Settings")
		fieldnames = [df.fieldname for df in meta.fields]

		for fieldname in STAGING_FIELDS:
			self.assertIn(fieldname, fieldnames, f"{fieldname} missing from Processa Settings")

		start = fieldnames.index("section_break_staging")
		self.assertEqual(fieldnames[start : start + len(STAGING_FIELDS)], STAGING_FIELDS)

		for fieldname in ("staging_site_url", "staging_api_key", "staging_api_secret"):
			self.assertEqual(
				meta.get_field(fieldname).mandatory_depends_on,
				"eval:doc.enable_staging_sync==1",
			)
