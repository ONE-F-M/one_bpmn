"""Process model lookup and digest, for the General Chat process tools."""

import xml.etree.ElementTree as ET

import frappe
from frappe import _
from frappe.utils import strip_html

from one_bpmn.agents.memory.tools import _query_tokens

DOCTYPE = "BPMN Process Model"
BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
SEARCH_FIELDS = ("title", "process_id", "process_name", "description")
CANDIDATE_LIMIT = 50
MAX_MODELS = 8
MAX_DIGEST_CHARS = 8000
MAX_DOC_CHARS = 300
STEP_TAGS = (
	"startEvent",
	"endEvent",
	"task",
	"userTask",
	"serviceTask",
	"scriptTask",
	"manualTask",
	"sendTask",
	"receiveTask",
	"businessRuleTask",
	"subProcess",
	"adHocSubProcess",
	"callActivity",
	"intermediateCatchEvent",
	"intermediateThrowEvent",
	"boundaryEvent",
)
EVENT_DEFINITIONS = {
	"messageEventDefinition": ("message", "messageRef"),
	"signalEventDefinition": ("signal", "signalRef"),
}
GATEWAY_TAGS = ("exclusiveGateway", "parallelGateway", "inclusiveGateway", "eventBasedGateway")


def find_process_models(query: str) -> dict:
	"""Process models the current user can read that match the query, best match first."""
	tokens = [token.lower() for token in _query_tokens(query)]
	if not tokens:
		return {"error": _("Give at least one keyword to search for.")}

	rows = frappe.get_list(
		DOCTYPE,
		fields=["name", *SEARCH_FIELDS],
		or_filters=[[field, "like", f"%{token}%"] for field in SEARCH_FIELDS for token in tokens],
		order_by="modified desc",
		limit_page_length=CANDIDATE_LIMIT,
	)
	for row in rows:
		haystack = " ".join(str(row[field] or "") for field in SEARCH_FIELDS).lower()
		row["score"] = sum(token in haystack for token in tokens)
	rows.sort(key=lambda row: row["score"], reverse=True)

	return {
		"results": [
			{
				"process_model": row.name,
				"title": row.title,
				"process": row.process_name,
				"description": strip_html(row.description or "")[:MAX_DOC_CHARS],
				"kind": _kind(_parse(frappe.db.get_value(DOCTYPE, row.name, "bpmn_xml"))),
			}
			for row in rows[:MAX_MODELS]
		]
	}


def get_process_model_digest(process_model: str) -> dict:
	"""Plain-text description of one process model the current user can read."""
	if not frappe.db.exists(DOCTYPE, process_model):
		return {"error": _("No process model named {0}.").format(process_model)}

	model = frappe.get_doc(DOCTYPE, process_model)
	model.check_permission("read")
	root = _parse(model.bpmn_xml)

	lines = [f"Process model: {model.title}", f"Kind: {_kind(root)}"]
	lines.extend(_process_lines(model.process_name))
	if model.description:
		lines.append(f"Description: {strip_html(model.description)}")
	lines.extend(_flow_lines(root))

	digest = "\n".join(lines)
	if len(digest) > MAX_DIGEST_CHARS:
		digest = digest[:MAX_DIGEST_CHARS] + "\n[digest truncated]"
	return {"digest": digest}


def _parse(bpmn_xml: str | None):
	if not (bpmn_xml or "").strip():
		return None
	try:
		return ET.fromstring(bpmn_xml.strip().encode("utf-8"))
	except ET.ParseError:
		return None


def _kind(root) -> str:
	"""Executable when any process element carries isExecutable="true", as deploy requires."""
	if root is None:
		return "documented"
	flags = [el.get("isExecutable", "false").strip().lower() for el in root.iter(_tag("process"))]
	return "executable" if "true" in flags else "documented"


def _process_lines(process_name: str | None) -> list[str]:
	if not process_name:
		return []
	process = frappe.db.get_value("Process", process_name, ["process_owner_name"], as_dict=True)
	if not process:
		return []
	roles = frappe.get_all("Process Role", filters={"parent": process_name}, pluck="role")
	lines = [f"Process: {process_name}"]
	if process.process_owner_name:
		lines.append(f"Process owner: {process.process_owner_name}")
	if roles:
		lines.append(f"Roles: {', '.join(roles)}")
	return lines


def _flow_lines(root) -> list[str]:
	if root is None:
		return ["The diagram is empty or unreadable."]

	names = {el.get("id"): el.get("name") or el.get("id") for el in root.iter() if el.get("id")}
	lanes = {}
	for lane in root.iter(_tag("lane")):
		for ref in lane.findall(_tag("flowNodeRef")):
			lanes[(ref.text or "").strip()] = lane.get("name") or ""
	outgoing = {}
	for flow in root.iter(_tag("sequenceFlow")):
		outgoing.setdefault(flow.get("sourceRef"), []).append(flow)

	lines = ["Steps in diagram order:"]
	for el in root.iter():
		kind = _local(el.tag)
		if kind in STEP_TAGS:
			lines.append(_step_line(el, kind, lanes, names))
		elif kind in GATEWAY_TAGS:
			lines.append(_gateway_line(el, kind, outgoing, names))
	return lines


def _step_line(el, kind: str, lanes: dict, names: dict) -> str:
	lane = lanes.get(el.get("id"))
	text = f"- {kind}: {el.get('name') or el.get('id')}"
	event = _event_note(el, names)
	if event:
		text += f" [{event}]"
	if lane:
		text += f" (lane: {lane})"
	documentation = el.find(_tag("documentation"))
	if documentation is not None and (documentation.text or "").strip():
		text += f" - {strip_html(documentation.text).strip()[:MAX_DOC_CHARS]}"
	return text


def _event_note(el, names: dict) -> str:
	for child in el:
		kind, ref_attr = EVENT_DEFINITIONS.get(_local(child.tag), (None, None))
		if kind:
			return f"{kind}: {names.get(child.get(ref_attr), '?')}"
	if el.get("messageRef"):
		return f"message: {names.get(el.get('messageRef'), '?')}"
	return ""


def _gateway_line(el, kind: str, outgoing: dict, names: dict) -> str:
	branches = [
		f"{flow.get('name') or 'unnamed'} -> {names.get(flow.get('targetRef'), '?')}"
		for flow in outgoing.get(el.get("id"), [])
	]
	return f"- {kind}: {el.get('name') or el.get('id')} [{'; '.join(branches)}]"


def _tag(name: str) -> str:
	return f"{{{BPMN_NS}}}{name}"


def _local(tag) -> str:
	return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""
