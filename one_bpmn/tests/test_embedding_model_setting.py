# The Embedding Model setting: only models that fit the stored column may be
# chosen, Disabled turns semantic search off, and the save check catches a bad
# value that reached the field without passing through the form.

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.llm_provider import embedding as E
from one_bpmn.one_bpmn.doctype.ai_memory.ai_memory import EMBEDDING_DIMENSIONS


def _options() -> list[str]:
	field = frappe.get_meta("Processa Settings").get_field("memory_embedding_model")
	return [line.strip() for line in (field.options or "").splitlines() if line.strip()]


class TestEmbeddingModelChoices(FrappeTestCase):
	def test_the_field_is_a_list_not_a_text_box(self):
		field = frappe.get_meta("Processa Settings").get_field("memory_embedding_model")
		self.assertEqual(field.fieldtype, "Select")

	def test_every_choice_fits_the_stored_column(self):
		"""A model of the wrong width does not fail on save, it fails on every
		later write, so the list itself has to be right."""
		try:
			from fastembed import TextEmbedding
		except ImportError:
			self.skipTest("fastembed is not installed")

		widths = {m["model"]: m.get("dim") for m in TextEmbedding.list_supported_models()}
		for choice in _options():
			if choice == E.SEMANTIC_DISABLED:
				continue
			self.assertIn(choice, widths, f"{choice} is not a model fastembed supports")
			self.assertEqual(widths[choice], EMBEDDING_DIMENSIONS, f"{choice} does not fit the column")

	def test_disabled_is_offered_and_the_default_is_a_real_model(self):
		options = _options()
		self.assertIn(E.SEMANTIC_DISABLED, options)
		self.assertIn(E.DEFAULT_MODEL, options)


class TestDisabledTurnsSemanticSearchOff(FrappeTestCase):
	def test_disabled_returns_nothing_to_embed_with(self):
		with patch.object(E, "model_name", return_value=E.SEMANTIC_DISABLED):
			self.assertIsNone(E.embed(["anything"]))

	def test_disabled_never_loads_a_model(self):
		with patch.object(E, "model_name", return_value=E.SEMANTIC_DISABLED), patch.object(
			E, "_vectors", side_effect=AssertionError("should not have loaded a model")
		):
			self.assertIsNone(E.embed(["anything"]))


class TestSaveCheck(FrappeTestCase):
	"""The list stops a wrong model in the form; this stops one that arrives by
	patch, fixture or API, which is the path that would otherwise leave semantic
	search off with nothing on screen to say so."""

	def _save(self, value):
		settings = frappe.get_single("Processa Settings")
		settings.memory_embedding_model = value
		settings.validate()

	def test_a_model_of_the_wrong_width_is_refused(self):
		with patch.object(E, "probe_model", return_value=EMBEDDING_DIMENSIONS * 2):
			with self.assertRaises(frappe.ValidationError) as caught:
				self._save("some/too-wide-model")
		self.assertIn(str(EMBEDDING_DIMENSIONS), str(caught.exception))

	def test_a_model_that_cannot_be_loaded_is_refused(self):
		with patch.object(E, "probe_model", side_effect=RuntimeError("no such model")):
			with self.assertRaises(frappe.ValidationError):
				self._save("does-not/exist")

	def test_a_model_of_the_right_width_is_accepted(self):
		with patch.object(E, "probe_model", return_value=EMBEDDING_DIMENSIONS):
			self._save("BAAI/bge-small-en-v1.5")

	def test_disabled_is_accepted_without_loading_anything(self):
		with patch.object(E, "probe_model", side_effect=AssertionError("should not probe")):
			self._save(E.SEMANTIC_DISABLED)

	def test_an_unchanged_field_is_not_probed(self):
		"""Editing an unrelated setting must not wait for a model to load, and a
		machine that has lost its model cache must stay configurable."""
		settings = frappe.get_single("Processa Settings")
		with patch.object(E, "probe_model", side_effect=AssertionError("should not probe")):
			settings.validate()
