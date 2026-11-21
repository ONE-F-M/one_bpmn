"""Run a Logix draft as a script task on a sample record, then undo everything it did."""

import traceback
import xml.etree.ElementTree as ET
from contextlib import ExitStack
from unittest.mock import patch

import frappe
from frappe.model.document import Document

from processa.ai_agent_registry.definitions.logix.helpers import BPMN_NS, ERROR_CHARS, SERVER_SCRIPT_ATTR
from processa.ai_agent_security.code_checks.script_validator import deep_inspect_script
from processa.processa_engine.engine.script_engine import make_import_script

DRAFT_FILE = "<logix draft>"
SAVEPOINT = "logix_dry_run"
OUTBOUND = (
	"frappe.sendmail",
	"frappe.enqueue",
	"frappe.integrations.utils.make_request",
	"frappe.integrations.utils.make_get_request",
	"frappe.integrations.utils.make_post_request",
	"frappe.integrations.utils.make_put_request",
	"requests.request",
	"requests.get",
	"requests.post",
	"requests.put",
)
WRITES = ("insert", "save", "submit", "cancel", "delete")


def dry_run(code: str, turn: dict) -> dict:
	"""Run the draft the way the engine runs a script task and report what it did or the error it raised.

	The run is inside a savepoint that is rolled back, as the person who asked, with email and HTTP calls stubbed.
	"""
	context = turn.get("process_context") or {}
	model = _process_model(context.get("process_name"))
	doctype = model and model.trigger_doctype
	names = frappe.get_all(doctype, pluck="name", order_by="creation desc", limit=1) if doctype else []
	if not names:
		return {"ran": False, "summary": "I did not run the script: this process has no record to try it on."}
	if deep_inspect_script(code, allowed=frozenset(OUTBOUND)):
		return {"ran": False, "summary": "I did not run the script: it needs approval before it can run."}
	docname = names[0]

	writes, stubbed, result = [], [], {}
	namespace = _namespace(model, context, frappe.get_doc(doctype, docname), result)
	outcome = {"ran": True, "record": f"{doctype} {docname}"}
	user, person = frappe.session.user, frappe.flags.get("requesting_user") or frappe.session.user
	frappe.db.savepoint(SAVEPOINT)
	try:
		if person != user:
			frappe.set_user(person)
		with ExitStack() as stack:
			for target in OUTBOUND:
				stack.enter_context(patch(target, _stub(stubbed, target)))
			for method in WRITES:
				stack.enter_context(patch.object(Document, method, _recorded(writes, method)))
			exec(
				compile(code, DRAFT_FILE, "exec"), namespace
			)  # nosemgrep: frappe-semgrep-rules.rules.security.frappe-codeinjection-eval
	except Exception as exc:
		if type(exc) is frappe.ValidationError:
			outcome["stopped"] = frappe.utils.strip_html(str(exc))
		else:
			outcome.update(_failure(code, exc))
	finally:
		frappe.db.rollback(save_point=SAVEPOINT)
		frappe.local.message_log = []
		if person != user:
			frappe.set_user(user)
	outcome.update(writes=list(dict.fromkeys(writes)), stubbed=list(dict.fromkeys(stubbed)), result=result)
	outcome["summary"] = _summary(outcome)
	return outcome


def _namespace(model, context: dict, doc, result: dict) -> dict:
	"""The names the engine gives a script task, with the sample record as doc."""
	return {
		"frappe": frappe,
		"_": frappe._,
		"__builtins__": __builtins__,
		"agent_configuration": "",
		"context_doctype": doc.doctype,
		"context_docname": doc.name,
		"result": result,
		"instance": None,
		"bpmn_id": context.get("element_id") or "",
		"task_data": {},
		"import_script": make_import_script(
			frappe._dict(process_model=model.name), _script_tasks(model.bpmn_xml)
		),
		"doc": doc,
	}


def _process_model(process_id: str | None):
	if not process_id:
		return None
	name = frappe.db.get_value(
		"BPMN Process Model", {"process_id": process_id}, "name", order_by="modified desc"
	)
	return name and frappe.db.get_value(
		"BPMN Process Model", name, ["name", "trigger_doctype", "bpmn_xml"], as_dict=True
	)


def _script_tasks(bpmn_xml: str) -> dict:
	"""Each script task on the map with its Server Script, for import_script."""
	tasks = ET.fromstring((bpmn_xml or "<x/>").strip().encode()).iter(f"{BPMN_NS}scriptTask")
	return {
		t.get("id"): {"serverScript": t.get(SERVER_SCRIPT_ATTR)} for t in tasks if t.get(SERVER_SCRIPT_ATTR)
	}


def _stub(stubbed: list, target: str):
	def stub(*args, **kwargs):
		stubbed.append(target.rsplit(".", 1)[-1])

	return stub


def _recorded(writes: list, method: str):
	original = getattr(Document, method)

	def record(self, *args, **kwargs):
		value = original(self, *args, **kwargs)
		writes.append(f"{method} {self.doctype} {self.name}")
		return value

	return record


def _failure(code: str, exc: Exception) -> dict:
	frames = [f for f in traceback.extract_tb(exc.__traceback__) if f.filename == DRAFT_FILE]
	line = frames[-1].lineno if frames else 0
	lines = code.splitlines()
	return {
		"error": "".join(traceback.format_exception(exc))[-ERROR_CHARS:],
		"line": line,
		"code": lines[line - 1].strip() if 0 < line <= len(lines) else "",
		"message": f"{type(exc).__name__}: {exc}",
	}


def _summary(outcome: dict) -> str:
	if outcome.get("error"):
		return f"It failed on {outcome['record']}: {outcome['message']}."
	parts = [f"I tried it on {outcome['record']} and undid the changes afterwards."]
	if outcome.get("stopped"):
		parts.append(f"It stopped with the message: {outcome['stopped']}")
	parts += [f"It would {w}." for w in outcome["writes"]]
	parts += [f"It sets {key} to {value!r}." for key, value in outcome["result"].items()]
	if outcome["stubbed"]:
		parts.append("Not executed in the trial: " + ", ".join(outcome["stubbed"]) + ".")
	if len(parts) == 1:
		parts.append("It changed nothing and set no results.")
	return " ".join(parts)
