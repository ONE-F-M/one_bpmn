import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from one_bpmn.one_bpmn.custom.custom_field.comment import get_comment_custom_fields

def execute():
	logger = frappe.logger("migrate_processa_comments")

	# 1. Add custom fields to Comment DocType
	logger.info("Creating custom fields for Comment DocType")
	create_custom_fields(get_comment_custom_fields())

	# 2. Migrate data from Processa Comment to Comment
	if frappe.db.table_exists("Processa Comment"):
		processa_comments = frappe.get_all(
			"Processa Comment",
			fields=[
				"name", "model", "element_id", "comment", "is_task", 
				"status", "assigned_to", "author", "creation", "owner"
			]
		)
		logger.info(f"Found {len(processa_comments)} Processa Comment records to migrate")

		for pc in processa_comments:
			# Check if already migrated to avoid duplicates
			if not frappe.db.exists("Comment", {
				"comment_type": "Comment",
				"reference_doctype": "BPMN Process Model",
				"reference_name": pc.model,
				"content": pc.comment,
				"custom_element_id": pc.element_id,
				"creation": pc.creation
			}):
				new_comment = frappe.new_doc("Comment")
				new_comment.comment_type = "Comment"
				new_comment.reference_doctype = "BPMN Process Model"
				new_comment.reference_name = pc.model
				new_comment.content = pc.comment
				new_comment.is_processa_comment = 1
				new_comment.custom_element_id = pc.element_id
				new_comment.custom_is_task = pc.is_task
				new_comment.custom_status = pc.status
				new_comment.custom_assigned_to = pc.assigned_to
				new_comment.comment_email = pc.author or pc.owner
				new_comment.creation = pc.creation
				new_comment.owner = pc.owner
				
				# Use db_insert to preserve creation timestamp and skip controller logic
				try:
					new_comment.db_insert()
					logger.info(f"Migrated Processa Comment {pc.name} -> Comment {new_comment.name}")
				except frappe.db.InternalError as e:
					if "Unknown column 'is_processa_comment'" in str(e):
						logger.warning("Column is_processa_comment missing. Running bench migrate might be needed.")
						raise

				# Also migrate any associated ToDos if it was a task
				if pc.is_task:
					frappe.db.set_value("ToDo", 
						{"reference_type": "Processa Comment", "reference_name": pc.name},
						{"reference_type": "Comment", "reference_name": new_comment.name}
					)
			else:
				equivalent_record = frappe.get_value("Comment", {
					"comment_type": "Comment",
					"reference_doctype": "BPMN Process Model",
					"reference_name": pc.model,
					"content": pc.comment,
					"custom_element_id": pc.element_id,
					"creation": pc.creation
				}, "name")
				logger.info(f"Processa Comment {pc.name} already migrated as Comment {equivalent_record}")
	else:
		logger.info("No Processa Comment table found; skipping migration")
