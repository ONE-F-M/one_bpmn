# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

import uuid
import frappe
from frappe import _


@frappe.whitelist()
def save_process_model(
	model_name: str,
	xml_content: str,
	process: str = None,
	description: str = None
) -> dict:
	"""
	Save or update a BPMN process model.

	Args:
		model_name: Name / title of the process model (maps to 'title' field)
		xml_content: BPMN XML content (maps to 'bpmn_xml' field)
		process: Legacy param (ignored — kept for frontend compat)
		description: Optional description

	Returns:
		dict with name and version of saved model
	"""
	if not model_name or not xml_content:
		frappe.throw(_("Model name and XML content are required"))

	# Check if model exists (title is the autoname)
	existing = frappe.db.exists("BPMN Process Model", model_name)

	if existing:
		# Update existing model
		doc = frappe.get_doc("BPMN Process Model", model_name)
		doc.check_permission("write")
		doc.bpmn_xml = xml_content
		if description is not None:
			doc.description = description
		doc.save()
	else:
		# Create new model
		doc = frappe.new_doc("BPMN Process Model")
		doc.title = model_name
		doc.process_name = process
		doc.bpmn_xml = xml_content
		doc.description = description or ""
		doc.version = 1
		doc.process_id = str(uuid.uuid4())
		doc.insert()

	return {
		"name": doc.name,
		"model_name": doc.title,
		"version": doc.version,
		"is_active": doc.is_active
	}


@frappe.whitelist()
def get_process_model(name: str) -> dict:
	"""
	Get a process model by name.

	Args:
		name: Name of the process model

	Returns:
		dict with model details
	"""
	if not name:
		frappe.throw(_("Model name is required"))

	doc = frappe.get_doc("BPMN Process Model", name)
	doc.check_permission("read")

	return {
		"name": doc.name,
		"model_name": doc.title,
		"title": doc.title,
		"process_id": doc.process_id,
		"description": doc.description,
		"xml_content": doc.bpmn_xml,
		"bpmn_xml": doc.bpmn_xml,
		"version": doc.version,
		"is_active": doc.is_active,
		"category": doc.category,
		"modified": doc.modified,
		"owner": doc.owner
	}


@frappe.whitelist()
def list_process_models() -> list:
	"""
	List all process models accessible to the current user.

	Returns:
		list of process model summaries
	"""
	models = frappe.get_list(
		"BPMN Process Model",
		fields=["name", "title", "process_id", "description", "version", "is_active", "category", "modified", "owner"],
		order_by="modified desc"
	)

	# Add model_name alias for frontend compat
	for m in models:
		m["model_name"] = m["title"]

	return models


@frappe.whitelist()
def list_processes() -> list:
	"""
	List all Process records that have BPMN diagrams or are accessible for creating diagrams.

	Returns:
		list of Process records with diagram counts
	"""
	# Get all processes with their diagram counts
	processes = frappe.get_list(
		"Process",
		fields=["name", "process_name", "process_owner", "process_owner_name", "business_analyst", "business_analyst_name", "description", "modified", "creation"],
		order_by="modified desc"
	)

	# Get diagram counts per process
	diagram_counts = frappe.get_all(
		"BPMN Process Model",
		fields=["process_name", "count(*) as count"],
		group_by="process_name"
	)
	count_map = {d["process_name"]: d["count"] for d in diagram_counts}

	for proc in processes:
		proc["diagram_count"] = count_map.get(proc["name"], 0)

		# Get most recent diagram status and modified time for this process
		latest_diagram = frappe.db.get_value(
			"BPMN Process Model",
			filters={"process_name": proc["name"]},
			fieldname=["is_active", "modified"],
			order_by="modified desc",
			as_dict=True
		)
		proc["status"] = "Active" if (latest_diagram and latest_diagram.get("is_active")) else "No Diagrams"
		proc["last_modified"] = latest_diagram.get("modified") if latest_diagram else proc["modified"]

	return processes


@frappe.whitelist()
def get_process_diagrams(process: str) -> dict:
	"""
	Get all diagrams for a specific process.

	Args:
		process: Name of the Process

	Returns:
		dict with process details and list of diagrams
	"""
	if not process:
		frappe.throw(_("Process name is required"))

	# Get process details
	proc = frappe.get_doc("Process", process)
	proc.check_permission("read")

	# Get diagrams filtered by process
	diagrams = frappe.get_list(
		"BPMN Process Model",
		filters={"process_name": process},
		fields=["name", "title", "process_id", "description", "version", "is_active", "modified"],
		order_by="modified desc"
	)

	# Add model_name alias for frontend compat
	for d in diagrams:
		d["model_name"] = d["title"]
		d["status"] = "Active" if d["is_active"] else "Inactive"

	return {
		"name": proc.name,
		"process_name": proc.process_name,
		"process_owner": proc.process_owner,
		"process_owner_name": proc.process_owner_name,
		"description": proc.description,
		"diagrams": diagrams
	}


@frappe.whitelist()
def update_diagram_order(process: str, order: list) -> dict:
	"""
	Update the display order of diagrams within a process.
	NOTE: display_order field was removed. This is now a no-op kept for frontend compat.

	Args:
		process: Name of the Process
		order: List of diagram names in desired order

	Returns:
		dict with success status
	"""
	return {"success": True}


@frappe.whitelist()
def delete_diagram(name: str) -> dict:
	"""
	Delete a BPMN process model diagram.

	Args:
		name: Name of the diagram to delete

	Returns:
		dict with success status
	"""
	if not name:
		frappe.throw(_("Diagram name is required"))

	doc = frappe.get_doc("BPMN Process Model", name)
	doc.check_permission("delete")
	doc.delete()

	return {"success": True}


# ============================================
# Shape Library API
# ============================================

@frappe.whitelist()
def get_shape_libraries() -> list:
	"""
	Get all shape libraries with their shapes.

	Returns:
		list of libraries with nested shapes
	"""
	libraries = frappe.get_list(
		"BPMN Shape Library",
		fields=["name", "library_name", "description", "icon", "display_order"],
		order_by="display_order asc"
	)

	# Get shapes for each library
	for lib in libraries:
		lib["shapes"] = frappe.get_list(
			"BPMN Custom Shape",
			filters={"library": lib["name"]},
			fields=["name", "shape_name", "shape_type", "svg_content", "display_order"],
			order_by="display_order asc"
		)

	return libraries


@frappe.whitelist()
def create_shape_library(library_name: str, description: str = None, icon: str = "folder") -> dict:
	"""
	Create a new shape library.

	Args:
		library_name: Name of the library
		description: Optional description
		icon: Lucide icon name

	Returns:
		dict with library details
	"""
	if not library_name:
		frappe.throw(_("Library name is required"))

	# Check if library already exists
	if frappe.db.exists("BPMN Shape Library", library_name):
		frappe.throw(_("Library '{0}' already exists").format(library_name))

	# Get next display order
	max_order = frappe.db.get_value(
		"BPMN Shape Library",
		fieldname="display_order",
		order_by="display_order desc"
	) or 0

	doc = frappe.new_doc("BPMN Shape Library")
	doc.library_name = library_name
	doc.description = description or ""
	doc.icon = icon
	doc.display_order = max_order + 1
	doc.insert()

	return {
		"name": doc.name,
		"library_name": doc.library_name,
		"description": doc.description,
		"icon": doc.icon
	}


@frappe.whitelist()
def delete_shape_library(name: str) -> dict:
	"""
	Delete a shape library and all its shapes.

	Args:
		name: Name of the library to delete

	Returns:
		dict with success status
	"""
	if not name:
		frappe.throw(_("Library name is required"))

	# Delete all shapes in the library first
	shapes = frappe.get_all("BPMN Custom Shape", filters={"library": name})
	for shape in shapes:
		frappe.delete_doc("BPMN Custom Shape", shape.name)

	# Delete the library
	doc = frappe.get_doc("BPMN Shape Library", name)
	doc.check_permission("delete")
	doc.delete()

	return {"success": True}


@frappe.whitelist()
def upload_shape(
	library: str,
	shape_name: str,
	svg_content: str,
	shape_type: str = "decorative"
) -> dict:
	"""
	Upload a new custom shape.

	Args:
		library: Name of the parent library
		shape_name: Name of the shape
		svg_content: SVG markup
		shape_type: 'decorative' or 'bpmn_element'

	Returns:
		dict with shape details
	"""
	if not library or not shape_name or not svg_content:
		frappe.throw(_("Library, shape name, and SVG content are required"))

	# Validate library exists
	if not frappe.db.exists("BPMN Shape Library", library):
		frappe.throw(_("Library '{0}' does not exist").format(library))

	# Validate shape type
	if shape_type not in ["decorative", "bpmn_element"]:
		frappe.throw(_("Shape type must be 'decorative' or 'bpmn_element'"))

	# Get next display order within library
	max_order = frappe.db.get_value(
		"BPMN Custom Shape",
		filters={"library": library},
		fieldname="display_order",
		order_by="display_order desc"
	) or 0

	doc = frappe.new_doc("BPMN Custom Shape")
	doc.library = library
	doc.shape_name = shape_name
	doc.svg_content = svg_content
	doc.shape_type = shape_type
	doc.display_order = max_order + 1
	doc.insert()

	return {
		"name": doc.name,
		"shape_name": doc.shape_name,
		"library": doc.library,
		"shape_type": doc.shape_type
	}


@frappe.whitelist()
def delete_shape(name: str) -> dict:
	"""
	Delete a custom shape.

	Args:
		name: Name of the shape to delete

	Returns:
		dict with success status
	"""
	if not name:
		frappe.throw(_("Shape name is required"))

	doc = frappe.get_doc("BPMN Custom Shape", name)
	doc.check_permission("delete")
	doc.delete()

	return {"success": True}


@frappe.whitelist()
def list_process_instances(filters=None, limit_start=0, limit_page_length=20, order_by="creation desc"):
	"""
	List BPMN process instances with their active tasks joined as 'current_step'.
	"""
	import json
	
	if isinstance(filters, str):
		filters = json.loads(filters)

	instances = frappe.get_list(
		"BPMN Process Instance",
		fields=["name", "process_model", "status", "context_doctype", "context_docname", "started_at", "initiated_by"],
		filters=filters,
		limit_start=limit_start,
		limit_page_length=limit_page_length,
		order_by=order_by
	)

	if instances:
		instance_names = [d.name for d in instances]
		tasks = frappe.get_all(
			"BPMN Active Task",
			filters={"parent": ["in", instance_names], "parenttype": "BPMN Process Instance"},
			fields=["parent", "task_name", "status"]
		)
		
		from collections import defaultdict
		task_map = defaultdict(list)
		for t in tasks:
			if t.status == "Waiting" or not t.status:
				task_map[t.parent].append(t.task_name)
			
		for d in instances:
			d.current_step = ", ".join(task_map.get(d.name, []))

	return instances


@frappe.whitelist()
def get_process_instance_details(instance_id: str) -> dict:
	"""
	Get details of a specific BPMN Process Instance.
	"""
	if not instance_id:
		frappe.throw(_("Instance ID is required"))

	instance = frappe.get_doc("BPMN Process Instance", instance_id)
	instance.check_permission("read")

	# Prepare instance data
	data = {
		"name": instance.name,
		"process_model": instance.process_model,
		"status": instance.status,
		"initiated_by": instance.initiated_by,
		"started_at": instance.started_at,
		"completed_at": instance.completed_at,
		"context_doctype": instance.context_doctype,
		"context_docname": instance.context_docname,
		"active_tasks": []
	}

	# Get active tasks
	for task in instance.active_tasks:
		if task.status and task.status != "Waiting":
			continue
			
		data["active_tasks"].append({
			"task_id": task.task_id,
			"task_name": task.task_name,
			"task_type": task.task_type,
			"status": task.status,
			"started_at": task.started_at,
			"assigned_role": task.assigned_role,
			"assigned_user": task.assigned_user,
			"target_doctype": task.target_doctype,
			"target_docname": task.target_docname,
			"timer_duration": task.timer_duration
		})

	return data


@frappe.whitelist()
def get_activity_logs(instance_id: str, limit_start=0, limit_page_length=20) -> list:
	"""
	Get paginated activity logs for a BPMN Process Instance.
	"""
	if not instance_id:
		frappe.throw(_("Instance ID is required"))
		
	import json
	if isinstance(limit_start, str):
		limit_start = int(limit_start)
	if isinstance(limit_page_length, str):
		limit_page_length = int(limit_page_length)

	logs = frappe.get_list(
		"BPMN Activity Log",
		filters={"instance": instance_id},
		fields=["name", "task_id", "task_name", "action", "timestamp", "user", "data"],
		order_by="timestamp desc",
		limit_start=limit_start,
		limit_page_length=limit_page_length
	)

	return logs
