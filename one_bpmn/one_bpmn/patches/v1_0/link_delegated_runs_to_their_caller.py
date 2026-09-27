import frappe


def execute():
	"""Give every delegated run the caller the task already recorded.

	A run started by an A2A Task executes in its own request, so the flag that
	names the running run was empty and the link was never written. The task
	holds both sides, which is enough to repair the runs already recorded.
	"""
	tasks = frappe.get_all(
		"A2A Task",
		filters={"caller_agent_run": ["is", "set"]},
		fields=["name", "agent_run", "caller_agent_run", "instance"],
		limit_page_length=0,
	)
	linked = 0
	for task in tasks:
		child = task.agent_run or _only_run_on(task.instance)
		if not child or child == task.caller_agent_run:
			continue
		task.agent_run = child
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


def _only_run_on(instance: str | None) -> str | None:
	"""The run a delegated instance produced, when the task did not record it.

	Some tasks never had their agent_run written back, so the link has to come
	from the instance the task does name. Only a single top-level run there is
	safe to claim: more than one and the task cannot say which it meant.
	"""
	if not instance:
		return None
	runs = frappe.get_all(
		"AI Agent Run",
		filters={"instance": instance, "parent_run": ["is", "not set"]},
		fields=["name"],
		limit_page_length=2,
	)
	return runs[0].name if len(runs) == 1 else None
