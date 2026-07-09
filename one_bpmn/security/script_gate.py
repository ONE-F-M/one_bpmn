"""
Enforcement gates for BPMN Script Task security.

These helpers wire :func:`one_bpmn.security.script_validator.deep_inspect_script`
into the three pre-deployment gates:

  1. Server Script save        → ``validate_server_script_on_save`` (doc_event)
  2. Process-model authoring    → ``validate_process_model_scripts`` (model.validate)
  3. Process-model deploy       → ``validate_process_model_scripts`` (compile_process_model)

Only scripts that belong to BPMN script tasks are gated. Unrelated Server
Scripts in the site are never touched (see ``is_bpmn_linked_server_script``).
"""

import keyword
import xml.etree.ElementTree as ET

import frappe
from frappe import _

from one_bpmn.security.script_validator import deep_inspect_script

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"


def _looks_like_python(text: str) -> bool:
	"""Heuristic: is ``text`` inline Python rather than a Server Script name?

	Mirrors the compile-time heuristic in ``api.compilation._extract_script_task_config``
	so the two agree on which script tasks carry inline code.
	"""
	if not text:
		return False
	py_chars = ("=", "(", ")", "{", "}", ":", "\n", ".", "import", "def ", "class ", "return")
	lower = text.strip().lower()
	if any(c in lower for c in py_chars):
		return True
	if lower in keyword.kwlist:
		return True
	return False


def _script_task_sources(bpmn_xml: str) -> list[tuple]:
	"""
	Resolve every script task in the diagram to the code that will run.

	Returns a list of ``(label, code)`` tuples:
	  * inline ``<bpmn:script>`` tasks  → (label, inline python)
	  * ``spiffworkflow:serverScript`` tasks → (label, Server Script .script)

	Referenced Server Scripts that do not exist yet (authoring in progress) are
	skipped — the deploy gate re-checks once they exist. Never raises: an
	unparseable diagram yields an empty list and is handled by other validators.
	"""
	sources: list[tuple] = []
	try:
		root = ET.fromstring((bpmn_xml or "").strip().encode("utf-8"))
	except Exception:
		return sources

	for elem in root.iter(f"{{{BPMN_NS}}}scriptTask"):
		bpmn_id = elem.get("id", "") or "?"
		server_script = elem.get(f"{{{SPIFF_NS}}}serverScript", "").strip()

		inline = ""
		script_elem = elem.find(f"{{{BPMN_NS}}}script")
		if script_elem is not None and script_elem.text:
			inline = script_elem.text.strip()

		# Primary: a referenced Server Script.
		if not server_script and inline and not _looks_like_python(inline):
			# Fallback: inline field holds a Server Script name (legacy diagrams).
			server_script = inline
			inline = ""

		if server_script:
			code = frappe.db.get_value("Server Script", server_script, "script")
			if code:
				sources.append(
					(_("Script Task '{0}' → Server Script '{1}'").format(bpmn_id, server_script), code)
				)
		elif inline and _looks_like_python(inline):
			sources.append((_("Script Task '{0}' (inline)").format(bpmn_id), inline))

	return sources


def validate_process_model_scripts(bpmn_xml: str) -> None:
	"""
	Gate every script task in a process model. Raises ``frappe.ValidationError``
	listing all violations found across all script tasks. No-op when clean.

	Used by both the authoring gate (model.validate) and the deploy gate
	(compile_process_model).
	"""
	messages: list[str] = []
	for label, code in _script_task_sources(bpmn_xml):
		violations = deep_inspect_script(code)
		for v in violations:
			messages.append(f"{label}: {v}")

	if messages:
		frappe.throw(
			"<br>".join(f"• {frappe.utils.escape_html(m)}" for m in messages),
			title=_("Unsafe BPMN Script Task"),
			exc=frappe.ValidationError,
		)


def is_bpmn_linked_server_script(script_name: str) -> bool:
	"""
	True when ``script_name`` is referenced by at least one BPMN Process Model,
	either via the ``spiffworkflow:serverScript`` XML attribute (authoring) or a
	compiled ``script_task_extensions`` entry (deployed).

	Keeps the Server-Script save gate scoped to BPMN scripts only.
	"""
	if not script_name:
		return False

	# Authoring: attribute present in the raw diagram XML.
	if frappe.get_all(
		"BPMN Process Model",
		filters=[["bpmn_xml", "like", f'%serverScript="{script_name}"%']],
		limit=1,
	):
		return True

	# Deployed: name embedded in the compiled spec.
	if frappe.get_all(
		"BPMN Process Model",
		filters=[["serialized_spec", "like", f'%"serverScript": "{script_name}"%']],
		limit=1,
	):
		return True

	return False


def validate_server_script_on_save(doc, method=None) -> None:
	"""
	doc_event hook (Server Script ``validate``).

	Runs the structural validator on the script body, but only when the Server
	Script is linked to a BPMN process model — unrelated Server Scripts pass
	through untouched. Raises ``frappe.ValidationError`` on any violation.
	"""
	code = getattr(doc, "script", None)
	if not code:
		return
	if not is_bpmn_linked_server_script(doc.name):
		return

	violations = deep_inspect_script(code)
	if violations:
		frappe.throw(
			"<br>".join(f"• {frappe.utils.escape_html(v)}" for v in violations),
			title=_("Unsafe BPMN Server Script"),
			exc=frappe.ValidationError,
		)
