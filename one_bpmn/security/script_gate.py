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

	Returns a list of ``(label, code, script_name)`` tuples:
	  * inline ``<bpmn:script>`` tasks  → (label, inline python, None)
	  * ``spiffworkflow:serverScript`` tasks → (label, Server Script .script, name)

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
				sources.append((
					_("Script Task '{0}' → Server Script '{1}'").format(bpmn_id, server_script),
					code,
					server_script,
				))
		elif inline and _looks_like_python(inline):
			sources.append((_("Script Task '{0}' (inline)").format(bpmn_id), inline, None))

	return sources


def collect_script_security_violations(bpmn_xml: str) -> list:
	"""
	Structurally validate every (non-exempt) script task in a diagram.

	Shared by the deploy readiness check and the authoring/deploy gate, so all
	surfaces report exactly the same findings. Returns a list of dicts:
	``{"label": <task → script>, "message": <violation>}``. Empty when clean.
	"""
	findings: list = []
	for label, code, _script_name in _script_task_sources(bpmn_xml):
		for message in deep_inspect_script(code):
			findings.append({"label": label, "message": message})
	return findings


def _format_violations(messages: list) -> str:
	"""
	Render violation messages for display.

	Plain text, one bullet per line (``\\n`` separated) so it reads cleanly in
	the Processa editor notification (which uses ``whitespace-pre-line`` text
	interpolation, not HTML) and remains readable in the desk dialog. Angle
	brackets are stripped so an untrusted script/task name cannot inject markup
	into the desk's HTML message view.
	"""
	safe = [str(m).replace("<", "").replace(">", "") for m in messages]
	return "\n".join(f"• {m}" for m in safe)


def validate_process_model_scripts(bpmn_xml: str) -> None:
	"""
	Gate every script task in a process model. Raises ``frappe.ValidationError``
	with a concise, generic summary when any violation is found. No-op when clean.

	The user-facing message names the affected task(s) and the number of issues,
	and points to the Deployment Readiness → Script Security panel for the full
	per-rule breakdown — rather than dumping every rule into a modal. The complete
	detail is written to the admin-only Frappe Error Log.

	Used by both the authoring gate (model.validate) and the deploy gate
	(compile_process_model) as a backend safety net; the deploy readiness check
	surfaces the same findings in the UI first.
	"""
	findings = collect_script_security_violations(bpmn_xml)
	if not findings:
		return

	# Full per-rule detail → admin-only Error Log. Keeps the editor modal generic
	# while admins retain the exact findings for triage.
	frappe.log_error(
		title=_("Unsafe BPMN Script Task blocked"),
		message=_format_violations([f"{f['label']}: {f['message']}" for f in findings]),
	)

	# Concise, generic-but-actionable summary: one line per affected task with an
	# issue count, plus where to find the specifics.
	issue_counts: dict = {}
	for f in findings:
		safe_label = str(f["label"]).replace("<", "").replace(">", "")
		issue_counts[safe_label] = issue_counts.get(safe_label, 0) + 1

	lines = [
		_("This process can't be saved because one or more script tasks contain unsafe code:"),
		"",
	]
	for label, count in issue_counts.items():
		lines.append(_("• {0} — {1} security issue(s)").format(label, count))
	lines.append("")
	lines.append(
		_(
			"Unsafe scripts are blocked to protect the system. Open Deployment "
			"Readiness → Script Security to see each issue, or contact your administrator."
		)
	)

	frappe.throw(
		"\n".join(lines),
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
			_format_violations(violations),
			title=_("Unsafe BPMN Server Script"),
			exc=frappe.ValidationError,
		)
