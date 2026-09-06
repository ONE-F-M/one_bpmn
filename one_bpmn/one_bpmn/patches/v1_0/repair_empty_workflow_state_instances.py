import frappe


def execute():
	"""Repair BPMN Process Instances stranded with an empty ``workflow_state``.

	Root cause (fixed in code): ``trigger._maybe_start_instance`` inserted the
	instance with ``status="Active"``, while ``start_queued_instance()`` only
	runs ``start()`` for ``status="Queued"``. So ``start()`` — the only place
	that compiles the spec and writes ``workflow_state`` — was skipped, leaving
	an Active/Errored instance with no state. Actioning the linked document then
	failed with "Workflow state is missing. The instance may be corrupted."

	This patch repairs the stranded rows. It NEVER touches the linked business
	documents (Work Item, etc.) — those are a separate doctype, referenced only
	by ``context_docname``:

	  * Instance's process_model is in ``RESTART_MODELS`` -> re-run ``start()``
	    so the instance becomes a live process again. This performs the first
	    engine pass that never ran, which creates the initial user task/
	    assignment and dispatches any start-path service tasks (e.g.
	    notifications). That is the step that was skipped at creation, not
	    new/duplicate work.
	  * Every other empty instance -> Cancel it so it stops erroring. Nothing is
	    lost — it carried no process state. This deliberately does NOT restart
	    other processes (e.g. old Software Development v1/v2, CTC) to avoid
	    firing their start-path notifications for stale documents.

	``RESTART_MODELS`` is an explicit allowlist so restart never fans out beyond
	the process(es) we intend to revive. Add a model name here to revive it.

	Idempotent: instances that already have a ``workflow_state`` are skipped, so
	re-running the patch (or a later migrate) is a no-op for already-repaired
	rows. Each instance is committed independently and failures are logged, so a
	single bad instance cannot abort the migrate.
	"""
	from one_bpmn.one_bpmn.trigger import start_queued_instance

	# Only these process models are revived; all other empty instances are
	# cancelled. Keep this tight — restart re-runs a process from its start.
	RESTART_MODELS = {"Software Development v3"}

	names = frappe.get_all(
		"BPMN Process Instance",
		filters={"status": ["in", ["Queued", "Active", "Errored"]]},
		pluck="name",
	)

	repaired = cancelled = skipped = failed = 0

	for name in names:
		inst = frappe.db.get_value(
			"BPMN Process Instance",
			name,
			["workflow_state", "process_model"],
			as_dict=True,
		)
		# Only the corrupted rows (empty / NULL workflow_state).
		if inst.workflow_state:
			skipped += 1
			continue

		try:
			if inst.process_model in RESTART_MODELS:
				# Put it in the state start_queued_instance expects, then run
				# the exact production start path (keeps the instance's own
				# initiated_by; runs as Administrator to avoid disabled-user
				# issues during migrate).
				frappe.db.set_value(
					"BPMN Process Instance", name, "status", "Queued",
					update_modified=False,
				)
				start_queued_instance(name, run_as_user="Administrator")
				repaired += 1
			else:
				frappe.db.set_value(
					"BPMN Process Instance", name, "status", "Cancelled",
					update_modified=False,
				)
				cancelled += 1
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			# Leave it Errored (still empty) so a later migrate can retry it.
			frappe.db.set_value(
				"BPMN Process Instance", name, "status", "Errored",
				update_modified=False,
			)
			frappe.db.commit()
			frappe.log_error(
				title=f"repair_empty_workflow_state: {name}",
				message=frappe.get_traceback(),
			)
			failed += 1

	frappe.logger().info(
		"repair_empty_workflow_state_instances: "
		f"repaired={repaired} cancelled={cancelled} "
		f"skipped={skipped} failed={failed}"
	)
