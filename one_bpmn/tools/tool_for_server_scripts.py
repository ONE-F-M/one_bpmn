"""
Frappe Server Script tools for the Logix ScriptTaskAgent.

These functions are registered as ADK tools on the LlmAgent so Logix can
read and enumerate Server Scripts during a conversation.

They run inside the Frappe request context, so `frappe` is always available.
"""

import json
import frappe


def get_server_script_content(script_name: str) -> str:
	"""
	Fetch the full Python source code of a Frappe Server Script by name.

	Use this tool when the user asks to modify, review, or extend an existing
	Server Script so you can read the current implementation before making changes.

	Args:
		script_name: The exact name (document ID) of the Server Script to fetch.

	Returns:
		The Python script content as a string, or an error message prefixed with
		"# Error:" if the script does not exist or cannot be read.
	"""
	try:
		doc = frappe.get_doc("Server Script", script_name)
		if not doc.script:
			return f"# Script '{script_name}' exists but has no content yet."
		return doc.script
	except frappe.DoesNotExistError:
		return f"# Error: Server Script '{script_name}' not found."
	except frappe.PermissionError:
		return f"# Error: No permission to read Server Script '{script_name}'."
	except Exception:
		frappe.log_error(
			title="Logix Tool - get_server_script_content",
			message=frappe.get_traceback(),
		)
		return f"# Error: Failed to fetch Server Script '{script_name}'."


def get_server_script_meta(script_name: str) -> str:
	"""
	Fetch the metadata (type, doctype, method, disabled status) of a Server Script.

	Use this when you need to understand the script's configuration (e.g. which
	DocType event it's bound to) without reading the full code.

	Args:
		script_name: The exact name (document ID) of the Server Script.

	Returns:
		A JSON string with keys: name, script_type, reference_doctype,
		doctype_event, api_method, disabled.  Returns an error string on failure.
	"""
	try:
		doc = frappe.get_doc("Server Script", script_name)
		return json.dumps({
			"name": doc.name,
			"script_type": doc.script_type,
			"reference_doctype": doc.reference_doctype or "",
			"doctype_event": doc.doctype_event or "",
			"api_method": doc.api_method or "",
			"disabled": bool(doc.disabled),
		})
	except frappe.DoesNotExistError:
		return json.dumps({"error": f"Server Script '{script_name}' not found."})
	except Exception:
		frappe.log_error(
			title="Logix Tool - get_server_script_meta",
			message=frappe.get_traceback(),
		)
		return json.dumps({"error": f"Failed to fetch metadata for '{script_name}'."})


def list_api_server_scripts() -> str:
	"""
	List all enabled API-type Server Scripts available in the system.

	Use this when the user wants to see which scripts already exist, or when
	you want to check whether a script with a similar purpose already exists
	before creating a new one.

	Returns:
		A JSON array of script names (strings), e.g. ["Check Attendance", "Validate Shift"].
		Returns an empty array on failure.
	"""
	try:
		scripts = frappe.get_all(
			"Server Script",
			filters={"script_type": "API", "disabled": 0},
			fields=["name"],
			limit_page_length=100,
			order_by="name asc",
		)
		return json.dumps([s.name for s in scripts])
	except Exception:
		frappe.log_error(
			title="Logix Tool - list_api_server_scripts",
			message=frappe.get_traceback(),
		)
		return json.dumps([])


def get_doctype_fields(doctype: str) -> str:
	"""
	Get the field names and types for a Frappe DocType.

	Use this when the user asks the script to access specific fields on a document
	and you need to confirm the exact field names available on that DocType.

	Args:
		doctype: The DocType name, e.g. "Employee", "Sales Order".

	Returns:
		A JSON array of objects with keys: fieldname, fieldtype, label, reqd.
		Returns an error object on failure.
	"""
	try:
		if not frappe.db.exists("DocType", doctype):
			return json.dumps({"error": f"DocType '{doctype}' does not exist."})

		meta = frappe.get_meta(doctype)
		fields = [
			{
				"fieldname": f.fieldname,
				"fieldtype": f.fieldtype,
				"label": f.label or f.fieldname,
				"reqd": bool(f.reqd),
			}
			for f in meta.fields
			if f.fieldtype not in ("Section Break", "Column Break", "HTML", "Heading")
		]
		return json.dumps(fields)
	except Exception:
		frappe.log_error(
			title="Logix Tool - get_doctype_fields",
			message=frappe.get_traceback(),
		)
		return json.dumps({"error": f"Failed to fetch fields for DocType '{doctype}'."})


def list_doctypes(search: str = "") -> str:
	"""
	List DocType names, optionally filtered by a search substring.

	Use this to discover the exact DocType names available before referencing one
	in a script. Pair it with ``get_doctype_fields`` to inspect a DocType's
	fields. Read-only — never modifies anything.

	Args:
		search: Optional substring to filter DocType names by (case-insensitive).
			When empty, the most-recently-modified DocTypes are returned.

	Returns:
		A JSON array of objects with keys: name, module. Excludes child tables,
		capped at 50 rows (most-recently-modified first). Returns an empty array
		on failure.
	"""
	try:
		filters = {"istable": 0}
		if search:
			filters["name"] = ["like", f"%{search}%"]
		rows = frappe.get_all(
			"DocType",
			filters=filters,
			fields=["name", "module"],
			order_by="modified desc",
			limit_page_length=50,
		)
		return json.dumps(rows)
	except Exception:
		frappe.log_error(
			title="Logix Tool - list_doctypes",
			message=frappe.get_traceback(),
		)
		return json.dumps([])
