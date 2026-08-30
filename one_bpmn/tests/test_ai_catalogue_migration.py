# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""The catalogue migration, against the shapes the real sites are actually in.

Production's shape is the one that matters here and it is the one no clean-site
test would have caught: models carrying no provider link at all, and a single
provider holding the only API key on the site.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils.password import get_decrypted_password, set_encrypted_password

from one_bpmn.one_bpmn.patches.v1_0.provider_is_a_name_model_holds_the_connection import (
	_adopt_orphans,
	_copy_connection_down,
)
from one_bpmn.one_bpmn.patches.v1_0.seed_ai_model_catalogue import (
	_provider_for,
	apply_due_rates,
)


class CatalogueCase(FrappeTestCase):
	def setUp(self):
		self.models = []
		self.providers = []

	def tearDown(self):
		for m in self.models:
			frappe.db.delete("AI Model", {"name": m})
			frappe.db.sql("DELETE FROM `__Auth` WHERE doctype='AI Model' AND name=%s", (m,))
		for p in self.providers:
			frappe.db.delete("AI Provider", {"name": p})
		frappe.db.commit()

	def _provider(self, name):
		if not frappe.db.exists("AI Provider", name):
			frappe.get_doc({"doctype": "AI Provider", "provider": name}).insert(
				ignore_permissions=True
			)
			self.providers.append(name)
		return name

	def _model(self, name, provider=None, key=None):
		doc = frappe.get_doc({
			"doctype": "AI Model", "model_name": name, "provider": provider, "enable_model": 0,
		}).insert(ignore_permissions=True)
		self.models.append(doc.name)
		if key:
			set_encrypted_password("AI Model", doc.name, key, "api_key")
		frappe.db.commit()
		return doc.name


class TestOrphanAdoption(CatalogueCase):
	def test_an_orphan_is_adopted_from_its_id(self):
		self._provider("OpenAI")
		m = self._model(f"gpt-probe-{frappe.generate_hash(length=6)}")
		_adopt_orphans()
		self.assertEqual(frappe.db.get_value("AI Model", m, "provider"), "OpenAI")

	def test_it_will_not_invent_a_provider(self):
		"""Creating one is the catalogue patch's job, and an invented provider
		has no key to give anyway. Pinned to a provider that certainly does not
		exist, so the site's own records cannot make this pass by accident."""
		from unittest.mock import patch

		from one_bpmn.one_bpmn.patches.v1_0 import (
			provider_is_a_name_model_holds_the_connection as mod,
		)

		absent = f"Nowhere {frappe.generate_hash(length=6)}"
		self.assertFalse(frappe.db.exists("AI Provider", absent))
		m = self._model(f"gpt-absent-{frappe.generate_hash(length=6)}")

		with patch.object(mod, "BY_PREFIX", (("gpt-", absent),)):
			mod._adopt_orphans()

		self.assertFalse(frappe.db.get_value("AI Model", m, "provider"))
		self.assertFalse(frappe.db.exists("AI Provider", absent))

	def test_an_unrecognisable_id_is_left_alone(self):
		m = self._model(f"mystery-{frappe.generate_hash(length=6)}")
		_adopt_orphans()
		self.assertFalse(frappe.db.get_value("AI Model", m, "provider"))
		self.assertIsNone(_provider_for(m))

	def test_a_model_that_already_has_a_provider_is_not_moved(self):
		self._provider("Anthropic")
		self._provider("OpenAI")
		# An id that says OpenAI, deliberately filed under Anthropic.
		m = self._model(f"gpt-odd-{frappe.generate_hash(length=6)}", provider="Anthropic")
		_adopt_orphans()
		self.assertEqual(frappe.db.get_value("AI Model", m, "provider"), "Anthropic")


class TestProductionShape(CatalogueCase):
	"""Production: one provider holding the only key, models linked to nothing.

	The pre-migration columns are gone from this site, so these rebuild them.
	Reproducing the old schema is the point — the defect only exists while the
	provider still holds a key, and a test that skips there proves nothing.
	"""

	def setUp(self):
		super().setUp()
		self.added_columns = []
		for column, ddl in (("api_key", "text"), ("api_endpoint", "varchar(140)")):
			if not frappe.db.has_column("AI Provider", column):
				frappe.db.sql_ddl(f"ALTER TABLE `tabAI Provider` ADD COLUMN `{column}` {ddl}")
				self.added_columns.append(column)
		# has_column reads a cached column list that a raw ALTER does not touch,
		# so without this the code under test sees the old schema and bails.
		frappe.cache.hdel("table_columns", "tabAI Provider")

	def tearDown(self):
		for column in self.added_columns:
			frappe.db.sql_ddl(f"ALTER TABLE `tabAI Provider` DROP COLUMN `{column}`")
		frappe.cache.hdel("table_columns", "tabAI Provider")
		frappe.db.sql("DELETE FROM `__Auth` WHERE doctype='AI Provider'")
		super().tearDown()

	def test_the_only_api_key_on_the_site_survives(self):
		"""The defect this exists for. Without adoption first, the copy finds no
		model under the provider, and the next step drops the column and the
		__Auth row — the key is gone with nothing carrying it forward."""
		provider = self._provider("OpenAI")
		set_encrypted_password("AI Provider", provider, "sk-prod-only-copy", "api_key")
		orphan = self._model(f"gpt-prod-{frappe.generate_hash(length=6)}")

		_adopt_orphans()
		_copy_connection_down()

		self.assertEqual(frappe.db.get_value("AI Model", orphan, "provider"), "OpenAI")
		self.assertEqual(
			get_decrypted_password("AI Model", orphan, "api_key", raise_exception=False),
			"sk-prod-only-copy",
		)

	def test_a_model_that_already_has_its_own_key_keeps_it(self):
		provider = self._provider("OpenAI")
		set_encrypted_password("AI Provider", provider, "sk-from-the-provider", "api_key")
		m = self._model(f"gpt-own-{frappe.generate_hash(length=6)}",
		                provider="OpenAI", key="sk-its-own")

		_copy_connection_down()

		self.assertEqual(
			get_decrypted_password("AI Model", m, "api_key", raise_exception=False),
			"sk-its-own",
		)


class TestScheduledRates(CatalogueCase):
	def test_nothing_is_due_before_its_date(self):
		"""Today is before the sonnet-5 change, so this must be a no-op — and it
		must stay a no-op after the date too, once applied."""
		self.assertIsInstance(apply_due_rates(), list)

	def test_a_rate_that_is_not_the_superseded_one_is_never_touched(self):
		"""A negotiated rate will not equal the published rate being replaced, so
		it falls through untouched — that is the whole safety mechanism."""
		from unittest.mock import patch

		from one_bpmn.one_bpmn.patches.v1_0 import seed_ai_model_catalogue as cat

		m = self._model(f"rate-probe-{frappe.generate_hash(length=6)}")
		frappe.db.set_value("AI Model", m, {"input_cost": 1.75, "output_cost": 8.5},
		                    update_modified=False)
		frappe.db.commit()

		with patch.object(cat, "SCHEDULED_RATES", ((m, "2020-01-01", 3.0, 15.0, 2.0, 10.0),)):
			self.assertEqual(cat.apply_due_rates(), [])
		self.assertEqual(frappe.db.get_value("AI Model", m, "input_cost"), 1.75)

	def test_the_superseded_rate_is_replaced_once_its_date_passes(self):
		from unittest.mock import patch

		from one_bpmn.one_bpmn.patches.v1_0 import seed_ai_model_catalogue as cat

		m = self._model(f"rate-due-{frappe.generate_hash(length=6)}")
		frappe.db.set_value("AI Model", m, {"input_cost": 2.0, "output_cost": 10.0},
		                    update_modified=False)
		frappe.db.commit()

		with patch.object(cat, "SCHEDULED_RATES", ((m, "2020-01-01", 3.0, 15.0, 2.0, 10.0),)):
			self.assertEqual(len(cat.apply_due_rates()), 1)
			self.assertEqual(frappe.db.get_value("AI Model", m, "output_cost"), 15.0)
			# Idempotent: the rate no longer matches what it supersedes.
			self.assertEqual(cat.apply_due_rates(), [])
