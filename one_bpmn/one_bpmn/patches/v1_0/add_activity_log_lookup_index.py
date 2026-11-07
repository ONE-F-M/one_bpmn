from one_bpmn.processa_engine.doctype.bpmn_activity_log.bpmn_activity_log import on_doctype_update


def execute():
	"""Create the instance, task and action index; on_doctype_update only runs when the DocType itself syncs."""
	on_doctype_update()
