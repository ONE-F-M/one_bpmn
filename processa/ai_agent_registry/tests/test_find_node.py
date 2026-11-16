import os
import stat
import tempfile
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_registry.definitions.frontend_agent import tools as frontend_tools
from processa.ai_agent_registry.definitions.shared.helpers import find_node


def fake_nvm_node(home: str, version: str) -> str:
	path = os.path.join(home, ".nvm", "versions", "node", version, "bin", "node")
	os.makedirs(os.path.dirname(path))
	with open(path, "w") as f:
		f.write("")
	os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
	return path


class TestFindNode(FrappeTestCase):
	def test_an_nvm_node_is_found_when_path_has_none(self):
		with tempfile.TemporaryDirectory() as home:
			fake_nvm_node(home, "v16.20.0")
			newest = fake_nvm_node(home, "v20.20.2")
			fake_nvm_node(home, "v18.19.1")
			with patch.dict(os.environ, {"HOME": home}), patch("shutil.which", return_value=None):
				self.assertEqual(find_node(), newest)

	def test_the_frontend_build_uses_the_shared_lookup(self):
		with patch.object(frontend_tools, "find_node", return_value=None):
			result = frontend_tools.run_build({})
		self.assertEqual(result["errors"], ["node was not found on PATH."])
