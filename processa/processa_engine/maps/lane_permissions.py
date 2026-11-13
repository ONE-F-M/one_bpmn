# Copyright (c) 2026, one-fm and contributors
"""Deploy readiness: warn when a lane's role lacks the DocType permissions its tasks need."""

import frappe
from frappe import _


PERMISSION_ORDER = ("read", "write", "create", "submit", "delete")

SCRIPT_CALL_PERMISSIONS = {
	"get_all": "read",
	"get_list": "read",
	"get_value": "read",
	"get_cached_doc": "read",
	"get_last_doc": "read",
	"exists": "read",
	"count": "read",
	"get_doc": "read",
	"set_value": "write",
	"new_doc": "create",
	"delete_doc": "delete",
}


def lane_role_permission_warnings(root, valid_roles: set) -> list:
	"""Warnings for lane roles that lack DocType permissions their tasks need."""
	bpmn_ns = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	spiff_ns = "http://spiffworkflow.org/bpmn/schema/1.0/core"
	tasks = {}
	for tag in ("userTask", "serviceTask", "scriptTask"):
		for el in root.iter(f"{{{bpmn_ns}}}{tag}"):
			tasks[el.get("id")] = el

	needs = {}
	for lane in root.iter(f"{{{bpmn_ns}}}lane"):
		role = lane.get("name", "").strip()
		if role not in valid_roles:
			continue
		for ref in lane.iter(f"{{{bpmn_ns}}}flowNodeRef"):
			task = tasks.get((ref.text or "").strip())
			if task is None:
				continue
			attrs = {k.split("}")[-1]: v for k, v in task.attrib.items() if k.startswith(f"{{{spiff_ns}}}")}
			for doctype, ptypes in _task_permission_needs(task, attrs).items():
				if frappe.db.exists("DocType", doctype):
					need = needs.setdefault((role, doctype), {"ptypes": set(), "tasks": []})
					need["ptypes"].update(ptypes)
					need["tasks"].append(task.get("name") or task.get("id"))

	items = []
	for (role, doctype), need in sorted(needs.items()):
		missing = [p for p in PERMISSION_ORDER if p in need["ptypes"] and role not in _roles_with(doctype, p)]
		if missing:
			items.append({
				"name": f"{role} on {doctype}",
				"exists": True,
				"type": "warning",
				"detail": _("Role lacks {0} permission on {1}, needed by: {2}").format(
					", ".join(missing), doctype, ", ".join(need["tasks"])
				),
			})
	return items


def _roles_with(doctype: str, ptype: str) -> set:
	"""Roles granted ptype on the DocType at permission level 0."""
	return {p.role for p in frappe.get_meta(doctype).permissions if p.get(ptype) and not p.permlevel}


def _task_permission_needs(task, attrs: dict) -> dict:
	"""Map each DocType a task acts on to the permission types it needs."""
	tag = task.tag.split("}")[-1]
	if tag == "userTask":
		return {attrs["targetDoctype"]: {"read", "write"}} if attrs.get("targetDoctype") else {}
	if tag == "scriptTask":
		return _script_permission_needs(task, attrs)
	doctype = attrs.get("serviceTargetDoctype") or attrs.get("updateFieldDoctype") or attrs.get("emailDoctype")
	if not doctype:
		return {}
	ptypes = {"read", "write"}
	if attrs.get("serviceType") == "apply_workflow" and frappe.db.get_value("DocType", doctype, "is_submittable"):
		ptypes.add("submit")
	return {doctype: ptypes}


def _script_permission_needs(task, attrs: dict) -> dict:
	"""DocTypes a script task touches: its Server Script reference plus literal DocTypes in frappe calls."""
	import xml.etree.ElementTree as ET

	from processa.ai_agent_security.code_checks.script_gate import _script_task_sources

	needs = {}
	reference = frappe.db.get_value("Server Script", attrs["serverScript"], "reference_doctype") if attrs.get("serverScript") else None
	if reference:
		needs[reference] = {"read", "write"}
	for _label, code, _name in _script_task_sources(ET.tostring(task, encoding="unicode")):
		for doctype, ptype in _script_doctype_calls(code):
			needs.setdefault(doctype, set()).add(ptype)
	return needs


def _script_doctype_calls(code: str) -> list:
	"""(doctype, permission type) pairs for frappe calls that name a DocType as a string literal."""
	import ast

	try:
		tree = ast.parse(code)
	except SyntaxError:
		return []
	calls = []
	for node in ast.walk(tree):
		if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.args):
			continue
		first = node.args[0]
		ptype = SCRIPT_CALL_PERMISSIONS.get(node.func.attr)
		if isinstance(first, ast.Dict) and node.func.attr == "get_doc":
			doctype = next((v.value for k, v in zip(first.keys, first.values) if isinstance(k, ast.Constant) and k.value == "doctype" and isinstance(v, ast.Constant)), None)
			ptype = "create"
		else:
			doctype = first.value if isinstance(first, ast.Constant) and isinstance(first.value, str) else None
		if doctype and ptype:
			calls.append((doctype, ptype))
	return calls
