"""Sites that already ran add_testing_agent_sandbox_tools get the corrected Browser Snapshot script.

The first version saved the screenshot with insert(ignore_permissions=True). Linking that script to a process map runs the
security gate, which rejects the keyword, so the map could not be saved. The tools patch rewrites all three scripts."""

from processa.patches.v1_0 import add_testing_agent_sandbox_tools


def execute():
	add_testing_agent_sandbox_tools.execute()
