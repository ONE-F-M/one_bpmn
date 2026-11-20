"""
Enforcement gates for BPMN Script Task security.

These helpers wire :func:`processa.ai_agent_security.code_checks.script_validator.deep_inspect_script`
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
from frappe.query_builder import DocType

from processa.ai_agent_security.code_checks.script_validator import (
	SYNTAX_ERROR,
	inspect_script,
	used_categories,
)

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"


def approved_request_names(process: str, script_task: str, server_script: str) -> frozenset:
	"""The item names on Approved Script Approval Requests for this script task."""
	return frozenset(approved_request_items(process, script_task, server_script))


def approved_request_items(process: str, script_task: str, server_script: str) -> dict:
	"""Each item name on an Approved Script Approval Request for this script task, with that request."""
	request = DocType("Script Approval Request")
	item = DocType("Script Approval Request Item")
	rows = (
		frappe.qb.from_(request)
		.join(item)
		.on(item.parent == request.name)
		.select(item.item_name, request.name)
		.where(request.process_name == process)
		.where(request.script_task == script_task)
		.where(request.server_script == server_script)
		.where(request.status == "Approved")
	).run()
	return dict(rows)


def script_task_findings(code: str, process: str, script_task: str, server_script: str) -> list[dict]:
	"""Findings in code that no Approved request for this script task covers."""
	return inspect_script(code, approved_request_names(process, script_task, server_script))


def lint_script(code: str, script_name: str = "", process: str = "", script_task: str = "") -> dict:
	"""Each finding in ``code`` with its approval state, and the status and open request of its script task.

	Without a Process, script task and Server Script every finding is checked against the default categories.
	"""
	if script_name and frappe.db.exists("Server Script", script_name):
		frappe.get_doc("Server Script", script_name).check_permission("read")
	on_task = bool(process and script_task and script_name)
	approved = approved_request_items(process, script_task, script_name) if on_task else {}
	categories = frappe.get_list(
		"Script Import Category",
		fields=["name", "allowed_by_default", "sanctioned_alternative"],
		order_by="name asc",
	)
	alternatives = {c.name: c.sanctioned_alternative for c in categories}
	findings = []
	for finding in inspect_script(code or ""):
		request = _covering_request(finding["name"], approved)
		alternative = alternatives.get(finding["category"]) or ""
		findings.append(
			{**finding, "approved": bool(request), "request": request, "sanctioned_alternative": alternative}
		)
	open_request = _open_request(process, script_task, script_name) if on_task else None
	latest = on_task and frappe.get_list(
		"Script Approval Request",
		filters={"process_name": process, "script_task": script_task, "server_script": script_name},
		fields=["name", "status", "decision_note"],
		order_by="creation desc",
		limit=1,
	)
	return {
		"findings": findings,
		"open_request": open_request,
		"status": _task_status(findings, open_request),
		"latest_request": latest[0] if latest else None,
		"in_use": used_categories(code),
		"categories": [{"name": c.name, "allowed_by_default": c.allowed_by_default} for c in categories],
	}


def _covering_request(name: str, approved: dict) -> str | None:
	"""The Approved request listing name or one of its dotted prefixes."""
	parts = name.split(".")
	for end in range(len(parts), 0, -1):
		request = approved.get(".".join(parts[:end]))
		if request:
			return request
	return None


def _task_status(findings: list, open_request: str | None) -> str:
	if any(f["category"] == SYNTAX_ERROR for f in findings):
		return "Syntax error"
	if all(f["approved"] for f in findings):
		return "Approved" if findings else "Clear"
	return "Requested" if open_request else "Needs approval"


def _looks_like_python(text: str) -> bool:
	"""Heuristic: is ``text`` inline Python rather than a Server Script name?

	Mirrors the compile-time heuristic in ``compiler.extensions.extract_script_task_config``
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


def script_task_sources(bpmn_xml: str, process: str | None = None) -> list[tuple]:
	"""
	Resolve every script task in the diagram to the code that will run.

	Returns a list of ``(label, code, allowed, bpmn_id, server_script)`` tuples. Inline code gets
	no allowed names; a Server Script gets the names its Approved requests on ``process`` list.

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
					approved_request_names(process, bpmn_id, server_script) if process else frozenset(),
					bpmn_id,
					server_script,
				))
		elif inline and _looks_like_python(inline):
			sources.append((_("Script Task '{0}' (inline)").format(bpmn_id), inline, frozenset(), bpmn_id, ""))

	return sources


def collect_script_security_violations(bpmn_xml: str, process: str | None = None) -> list:
	"""Every finding on the diagram's script tasks that no Approved request on ``process`` covers.

	Each is ``{"label", "message", "category", "request"}``; request is the open request for the task, if any.
	"""
	findings: list = []
	for label, code, allowed, bpmn_id, server_script in script_task_sources(bpmn_xml, process):
		request = _open_request(process, bpmn_id, server_script)
		for finding in inspect_script(code, allowed):
			findings.append(
				{"label": label, "message": finding["message"], "category": finding["category"], "request": request}
			)
	return findings


def _open_request(process: str | None, script_task: str, server_script: str) -> str | None:
	if not (process and server_script):
		return None
	return frappe.db.get_value(
		"Script Approval Request",
		{
			"process_name": process,
			"script_task": script_task,
			"server_script": server_script,
			"status": ("in", ("Pending Review", "Pending Approval")),
		},
	)


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


def validate_process_model_scripts(bpmn_xml: str, process: str | None = None) -> None:
	"""Deploy gate: refuse the map while any script task has a finding no Approved request covers."""
	_refuse_findings(
		collect_script_security_violations(bpmn_xml, process),
		_("This process can't be deployed because these script tasks need approval:"),
	)


def validate_process_model_syntax(bpmn_xml: str) -> None:
	"""Map save gate: refuse only a script task whose code does not parse."""
	_refuse_findings(
		[f for f in collect_script_security_violations(bpmn_xml) if f["category"] == SYNTAX_ERROR],
		_("This process can't be saved because a script task has a syntax error:"),
	)


def _refuse_findings(findings: list, heading: str) -> None:
	"""Log the full findings and throw one line per affected script task."""
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

	lines = [heading, ""]
	for label, count in issue_counts.items():
		lines.append(_("• {0} — {1} security issue(s)").format(label, count))
	lines.append("")
	lines.append(
		_(
			"Open Deployment Readiness → Script Security to see each item and request approval for it."
		)
	)

	frappe.throw(
		"\n".join(lines),
		title=_("Script Task Security"),
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

	Refuses a syntax error in a Server Script linked to a BPMN process model; what needs
	approval is checked at deploy and before the script runs. Unrelated Server Scripts pass through.
	"""
	code = getattr(doc, "script", None)
	if not code:
		return
	if not is_bpmn_linked_server_script(doc.name):
		return

	violations = [f["message"] for f in inspect_script(code) if f["category"] == SYNTAX_ERROR]
	if violations:
		frappe.throw(
			_format_violations(violations),
			title=_("Unsafe BPMN Server Script"),
			exc=frappe.ValidationError,
		)
