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

import hashlib
import keyword
import xml.etree.ElementTree as ET

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.utils import cint, cstr, now_datetime

from processa.ai_agent_security.code_checks.script_validator import (
	SYNTAX_ERROR,
	deep_inspect_script,
	inspect_script,
	parse_allowed,
)

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

APPROVAL_FIELDS = ("processa_allowed_modules", "processa_approved")

SERVER_SCRIPT_APPROVAL_FIELDS = {
	"Server Script": [
		{
			"fieldname": "processa_approval_section",
			"fieldtype": "Section Break",
			"label": "Processa Approval",
			"insert_after": "cron_format",
		},
		{
			"fieldname": "processa_allowed_modules",
			"fieldtype": "Small Text",
			"label": "Allowed Modules",
			"description": "Blocked modules and frappe calls this script may use, one per line or comma-separated. Only a System Manager can change this.",
			"insert_after": "processa_approval_section",
		},
		{
			"fieldname": "processa_approved",
			"fieldtype": "Check",
			"label": "Approved",
			"description": "Set by a System Manager. Any change to the script clears it and disables the script.",
			"insert_after": "processa_allowed_modules",
		},
		{
			"fieldname": "processa_approved_by",
			"fieldtype": "Link",
			"options": "User",
			"label": "Approved By",
			"read_only": 1,
			"insert_after": "processa_approved",
		},
		{
			"fieldname": "processa_approved_on",
			"fieldtype": "Datetime",
			"label": "Approved On",
			"read_only": 1,
			"insert_after": "processa_approved_by",
		},
		{
			"fieldname": "processa_pending_review",
			"fieldtype": "Check",
			"label": "Pending Review",
			"description": "Set when an agent writes or edits the script. A System Manager enabling it clears this.",
			"read_only": 1,
			"insert_after": "processa_approved_on",
		},
		{
			"fieldname": "processa_approved_hash",
			"fieldtype": "Data",
			"label": "Approved Code Hash",
			"read_only": 1,
			"hidden": 1,
			"insert_after": "processa_pending_review",
		},
	]
}


def script_hash(code: str | None) -> str:
	return hashlib.sha256(cstr(code).encode()).hexdigest()


def approved_names(script) -> frozenset:
	"""The allowed modules of a Server Script approved for its current code, else none."""
	if not cint(script.get("processa_approved")):
		return frozenset()
	if script.get("processa_approved_hash") != script_hash(script.get("script")):
		return frozenset()
	return parse_allowed(script.get("processa_allowed_modules"))


def approved_request_names(process: str, script_task: str, server_script: str) -> frozenset:
	"""The item names on Approved Script Approval Requests for this script task."""
	request = DocType("Script Approval Request")
	item = DocType("Script Approval Request Item")
	rows = (
		frappe.qb.from_(request)
		.join(item)
		.on(item.parent == request.name)
		.select(item.item_name)
		.where(request.process_name == process)
		.where(request.script_task == script_task)
		.where(request.server_script == server_script)
		.where(request.status == "Approved")
	).run()
	return frozenset(row[0] for row in rows)


def script_task_findings(code: str, process: str, script_task: str, server_script: str) -> list[dict]:
	"""Findings in code that no Approved request for this script task covers."""
	return inspect_script(code, approved_request_names(process, script_task, server_script))


def lint_code(code: str, script_name: str = "") -> list[str]:
	"""The violations in ``code``, allowing what the saved script's approval covers while it still matches."""
	allowed = frozenset()
	if script_name and frappe.db.exists("Server Script", script_name):
		script = frappe.get_doc("Server Script", script_name)
		script.check_permission("read")
		allowed = approved_names(frappe._dict(script.as_dict(), script=code))
	return deep_inspect_script(code or "", allowed=allowed)


def apply_server_script_approval(doc, method=None) -> None:
	"""Server Script validate: only a System Manager approves, and a code change clears the approval."""
	before = doc.get_doc_before_save()
	stored = before or frappe._dict()
	if (
		cstr(stored.get("processa_allowed_modules")) != cstr(doc.get("processa_allowed_modules"))
		or cint(stored.get("processa_approved")) != cint(doc.get("processa_approved"))
	) and "System Manager" not in frappe.get_roles():
		frappe.throw(
			_("Only a System Manager can change the allowed modules or the approval of a Server Script."),
			frappe.PermissionError,
		)

	_apply_pending_review(doc, stored)

	# The stamps are server-owned: start from the stored values whatever the client sent.
	doc.processa_approved_by = stored.get("processa_approved_by")
	doc.processa_approved_on = stored.get("processa_approved_on")
	doc.processa_approved_hash = stored.get("processa_approved_hash")
	code_hash = script_hash(doc.script)

	if not cint(doc.processa_approved):
		_clear_approval(doc)
	elif not cint(stored.get("processa_approved")) or cstr(stored.get("processa_allowed_modules")) != cstr(
		doc.processa_allowed_modules
	):
		doc.processa_approved_by = frappe.session.user
		doc.processa_approved_on = now_datetime()
		doc.processa_approved_hash = code_hash
	elif doc.processa_approved_hash != code_hash:
		_clear_approval(doc)
		doc.disabled = 1


def _apply_pending_review(doc, stored) -> None:
	"""Only a System Manager enables a script awaiting review, and enabling it clears the marker."""
	if "System Manager" not in frappe.get_roles():
		doc.processa_pending_review = stored.get("processa_pending_review")
	if not cint(doc.processa_pending_review) or cint(doc.disabled):
		return
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Only a System Manager can enable a Server Script awaiting review."), frappe.PermissionError)
	doc.processa_pending_review = 0


def _clear_approval(doc) -> None:
	doc.processa_approved = 0
	doc.processa_approved_by = None
	doc.processa_approved_on = None
	doc.processa_approved_hash = None


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


def _script_task_sources(bpmn_xml: str, process: str | None = None) -> list[tuple]:
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
	for label, code, allowed, bpmn_id, server_script in _script_task_sources(bpmn_xml, process):
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
