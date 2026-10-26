import re

import frappe

from one_bpmn.one_bpmn.doctype.bpmn_process_model.bpmn_process_model import (
	new_process_id,
	swap_process_id,
)

# The two ids nothing ever meant to store: the editor's blank-diagram template
# and the drawing library's own default.
GENERATED = re.compile(r"^Process_([0-9a-f]{8}|\d+)$")


def execute():
	"""Name every map's process after the map, and repoint whoever calls it.

	The id was read back out of the diagram on every save, so the readable one a
	model was created with was replaced by whatever the editor had minted. A
	Call Activity resolves its target by that id, and duplicates resolve to
	whichever row the database returns first.
	"""
	models = frappe.get_all(
		"BPMN Process Model",
		fields=["name", "process_id", "process_name", "title", "is_active"],
	)

	sharing = {}
	for model in models:
		sharing.setdefault(model.process_id, []).append(model.name)

	recompile = set()
	ambiguous = []

	for model in models:
		old_id = model.process_id or ""
		if not GENERATED.match(old_id):
			continue

		new_id = new_process_id(model.process_name or model.title)
		xml = frappe.db.get_value("BPMN Process Model", model.name, "bpmn_xml") or ""
		frappe.db.set_value(
			"BPMN Process Model",
			model.name,
			{"process_id": new_id, "bpmn_xml": swap_process_id(xml, old_id, new_id)},
			update_modified=False,
		)
		if model.is_active:
			recompile.add(model.name)

		callers = frappe.get_all(
			"BPMN Process Model",
			filters={
				"name": ["!=", model.name],
				"bpmn_xml": ["like", '%%calledElement="%s"%%' % old_id],
			},
			fields=["name", "is_active"],
		)

		# A Call Activity naming an id that several models answer to cannot be
		# repointed — there is no way to know which one it meant. It is no worse
		# off than before: it already resolved to whichever row came back first.
		if callers and len(sharing.get(old_id) or []) > 1:
			ambiguous.append((old_id, [c.name for c in callers]))
			continue
		if len(sharing.get(old_id) or []) > 1:
			continue

		for caller in callers:
			caller_xml = frappe.db.get_value("BPMN Process Model", caller.name, "bpmn_xml") or ""
			frappe.db.set_value(
				"BPMN Process Model",
				caller.name,
				"bpmn_xml",
				swap_process_id(caller_xml, old_id, new_id),
				update_modified=False,
			)
			if caller.is_active:
				recompile.add(caller.name)

	frappe.db.commit()

	if ambiguous:
		frappe.log_error(
			title="Process id repair: Call Activities left alone",
			message="\n".join(
				f"{old} was shared by several models, so {', '.join(names)} still name it"
				for old, names in ambiguous
			),
		)

	# The engine runs the compiled spec, not the diagram, so a repaired map is
	# only repaired once it is recompiled. Active models only: compiling an
	# inactive one activates it, which would retire the version now in use.
	from one_bpmn.api.compilation import compile_process_model

	for name in sorted(recompile):
		try:
			compile_process_model(name)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(
				title="Process id repair: could not recompile",
				message=f"{name}\n{frappe.get_traceback()}",
			)
