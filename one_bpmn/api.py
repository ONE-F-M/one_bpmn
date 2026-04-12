# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

import json
import uuid
from lxml import etree as ET
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
		doc.is_active = 0
		doc.process_id = str(uuid.uuid4())
		doc.check_permission("create")
		doc.insert()

	return {
		"name": doc.name,
		"model_name": doc.title,
		"version": doc.version,
		"is_active": doc.is_active
	}


@frappe.whitelist()
def import_bpmn(
	xml_content: str,
	title: str = None,
	process: str = None,
) -> dict:
	"""
	Import a BPMN XML string as a new or updated BPMN Process Model.

	The process_id is extracted from the first <bpmn:process id="…"> element in
	the XML. If a BPMN Process Model with that process_id already exists it is
	updated; otherwise a new record is created.

	Args:
		xml_content: Raw BPMN XML text (content of a .bpmn file)
		title:       Optional human-readable title. Defaults to the process_id.
		process:     Optional link to a Process DocType record.

	Returns:
		dict with name, model_name, process_id, and action ('created'|'updated')
	"""
	if not xml_content or not xml_content.strip():
		frappe.throw(_("BPMN XML content is required"))

	# --- Validate & parse XML ---
	# lxml raises TypeError when fromstring() receives a str containing an encoding
	# declaration (<?xml ... encoding="UTF-8"?>). Encoding to bytes avoids this.
	try:
		root = ET.fromstring(xml_content.strip().encode("utf-8"))
	except ET.XMLSyntaxError as exc:
		frappe.throw(_("Invalid BPMN XML: {0}").format(str(exc)))

	# Register namespaces so ElementTree can search them
	bpmn_ns = "http://www.omg.org/spec/BPMN/20100524/MODEL"

	# Accept both namespaced and bare <process> tags
	process_el = root.find(f"{{{bpmn_ns}}}process")
	if process_el is None:
		# Fallback: look without namespace (some exporters omit it)
		process_el = root.find("process")

	if process_el is None:
		frappe.throw(_(
			"Invalid BPMN XML: no <bpmn:process> element found. "
			"Please upload a valid BPMN 2.0 file."
		))

	extracted_process_id = process_el.get("id")
	if not extracted_process_id:
		frappe.throw(_("Invalid BPMN XML: <bpmn:process> element has no 'id' attribute"))

	effective_title = title or process_el.get("name") or extracted_process_id

	# --- Upsert logic: match by process_id (unique field) ---
	existing_name = frappe.db.get_value(
		"BPMN Process Model",
		{"process_id": extracted_process_id},
		"name"
	)

	if existing_name:
		doc = frappe.get_doc("BPMN Process Model", existing_name)
		doc.check_permission("write")
		doc.bpmn_xml = xml_content
		if process:
			doc.process_name = process
		# Always sync the title field so the return value is accurate
		if effective_title:
			doc.title = effective_title
		doc.save()

		# Rename the document if the human title has changed
		# (autoname only runs on insert, so we must rename manually)
		if effective_title and effective_title != doc.name:
			try:
				frappe.rename_doc(
					"BPMN Process Model",
					doc.name,
					effective_title,
					force=True,
					merge=False,
				)
				doc = frappe.get_doc("BPMN Process Model", effective_title)
			except Exception:
				# If rename fails (e.g. duplicate title), keep existing name
				pass

		action = "updated"
	else:
		doc = frappe.new_doc("BPMN Process Model")
		doc.title = effective_title
		doc.process_id = extracted_process_id
		doc.bpmn_xml = xml_content
		doc.process_name = process or None
		doc.version = 1
		doc.check_permission("create")
		doc.insert()
		action = "created"

	return {
		"name": doc.name,
		"model_name": doc.title,
		"process_id": doc.process_id,
		"action": action,
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
	# Use get_all (no default page-size cap) so the Call Activity search dialog
	# and the process-id resolver never miss records beyond Frappe's default 20.
	models = frappe.get_all(
		"BPMN Process Model",
		fields=["name", "title", "process_id", "description", "version", "is_active", "category", "modified", "owner", "process_name"],
		order_by="modified desc"
	)

	# Add model_name alias for frontend compat
	for m in models:
		m["model_name"] = m["title"]

	return models


@frappe.whitelist()
def resolve_process_model_by_id(process_id: str) -> dict:
	"""
	Resolve a process_id to the BPMN Process Model that owns it.

	Used by the Call Activity editor to navigate to the linked diagram
	without requiring the frontend to fetch and filter the entire model list.

	Args:
		process_id: The BPMN process_id attribute (e.g. "Process_abc123")

	Returns:
		dict with name, title, process_name, process_id — or empty dict if not found
	"""
	if not process_id:
		return {}

	result = frappe.db.get_value(
		"BPMN Process Model",
		filters={"process_id": process_id},
		fieldname=["name", "title", "process_name", "process_id"],
		as_dict=True,
	)
	return result or {}


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

		# Get the active model (if any) for this process
		active_model = frappe.db.get_value(
			"BPMN Process Model",
			filters={"process_name": proc["name"], "is_active": 1},
			fieldname=["name", "modified"],
			as_dict=True
		)

		if active_model:
			proc["status"] = "Active"
			proc["last_modified"] = active_model["modified"]
		elif proc["diagram_count"] > 0:
			# Models exist but none is active
			latest = frappe.db.get_value(
				"BPMN Process Model",
				filters={"process_name": proc["name"]},
				fieldname="modified",
				order_by="modified desc",
			)
			proc["status"] = "Inactive"
			proc["last_modified"] = latest or proc["modified"]
		else:
			proc["status"] = "No Diagrams"
			proc["last_modified"] = proc["modified"]

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
		order_by="is_active desc, modified desc"
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


@frappe.whitelist()
def rename_process_model(name: str, new_title: str) -> dict:
	"""
	Rename a BPMN Process Model.

	Updates the title field and renames the document (since autoname is based
	on title).

	Args:
		name: Current document name of the BPMN Process Model
		new_title: New human-readable title / name

	Returns:
		dict with new name and model_name
	"""
	if not name or not new_title:
		frappe.throw(_("Current name and new title are required"))

	new_title = new_title.strip()
	if not new_title:
		frappe.throw(_("New title cannot be empty"))

	doc = frappe.get_doc("BPMN Process Model", name)
	doc.check_permission("write")

	# Update the title field
	doc.title = new_title
	doc.save()

	# Rename the document if the title (which drives the autoname) changed
	new_name = doc.name
	if new_title != doc.name:
		try:
			actual_new_name = frappe.rename_doc(
				"BPMN Process Model",
				doc.name,
				new_title,
				force=True,
				merge=False,
			)
			new_name = actual_new_name or new_title
		except frappe.ValidationError:
			# If rename fails (e.g. duplicate), keep the existing name
			frappe.log_error(
				title="BPMN Process Model rename failed",
				message=f"Could not rename '{doc.name}' to '{new_title}'"
			)
			frappe.throw(
				_("A process model with the name '{0}' already exists").format(new_title)
			)

	return {
		"name": new_name,
		"model_name": frappe.db.get_value("BPMN Process Model", new_name, "title") or new_title,
	}


@frappe.whitelist()
def get_assignee_docfields(doctype: str) -> list:
	"""
	Safe endpoint for the BPMN editor to get all Link fields pointing to User
	for a specific Target DocType. Bypasses the strict DocField table permissions.

	Args:
		doctype: Target DocType name

	Returns:
		list of dicts with fieldname and label
	"""
	if not doctype:
		return []

	# Use frappe.get_meta to get fields safely without querying DocField directly
	try:
		meta = frappe.get_meta(doctype)
	except frappe.DoesNotExistError:
		return []

	fields = meta.get("fields", {
		"fieldtype": "Link",
		"options": "User"
	})

	return [{"fieldname": f.fieldname, "label": f.label} for f in fields]


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
def list_process_instances(filters=None, limit_start=0, limit_page_length=20, order_by="creation desc") -> list:
	"""
	List BPMN process instances with their active tasks joined as 'current_step'.
	"""
	
	if isinstance(filters, str):
		filters = json.loads(filters)
	
	if isinstance(limit_start, str):
		limit_start = int(limit_start)
	if isinstance(limit_page_length, str):
		limit_page_length = int(limit_page_length)

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
			filters={"parent": ["in", instance_names], "parenttype": "BPMN Process Instance", "status": ["in", ["Waiting", ""]]},
			fields=["parent", "task_name", "status"]
		)
		
		from collections import defaultdict
		task_map = defaultdict(list)
		for t in tasks:
			task_map[t.parent].append(t.task_name)
			
		for d in instances:
			d.current_step = ", ".join(task_map.get(d.name, []))

	return instances



# ============================================
# Server Script API
# Uses ignore_permissions so Process Owners without the Script Manager role
# can still list/create Server Scripts via the BPMN editor.
# Creation is guarded to System Manager or Script Manager only.
# ============================================


@frappe.whitelist()
def create_server_script(
	script_name: str,
	script_type: str,
	script: str,
	reference_doctype: str = None,
	doctype_event: str = None,
	api_method: str = None,
	allow_guest: int = 0,
	event_frequency: str = None,
	cron_format: str = None,
	module: str = None,
) -> dict:
	if not script_name or not script_type or not script:
		frappe.throw(_("Script name, type, and content are required"))

	if not frappe.has_permission("Server Script", "create") and \
			"System Manager" not in frappe.get_roles():
		frappe.throw(
			_("You need the Script Manager or System Manager role to create Server Scripts."),
			frappe.PermissionError,
		)

	doc = frappe.new_doc("Server Script")
	doc.__newname = script_name
	doc.script_type = script_type
	doc.script = script
	doc.disabled = 1  # disabled by default — must be manually enabled
	if reference_doctype:
		doc.reference_doctype = reference_doctype
	if doctype_event:
		doc.doctype_event = doctype_event
	if api_method:
		doc.api_method = api_method
	if allow_guest:
		doc.allow_guest = int(allow_guest)
	if event_frequency:
		doc.event_frequency = event_frequency
	if cron_format:
		doc.cron_format = cron_format
	if module:
		doc.module = module

	# Elevate to Administrator temporarily to bypass the ServerScript controller's
	# `frappe.only_for("Script Manager")` validate hook. The role guard above
	# already ensures only System Manager / Script Manager users reach this point.
	original_user = frappe.session.user
	try:
		frappe.set_user("Administrator")
		doc.insert(ignore_permissions=True)
	finally:
		frappe.set_user(original_user)

	return {"name": doc.name, "script_type": doc.script_type}


# ============================================
# Notification API
# Creates Notification documents from the BPMN Send Task dialog.
# New notifications are disabled by default (enabled when deployed).
# ============================================


@frappe.whitelist()
def create_notification(
	notification_name: str,
	channel: str,
	document_type: str,
	event: str = "New",
	subject: str = None,
	message: str = None,
	message_type: str = "Markdown",
	condition: str = None,
	module: str = None,
	# Email-specific
	sender: str = None,
	sender_email: str = None,
	attach_print: int = 0,
	print_format: str = None,
	send_system_notification: int = 0,
	# Slack-specific
	slack_webhook_url: str = None,
	# WhatsApp-specific  (Twilio integration)
	twilio_number: str = None,
	# Trigger fields
	method: str = None,
	date_changed: str = None,
	days_in_advance: int = 0,
	value_changed: str = None,
	# Recipients
	send_to_all_assignees: int = 0,
	recipients: str = None,  # JSON string of recipient rows
	# After Alert
	set_property_after_alert: str = None,
	property_value: str = None,
) -> dict:
	"""
	Create a Notification document from the BPMN Send Task dialog.

	The notification is created with enabled=0 (disabled by default).
	It should be enabled when the process is deployed.

	Args:
		notification_name: Human-readable name for the notification
		channel: Email / Slack / System Notification / SMS / WhatsApp
		document_type: The DocType this notification is linked to
		event: Trigger event (New/Save/Submit/Cancel/Days After/Days Before/Value Change/Method/Custom)
		subject: Notification subject line (Jinja template)
		message: Message body (Jinja template)
		message_type: Markdown / HTML / Plain Text
		condition: Python condition expression
		module: Module for export
		sender: Email Account link (Email channel)
		sender_email: Sender email address (Email channel)
		attach_print: Whether to attach print (Email channel)
		print_format: Print Format link (Email channel)
		send_system_notification: Also send system notification flag
		slack_webhook_url: Slack Webhook URL link (Slack channel)
		twilio_number: Communication Medium link (WhatsApp channel)
		method: Trigger method name (Method event)
		date_changed: Date field name (Days After/Before events)
		days_in_advance: Number of days (Days After/Before events)
		value_changed: Field name (Value Change event)
		send_to_all_assignees: Send to all document assignees
		recipients: JSON array of recipient row objects
		set_property_after_alert: Field to set after alert fires
		property_value: Value to set

	Returns:
		dict with name and channel
	"""
	import json as _json

	if not notification_name or not channel or not document_type:
		frappe.throw(_("Notification name, channel, and document type are required"))

	if not frappe.has_permission("Notification", "create") and \
			"System Manager" not in frappe.get_roles():
		frappe.throw(
			_("You need the System Manager role to create Notifications."),
			frappe.PermissionError,
		)

	doc = frappe.new_doc("Notification")
	doc.__newname = notification_name
	doc.subject = subject or notification_name
	doc.channel = channel
	doc.document_type = document_type
	doc.event = event or "New"
	doc.enabled = 0  # Disabled by default — enabled when deployed
	doc.message_type = message_type or "Markdown"

	if message:
		doc.message = message
	if condition:
		doc.condition = condition
	if module:
		doc.module = module

	# Email-specific fields
	if sender:
		doc.sender = sender
	if sender_email:
		doc.sender_email = sender_email
	if int(attach_print or 0):
		doc.attach_print = 1
	if print_format:
		doc.print_format = print_format
	if int(send_system_notification or 0):
		doc.send_system_notification = 1

	# Slack-specific
	if slack_webhook_url:
		doc.slack_webhook_url = slack_webhook_url

	# WhatsApp-specific (Twilio)
	if twilio_number:
		doc.twilio_number = twilio_number

	# Trigger fields
	if method:
		doc.method = method
	if date_changed:
		doc.date_changed = date_changed
	if days_in_advance:
		doc.days_in_advance = int(days_in_advance)
	if value_changed:
		doc.value_changed = value_changed

	# After Alert
	if set_property_after_alert:
		doc.set_property_after_alert = set_property_after_alert
	if property_value:
		doc.property_value = property_value

	# Recipients
	if int(send_to_all_assignees or 0):
		doc.send_to_all_assignees = 1

	if recipients:
		if isinstance(recipients, str):
			try:
				rows = _json.loads(recipients)
			except (ValueError, _json.JSONDecodeError):
				frappe.throw("Recipients must be a valid JSON array of objects.", frappe.ValidationError)
		else:
			rows = recipients

		if not isinstance(rows, list):
			frappe.throw("Recipients must be a list of objects.", frappe.ValidationError)

		for row in rows:
			if not isinstance(row, dict):
				frappe.throw("Each recipient entry must be an object.", frappe.ValidationError)
			doc.append("recipients", {
				"receiver_by_document_field": row.get("receiver_by_document_field", ""),
				"receiver_by_role": row.get("receiver_by_role", ""),
				"cc": row.get("cc", ""),
				"bcc": row.get("bcc", ""),
				"condition": row.get("condition", ""),
			})

	# Elevate to bypass permission checks in the Notification controller.
	# The role guard above already ensures only authorised users reach here.
	original_user = frappe.session.user
	try:
		frappe.set_user("Administrator")
		doc.insert(ignore_permissions=True)
	finally:
		frappe.set_user(original_user)

	return {"name": doc.name, "channel": doc.channel}


# ============================================
# Pathfinder Log — Process Editability Check
# ============================================
# The Processa BPMN editor is deployed on two sites:
#   Production (one-fm.com)        — always read-only
#   BA site (business-analyst...)  — editable only when an active Pathfinder Log exists
#
# The Pathfinder Log doctype lives in the one_fm app on Production.
# These proxy endpoints let the BA site frontend check editability
# without making cross-origin requests directly.


def _is_production_site() -> bool:
	"""Return True if the current Frappe site IS the Production instance."""
	settings = frappe.get_single("Processa Settings")
	if not settings.enabled:
		return False

	production_url = (settings.production_url or "").rstrip("/")
	if not production_url:
		# If production_url is not configured, assume we are NOT production
		# (safe default: allow the editability check to proceed).
		return False
	site_url = frappe.utils.get_url().rstrip("/")
	return site_url == production_url


def _is_local_dev_mode() -> bool:
	"""Return True when production API credentials are NOT configured.

	In local dev the one_fm app (with Pathfinder Log) lives on the same
	bench, so we can call its API directly without HTTP.
	"""
	settings = frappe.get_single("Processa Settings")
	if not settings.enabled:
		return True

	production_url = settings.production_url
	api_key = settings.production_api_key
	api_secret = settings.get_password("production_api_secret")
	return not (production_url and api_key and api_secret)



@frappe.whitelist()
def check_and_update_editor_lock(model_name: str) -> list[dict[str, str | None]]:
	"""
	Track active editors for a BPMN Process Model using Frappe cache.

	Returns a list of dictionaries for other active users, where each
	dictionary contains ``name``, ``full_name``, and ``user_image``.
	"""
	if not model_name:
		return []

	current_user = frappe.session.user
	if current_user == "Guest":
		return []

	doc = frappe.get_doc("BPMN Process Model", model_name)
	doc.check_permission("read")
	cache_key = f"bpmn_editor_lock:{model_name}"
	active_editors = frappe.cache.get_value(cache_key) or {}
	
	import time
	now = time.time()
	
	# Clean up expired heartbeats (> 45s) and identify others
	other_editors = []
	updated_editors = {}
	
	for user, timestamp in active_editors.items():
		if now - timestamp < 45:
			if user != current_user:
				other_editors.append(user)
				updated_editors[user] = timestamp
	
	# Add current user
	updated_editors[current_user] = now
	
	# Save back to cache (60s TTL)
	frappe.cache.set_value(cache_key, updated_editors, expires_in_sec=60)
	
	# Return detailed user info for other editors for better UX (avatars)
	if other_editors:
		return frappe.get_all("User", 
			filters={"name": ["in", other_editors]}, 
			fields=["name", "full_name", "user_image"]
		)
	
	return []


def _call_local_pathfinder_api(method_path: str, params: dict) -> dict:
   """Call a pathfinder API method directly (same bench, no HTTP).

   Used as a fallback in local dev when production credentials are not
   configured.
   """
   from frappe.handler import call as frappe_call
   import importlib

   # method_path looks like "one_fm.one_fm.doctype.pathfinder_log.pathfinder_api.is_process_editable"
   module_path, func_name = method_path.rsplit(".", 1)
   module = importlib.import_module(module_path)
   func = getattr(module, func_name)
   return func(**params)
   

def _call_production_api(method: str, params: dict) -> dict:
	"""
	Call a whitelisted method on the Production site using API key auth.

	Reads `production_url`, `production_api_key`, and
	`production_api_secret` from Processa Settings DocType.

	Falls back to a direct local call when credentials are not configured
	(local development mode).
	"""
	import requests

	# Local dev fallback — call directly on the same bench
	if _is_local_dev_mode():
		return _call_local_pathfinder_api(method, params)

	settings = frappe.get_single("Processa Settings")
	production_url = (settings.production_url or "").rstrip("/")
	api_key = settings.production_api_key
	api_secret = settings.get_password("production_api_secret")

	if not production_url or not api_key or not api_secret:
		frappe.throw(_(
			"Production API credentials are not configured. "
			"Please go to Processa Settings to configure the "
			"Production URL, API Key, and API Secret."
		))

	url = f"{production_url}/api/method/{method}"
	headers = {
		"Authorization": f"token {api_key}:{api_secret}",
		"Content-Type": "application/json",
	}

	try:
		resp = requests.get(url, params=params, headers=headers, timeout=10)
		resp.raise_for_status()
		data = resp.json()
		return data.get("message", data)
	except requests.exceptions.Timeout:
		frappe.throw(_("Production API request timed out. Please try again."))
	except requests.exceptions.ConnectionError:
		frappe.throw(_("Cannot reach Production site. Please check connectivity."))
	except Exception as e:
		frappe.log_error(
			title="Production API call failed",
			message=f"Method: {method}\nParams: {json.dumps(params)}\nError: {str(e)}"
		)
		frappe.throw(_("Failed to check process editability. Please try again or contact support."))


@frappe.whitelist()
def check_process_editable(process_name: str) -> dict:
	"""
	Check if a single process is editable (has an active Pathfinder Log).

	On Production: always returns editable=False.
	On BA site: proxies the call to Production's API.

	Args:
		process_name: Name of the Process record.

	Returns:
		dict with editable, pathfinder_log, workflow_state, reason
	"""
	if not process_name:
		frappe.throw(_("Process name is required"))

	if _is_production_site():
		return {
			"editable": False,
			"pathfinder_log": None,
			"workflow_state": None,
			"reason": "Production site is always read-only.",
		}

	result = _call_production_api(
		"one_fm.one_fm.doctype.pathfinder_log.pathfinder_api.is_process_editable",
		{"process_name": process_name},
	)

	# Add a human-readable reason for the frontend
	if result.get("editable"):
		result["reason"] = f"Active Pathfinder Log: {result.get('pathfinder_log')}"
	else:
		result["reason"] = "No active Pathfinder Log. Create one to enable editing."

	return result


@frappe.whitelist()
def bulk_check_processes_editable(process_names: str) -> dict:
	"""
	Batch check editability for multiple processes.

	On Production: returns all as non-editable.
	On BA site: proxies to Production's bulk API.

	Args:
		process_names: JSON-encoded list of process name strings.

	Returns:
		dict mapping process name → editability info
	"""
	import json

	# Safe JSON parsing with validation
	try:
		if isinstance(process_names, str):
			process_names_list = frappe.parse_json(process_names)
		else:
			process_names_list = process_names
	except Exception:
		frappe.throw(
			_("Invalid process_names: expected a JSON-encoded list of strings."),
			title=_("Validation Error"),
		)

	if not isinstance(process_names_list, list):
		frappe.throw(_("process_names must be a list"))

	if _is_production_site():
		return {
			pname: {
				"editable": False,
				"pathfinder_log": None,
				"workflow_state": None,
			}
			for pname in process_names_list
		}

	return _call_production_api(
		"one_fm.one_fm.doctype.pathfinder_log.pathfinder_api.bulk_check_process_editable",
		{"process_names": json.dumps(process_names_list)},
	)


# ============================================
# Diagram Version History (for visual diffing)
# ============================================

@frappe.whitelist()
def get_diagram_versions(name: str) -> list:
	"""
	Get version history for a BPMN Process Model.

	Reads from Frappe's Version table (populated automatically because
	track_changes=1 on BPMN Process Model). Filters to only include
	versions where bpmn_xml actually changed.

	Args:
		name: Document name of the BPMN Process Model

	Returns:
		list of version entries with timestamp, user, and version_name
	"""
	if not name:
		frappe.throw(_("Diagram name is required"))

	doc = frappe.get_doc("BPMN Process Model", name)
	doc.check_permission("read")

	versions = frappe.get_all(
		"Version",
		filters={"ref_doctype": "BPMN Process Model", "docname": name},
		fields=["name", "owner", "creation", "data"],
		order_by="creation desc",
		limit_page_length=50,
	)

	import json as json_mod

	result = []
	for v in versions:
		# Only include versions where bpmn_xml was changed
		try:
			data = json_mod.loads(v.data)
			has_xml_change = any(
				change[0] == "bpmn_xml" for change in data.get("changed", [])
			)
			if not has_xml_change:
				continue
		except (json_mod.JSONDecodeError, KeyError, TypeError):
			continue

		result.append({
			"version_name": v.name,
			"user": frappe.utils.get_fullname(v.owner),
			"user_email": v.owner,
			"timestamp": v.creation,
		})

	return result


@frappe.whitelist()
def get_diagram_version_xml(name: str, version_name: str) -> dict:
	"""
	Get the bpmn_xml content at a specific version point.

	Extracts the bpmn_xml value from the Version record's stored diff data.
	Uses change[2] (new value) which is the state of the XML AT that version.

	Args:
		name: Document name of the BPMN Process Model
		version_name: Name of the Version record

	Returns:
		dict with xml_content, version_name, timestamp, user
	"""
	if not name or not version_name:
		frappe.throw(_("Diagram name and version name are required"))

	doc = frappe.get_doc("BPMN Process Model", name)
	doc.check_permission("read")

	version_doc = frappe.get_doc("Version", version_name)

	import json as json_mod

	try:
		data = json_mod.loads(version_doc.data)
	except (json_mod.JSONDecodeError, TypeError):
		frappe.throw(
			_("Version data is corrupted or unavailable for '{0}'").format(version_name)
		)

	# Extract the bpmn_xml change — changed is [[fieldname, old_value, new_value], ...]
	# change[2] = new value = the XML state AT this version point
	xml_content = None
	for change in data.get("changed", []):
		if change[0] == "bpmn_xml" and len(change) >= 3:
			xml_content = change[2]
			break

	if not xml_content:
		frappe.throw(_("No BPMN XML change found in this version"))

	return {
		"xml_content": xml_content,
		"version_name": version_name,
		"timestamp": version_doc.creation,
		"user": frappe.utils.get_fullname(version_doc.owner),
	}
