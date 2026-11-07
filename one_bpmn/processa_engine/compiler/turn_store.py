# Copyright (c) 2026, one-fm and contributors
"""Deploy warning for a closing script that reads a turn-store key no script on the map writes."""

import ast
import json
import re

import frappe
from frappe import _

from one_bpmn.processa_engine.compiler.agent_tools import ai_agents_with_tools


# Keys read through turn.get or out.get, for a script that does not parse.
_TURN_READ_RE = re.compile(r"\b(?:_?turn|_?out)\.get\(\s*['\"]([a-zA-Z_][\w]*)['\"]")


def validate_turn_store_contract(bpmn_xml: str, service_extensions: dict) -> list:
	"""Warn when a closing script reads a turn-store key that no script on the map writes."""
	agents = ai_agents_with_tools(service_extensions)
	if not agents:
		return []

	warnings = []
	for agent_id, cfg in agents.items():
		adhoc_id = (cfg.get("aiToolsAdhoc") or "").strip()
		tool_names, closing = _agent_script_names(bpmn_xml, adhoc_id)
		if not closing:
			continue
		bodies = _script_bodies(tool_names | set(closing.values()))

		wrote_top, wrote_out = set(), set()
		for name in bodies:
			t, o = _turn_keys_written(bodies[name])
			wrote_top |= t
			wrote_out |= o
		# A tool's declared parameters count as written: finalize passes its payload that way.
		for shape in json.loads(cfg.get("aiToolShapes") or "[]"):
			wrote_out |= set((shape.get("parameters") or {}).keys())

		for shape_id, script_name in sorted(closing.items()):
			body = bodies.get(script_name, "")
			read_top, read_out = _turn_keys_read(body)
			missing = sorted(
				[k for k in read_top if k not in wrote_top]
				+ [k for k in read_out if k not in wrote_out]
			)
			if not missing:
				continue
			warnings.append({
				"label": _("Turn Store"),
				"icon": "unplug",
				"type": "warning",
				"detail": _(
					"'{0}' ({1}) reads {2} from the turn store, which no tool of '{3}' writes. "
					"The answer will come back empty."
				).format(shape_id, script_name, ", ".join(f"'{k}'" for k in missing), agent_id),
			})
	return warnings


def _turn_keys_read(script: str) -> tuple:
	"""(top-level keys, output keys) a script reads out of the turn store."""
	top, out = set(), set()
	try:
		tree = ast.parse(script or "")
	except SyntaxError:
		return set(_TURN_READ_RE.findall(script or "")), set()
	for node in ast.walk(tree):
		if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
			continue
		if node.func.attr != "get" or not node.args:
			continue
		key = node.args[0]
		if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
			continue
		base = node.func.value
		name = base.id if isinstance(base, ast.Name) else None
		if name in ("turn", "_turn"):
			if key.value != "output":
				top.add(key.value)
		elif name in ("out", "_out"):
			out.add(key.value)
	return top, out


def _turn_keys_written(script: str) -> tuple:
	"""(top-level keys, output keys) a script writes into the turn store."""
	top, out = set(), set()
	try:
		tree = ast.parse(script or "")
	except SyntaxError:
		return top, out
	literals = {}
	for node in ast.walk(tree):
		if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
			for target in node.targets:
				if isinstance(target, ast.Name):
					literals[target.id] = _dict_literal_keys(node.value)
	for node in ast.walk(tree):
		if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
			continue
		if node.func.id not in ("update_turn", "set_turn"):
			continue
		for kw in node.keywords:
			if kw.arg is None:
				continue  # **kwargs - nothing static to read
			if kw.arg == "output":
				out |= _keys_of(kw.value, literals)
			else:
				top.add(kw.arg)
		for arg in node.args[1:]:
			top |= _keys_of(arg, literals)
	return top, out


def _keys_of(node, literals: dict) -> set:
	"""Keys of a dict argument, whether written inline or passed by name."""
	if isinstance(node, ast.Name):
		return set(literals.get(node.id) or ())
	return _dict_literal_keys(node)


def _dict_literal_keys(node) -> set:
	if not isinstance(node, ast.Dict):
		return set()
	return {
		k.value for k in node.keys
		if isinstance(k, ast.Constant) and isinstance(k.value, str)
	}


def _script_bodies(names: set) -> dict:
	"""Server Script sources by name, skipping any that no longer exist."""
	if not names:
		return {}
	rows = frappe.get_all(
		"Server Script", filters={"name": ["in", list(names)]}, fields=["name", "script"]
	)
	return {r["name"]: r["script"] or "" for r in rows}


def _agent_script_names(bpmn_xml: str, adhoc_id: str) -> tuple:
	"""(tool scripts inside the Tools box, scripts everywhere else on the map)."""
	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"
	try:
		root = _ET.fromstring(bpmn_xml.strip().encode("utf-8") if isinstance(bpmn_xml, str) else bpmn_xml)
	except Exception:
		return set(), {}

	tool_scripts, inside = set(), set()
	for adhoc in root.iter(f"{{{BPMN_NS}}}adHocSubProcess"):
		for child in adhoc.iter():
			name = child.get(f"{{{SPIFF_NS}}}serverScript")
			if child.get("id"):
				inside.add(child.get("id"))
			if name and adhoc.get("id") == adhoc_id:
				tool_scripts.add(name)

	others = {}
	for el in root.iter():
		name = el.get(f"{{{SPIFF_NS}}}serverScript")
		if name and el.get("id") not in inside:
			others[el.get("id")] = name
	return tool_scripts, others
