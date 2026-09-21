import frappe


def execute():
	"""Give every delegated run the caller the task already recorded.

	A run started by an A2A Task executes in its own request, so the flag that
	names the running run was empty and the link was never written. The task
	holds both sides, which is enough to repair the runs already recorded.
	"""
	tasks = frappe.get_all(
		"A2A Task",
		filters={"agent_run": ["is", "set"], "caller_agent_run": ["is", "set"]},
		fields=["name", "agent_run", "caller_agent_run"],
		limit_page_length=0,
	)
	linked = 0
	for task in tasks:
		if task.agent_run == task.caller_agent_run:
			continue
		if not frappe.db.exists("AI Agent Run", task.agent_run):
			continue
		if not frappe.db.exists("AI Agent Run", task.caller_agent_run):
			continue
		if frappe.db.get_value("AI Agent Run", task.agent_run, "parent_run"):
			continue
		frappe.db.set_value(
			"AI Agent Run",
			task.agent_run,
			"parent_run",
			task.caller_agent_run,
			update_modified=False,
		)
		linked += 1

	frappe.db.commit()
	print("linked %d delegated runs to their caller, from %d tasks" % (linked, len(tasks)))
