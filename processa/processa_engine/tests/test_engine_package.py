# Copyright (c) 2026, one-fm and contributors
"""The engine package: task type labels come from one table, and the class-level patches apply on import."""

from types import SimpleNamespace

from frappe.tests.utils import FrappeTestCase

from processa.processa_engine import engine
from processa.processa_engine.engine import spiff_patches


def _task_of(spec_class):
	return SimpleNamespace(task_spec=spec_class.__new__(spec_class))


class TestTaskTypeLabels(FrappeTestCase):
	def test_labels_and_order_are_pinned(self):
		self.assertEqual(
			[label for _cls, label in engine.TASK_TYPE_LABELS],
			[
				"User Task",
				"Script Task",
				"Service Task",
				"Manual Task",
				"Send Task",
				"Receive Task",
				"Business Rule Task",
				"Exclusive Gateway",
				"Parallel Gateway",
				"Inclusive Gateway",
			],
		)

	def test_each_row_labels_its_own_class(self):
		for spec_class, label in engine.TASK_TYPE_LABELS:
			with self.subTest(label=label):
				self.assertEqual(engine.get_task_type_label(_task_of(spec_class)), label)

	def test_a_new_row_labels_a_new_type(self):
		class CustomTask:
			pass

		self.assertEqual(engine.get_task_type_label(_task_of(CustomTask)), "CustomTask")
		original = engine.helpers.TASK_TYPE_LABELS
		engine.helpers.TASK_TYPE_LABELS = (*original, (CustomTask, "Custom Task"))
		try:
			self.assertEqual(engine.get_task_type_label(_task_of(CustomTask)), "Custom Task")
		finally:
			engine.helpers.TASK_TYPE_LABELS = original


class TestSpiffPatches(FrappeTestCase):
	def test_class_level_patches_are_applied(self):
		self.assertIs(engine.AdHocSubprocessSpec.path_complete, spiff_patches._safe_path_complete)
		self.assertIs(
			spiff_patches._EventBasedGateway._predict_hook, spiff_patches._safe_eventgateway_predict_hook
		)
