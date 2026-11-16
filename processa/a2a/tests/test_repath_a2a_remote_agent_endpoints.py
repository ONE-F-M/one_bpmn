import frappe
from frappe.tests.utils import FrappeTestCase

from processa.patches.v1_0 import repath_a2a_remote_agent_endpoints as patch

BA_HOST = "https://business-analyst.one-fm.com/api/method/"


def make_remote_agent(name: str, endpoint_url: str) -> str:
	frappe.get_doc(
		{
			"doctype": "A2A Remote Agent",
			"name": name,
			"agent_name": name,
			"endpoint_url": endpoint_url,
			"enabled": 1,
		}
	).db_insert()
	return name


class TestRepathA2ARemoteAgentEndpoints(FrappeTestCase):
	def test_old_rpc_path_moves_to_processa_and_others_stay(self):
		old = make_remote_agent(
			"_Test Old Rpc Agent", f"{BA_HOST}one_bpmn.api.a2a_api.rpc?agent_id=a2a_parts_checker"
		)
		other = make_remote_agent("_Test Other Agent", "https://example.com/a2a/rpc")

		patch.execute()

		self.assertEqual(
			frappe.db.get_value("A2A Remote Agent", old, "endpoint_url"),
			f"{BA_HOST}processa.api.a2a.rpc?agent_id=a2a_parts_checker",
		)
		self.assertEqual(
			frappe.db.get_value("A2A Remote Agent", other, "endpoint_url"), "https://example.com/a2a/rpc"
		)

	def test_new_path_is_the_rpc_method_processa_serves(self):
		from processa.api import a2a

		self.assertIs(frappe.get_attr(patch.NEW_RPC), a2a.rpc)
