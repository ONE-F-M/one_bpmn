import os

from frappe.tests.utils import FrappeTestCase

PATCHES_TXT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "patches.txt")


def _count(text, needle):
	return sum(1 for line in text.splitlines() if needle in line)


class TestPatchesTxt(FrappeTestCase):
	def setUp(self):
		with open(PATCHES_TXT, encoding="utf-8") as f:
			self.text = f.read()

	def test_retired_cleanup_patches_are_not_listed(self):
		self.assertEqual(_count(self.text, "cleanup_ai_memory_store"), 0)

	def test_a2a_connector_patch_is_listed_once(self):
		self.assertEqual(_count(self.text, "add_work_item_refs_to_a2a_connector"), 1)
