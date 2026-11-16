"""The seeded github_video_upload connector is the one upload_videos reads, as a Bearer Token connector with no token in the seed."""

from frappe.tests import UnitTestCase

from processa.agents_sandbox.sandbox import ops
from processa.patches.v1_0 import seed_github_video_upload_connector as seed


class TestVideoUploadConnectorSeed(UnitTestCase):
	def test_it_is_the_connector_upload_videos_reads_and_it_uses_bearer_token_auth(self):
		manifest = seed.VIDEO_UPLOAD_CONNECTOR
		self.assertEqual(manifest["connectorId"], ops.UPLOAD_CONNECTOR)
		self.assertEqual(manifest["execution"]["auth"]["type"], "Bearer Token")
		self.assertEqual(manifest["operations"], [])

	def test_the_seed_carries_no_secret(self):
		text = repr(seed.VIDEO_UPLOAD_CONNECTOR).lower()
		for word in ("secret\": ", "token\": \"", "ghp_", "github_pat"):
			self.assertNotIn(word, text)
