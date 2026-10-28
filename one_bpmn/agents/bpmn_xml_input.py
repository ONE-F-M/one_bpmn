# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Direct parsing of BPMN 2.0 XML that a user pastes into a ProsAlly chat (WI-004172).

Without this, a pasted diagram reached the model as conversational text and ProsAlly asked the user to
re-type the steps as a list. Here the pasted XML is recognised, parsed on the server and handed to the model
as a compact semantic analysis:

* tasks, sequence flows, catch/throw/boundary events and gateways are read directly;
* every finding names the element id, the tag and the flow connection involved, with a suggested fix;
* XML that is not well-formed is reported with the line, column and tag of the failure;
* the ``bpmndi`` layout section (coordinates only) is never listed and is cut from very large pastes, so the
  semantic model fits the context window.

Pure Python (no frappe), so it can be tested without a site.
"""

from __future__ import annotations

import difflib
import re
from xml.etree import ElementTree as ET

from one_bpmn.agents.memory.text_clean import unescape_entities

# A paste longer than this is sent to the model without its diagram-layout section.
MAX_RAW_XML_CHARS = 20000
# The analysis block handed to the model never exceeds this.
MAX_ANALYSIS_CHARS = 12000
MAX_LISTED_ELEMENTS = 150
MAX_LISTED_FLOWS = 150
MAX_LISTED_ISSUES = 40
# Lines kept either side of a parse failure when a huge paste has to be cut down to an excerpt.
ERROR_EXCERPT_LINES = 5

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
DI_NAMESPACES = (
	"http://www.omg.org/spec/BPMN/20100524/DI",
	"http://www.omg.org/spec/DD/20100524/DC",
	"http://www.omg.org/spec/DD/20100524/DI",
)
# Prefixes declared around a pasted fragment that carries no xmlns of its own.
FRAGMENT_PREFIXES = {
	"bpmn": BPMN_NS,
	"bpmn2": BPMN_NS,
	"bpmndi": DI_NAMESPACES[0],
	"dc": DI_NAMESPACES[1],
	"di": DI_NAMESPACES[2],
	"xsi": "http://www.w3.org/2001/XMLSchema-instance",
	"camunda": "http://camunda.org/schema/1.0/bpmn",
	"spiffworkflow": "http://spiffworkflow.org/bpmn/schema/1.0/core",
	"custom": "http://custom/text-style",
}

TASK_TAGS = frozenset(
	(
		"task",
		"userTask",
		"serviceTask",
		"scriptTask",
		"manualTask",
		"sendTask",
		"receiveTask",
		"businessRuleTask",
		"callActivity",
		"subProcess",
		"adHocSubProcess",
		"transaction",
	)
)
EVENT_TAGS = frozenset(("startEvent", "endEvent", "intermediateCatchEvent", "intermediateThrowEvent", "boundaryEvent"))
GATEWAY_TAGS = frozenset(
	("exclusiveGateway", "inclusiveGateway", "parallelGateway", "eventBasedGateway", "complexGateway")
)
FLOW_NODE_TAGS = TASK_TAGS | EVENT_TAGS | GATEWAY_TAGS
CATCH_ONLY_DEFINITIONS = frozenset(("timerEventDefinition", "conditionalEventDefinition"))

_TAG_NAMES = (
	"definitions|process|collaboration|sequenceFlow|startEvent|endEvent|intermediateCatchEvent|"
	"intermediateThrowEvent|boundaryEvent|task|userTask|serviceTask|scriptTask|manualTask|sendTask|"
	"receiveTask|businessRuleTask|callActivity|subProcess|adHocSubProcess|exclusiveGateway|inclusiveGateway|"
	"parallelGateway|eventBasedGateway|complexGateway|BPMNDiagram|BPMNPlane|BPMNShape|BPMNEdge"
)
_BPMN_TAG = re.compile(r"<(?:[A-Za-z_][\w.-]*:)?(" + _TAG_NAMES + r")\b")
_STRONG_TAGS = frozenset(("definitions", "process", "collaboration", "BPMNDiagram"))
_FENCE = re.compile(r"```[ \t]*(?:xml|bpmn)?[ \t]*\r?\n?(.*?)```", re.S | re.I)
_DIAGRAM = re.compile(r"<(?:[\w.-]+:)?BPMNDiagram\b.*?</(?:[\w.-]+:)?BPMNDiagram\s*>", re.S)
_DECLARATION = re.compile(r"^\s*<\?xml[^?]*\?>")
_DTD = re.compile(r"<!\s*(?:DOCTYPE|ENTITY)", re.I)
_POSITION_SUFFIX = re.compile(r":?\s*line \d+, column \d+\s*$")


# ── Detection and extraction ─────────────────────────────────────────────────


def is_bpmn_xml(text: str) -> bool:
	"""True when a chat message carries BPMN 2.0 XML, whole or partial, rather than prose.

	A single tag-shaped word in a sentence ("what is a <task>?") is not enough; a document-level tag, an XML
	declaration with a BPMN tag, or two different BPMN tags is.
	"""
	text = unescape_entities(text or "")
	if "<" not in text:
		return False
	found = {m.group(1) for m in _BPMN_TAG.finditer(text)}
	if not found:
		return False
	return bool(found & _STRONG_TAGS) or len(found) >= 2 or "<?xml" in text


def extract_xml(text: str) -> tuple[str, str, str]:
	"""(xml, text_before, text_after): the XML in a message, from a code fence or from its first tag to its last ``>``."""
	text = unescape_entities(text or "")
	for fence in _FENCE.finditer(text):
		if _BPMN_TAG.search(fence.group(1)):
			return fence.group(1).strip("\r\n"), text[: fence.start()], text[fence.end() :]
	first = _BPMN_TAG.search(text)
	declaration = text.find("<?xml")
	start = first.start() if first else 0
	if declaration != -1 and declaration <= start:
		start = declaration
	end = text.rfind(">") + 1
	if end <= start:
		end = len(text)
	return text[start:end], text[:start], text[end:]


def strip_diagram(xml: str) -> str:
	"""xml without its bpmndi:BPMNDiagram sections: coordinates only, no process meaning."""
	return _DIAGRAM.sub("", xml or "")


# ── Parsing ──────────────────────────────────────────────────────────────────


def _local(tag) -> str:
	return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _namespace(tag) -> str:
	if isinstance(tag, str) and tag.startswith("{"):
		return tag[1:].split("}", 1)[0]
	return ""


def _offset_position(text: str, offset: int) -> tuple[int, int]:
	"""1-based (line, column) of a character offset."""
	line = text.count("\n", 0, offset) + 1
	return line, offset - (text.rfind("\n", 0, offset) + 1) + 1


def _parse_error(xml: str, message: str, line: int, column: int) -> dict:
	"""A parse failure as the line, column, offending tag and offending source line."""
	lines = xml.split("\n")
	source = lines[line - 1].rstrip("\r") if 0 < line <= len(lines) else ""
	index = max(0, min(column - 1, max(len(source) - 1, 0)))
	opening = source.rfind("<", 0, index + 1)
	tag, name = "", ""
	if opening != -1:
		closing = source.find(">", opening)
		tag = source[opening : closing + 1 if closing != -1 else opening + 80]
		named = re.match(r"</?([\w.:-]+)", tag)
		name = named.group(1) if named else ""
	return {
		"message": _POSITION_SUFFIX.sub("", message).strip() or "not well-formed XML",
		"line": line,
		"column": column,
		"tag": name,
		"tag_text": tag.strip(),
		"source_line": source.strip()[:200],
	}


def parse_bpmn_xml(xml: str) -> tuple:
	"""(root, partial, error): the parsed tree, whether it needed namespace declarations added, or the failure.

	A fragment (a few elements, no ``definitions`` wrapper, undeclared ``bpmn:`` prefix, several roots) is parsed
	inside a wrapper that declares the usual BPMN prefixes. Anything else that is not well-formed is an error
	pointing at the line, column and tag where the parser stopped; nothing is guessed or repaired.
	"""
	xml = xml or ""
	dtd = _DTD.search(xml)
	if dtd:
		line, column = _offset_position(xml, dtd.start())
		return None, False, _parse_error(xml, "DOCTYPE and ENTITY declarations are not allowed in BPMN XML", line, column)
	try:
		return ET.fromstring(xml), False, None
	except ET.ParseError as exc:
		first = exc
	message = str(first)
	line, column = first.position if getattr(first, "position", None) else (1, 0)
	if "unbound prefix" in message or "junk after document element" in message:
		declarations = " ".join(f'xmlns:{p}="{u}"' for p, u in FRAGMENT_PREFIXES.items())
		body = _DECLARATION.sub(lambda m: " " * len(m.group(0)), xml)
		try:
			return ET.fromstring(f"<fragment {declarations}>{body}</fragment>"), True, None
		except ET.ParseError:
			pass
		if "unbound prefix" in message:
			message += " (declare the namespace, e.g. xmlns:bpmn=\"" + BPMN_NS + "\")"
	return None, False, _parse_error(xml, message, line, column + 1)


# ── Structural analysis ──────────────────────────────────────────────────────


def _issue(severity: str, tag: str, element_id: str, message: str, suggestion: str) -> dict:
	return {
		"severity": severity,
		"tag": "bpmn:" + tag if tag else "",
		"element_id": element_id or "",
		"message": message,
		"suggestion": suggestion,
	}


def analyze_bpmn_xml(xml: str) -> dict:
	"""Parse pasted BPMN XML and check its structure.

	Returns ``{"ok", "partial", "error", "counts", "nodes", "flows", "issues", "layout_elements"}``. ``ok`` is
	False only when the XML could not be parsed, in which case ``error`` holds the line, column and tag.
	"""
	root, partial, error = parse_bpmn_xml(xml)
	result = {
		"ok": error is None,
		"partial": partial,
		"error": error,
		"counts": {},
		"nodes": [],
		"flows": [],
		"issues": [],
		"layout_elements": 0,
	}
	if error:
		return result

	issues = result["issues"]
	nodes: dict[str, dict] = {}
	flows: list[dict] = []
	ids: dict[str, str] = {}
	signals, messages = set(), set()
	for el in root.iter():
		name = _local(el.tag)
		if _namespace(el.tag) in DI_NAMESPACES:
			result["layout_elements"] += 1
			continue
		element_id = el.get("id")
		if element_id:
			if element_id in ids:
				issues.append(
					_issue(
						"error",
						name,
						element_id,
						f"id '{element_id}' is already used by <bpmn:{ids[element_id]}>",
						"Give every element a unique id and update the sourceRef/targetRef values that point at it",
					)
				)
			ids[element_id] = name
		if name == "signal" and element_id:
			signals.add(element_id)
		elif name == "message" and element_id:
			messages.add(element_id)
		elif name == "sequenceFlow":
			flows.append(
				{
					"id": element_id or "",
					"source": el.get("sourceRef") or "",
					"target": el.get("targetRef") or "",
					"name": el.get("name") or "",
					"conditional": any(_local(c.tag) == "conditionExpression" for c in el),
				}
			)
		elif name in FLOW_NODE_TAGS:
			node = {"id": element_id or "", "tag": name, "name": el.get("name") or "", "el": el, "in": [], "out": []}
			if element_id:
				nodes[element_id] = node
			else:
				issues.append(
					_issue(
						"error",
						name,
						"",
						f"<bpmn:{name}{_name_attr(el)}> has no id attribute",
						'Add a unique id attribute, for example id="' + name[0].upper() + name[1:] + '_1"',
					)
				)
			result["nodes"].append(node)

	for flow in flows:
		_check_flow(flow, nodes, partial, issues)
		if flow["source"] in nodes:
			nodes[flow["source"]]["out"].append(flow["id"])
		if flow["target"] in nodes:
			nodes[flow["target"]]["in"].append(flow["id"])

	definitions = _local(root.tag) == "definitions"
	for node in result["nodes"]:
		_check_node(node, nodes, flows, partial, issues)
		_check_event_definitions(node, signals, messages, definitions and not partial, issues)

	for process in root.iter("{" + BPMN_NS + "}process"):
		_check_process(process, partial, issues)

	counts: dict[str, int] = {}
	for node in result["nodes"]:
		counts[node["tag"]] = counts.get(node["tag"], 0) + 1
	if flows:
		counts["sequenceFlow"] = len(flows)
	result["counts"] = counts
	result["flows"] = flows
	issues.sort(key=lambda i: {"error": 0, "warning": 1}.get(i["severity"], 2))
	return result


def _name_attr(el) -> str:
	return f' name="{el.get("name")}"' if el.get("name") else ""


def _check_flow(flow: dict, nodes: dict, partial: bool, issues: list) -> None:
	label = flow["id"] or f"({flow['source'] or '?'} -> {flow['target'] or '?'})"
	tail = " If this is only an excerpt, the element may sit outside the pasted part." if partial else ""
	if not flow["id"]:
		issues.append(
			_issue(
				"error",
				"sequenceFlow",
				"",
				f"sequenceFlow from '{flow['source'] or '?'}' to '{flow['target'] or '?'}' has no id attribute",
				'Add a unique id, for example id="Flow_1"',
			)
		)
	for attr, ref in (("sourceRef", flow["source"]), ("targetRef", flow["target"])):
		if not ref:
			issues.append(
				_issue(
					"error",
					"sequenceFlow",
					flow["id"],
					f"sequenceFlow {label} has no {attr} attribute",
					f"Set {attr} to the id of the element this flow {'leaves' if attr == 'sourceRef' else 'enters'}",
				)
			)
		elif ref not in nodes:
			close = difflib.get_close_matches(ref, list(nodes), n=2, cutoff=0.6)
			hint = f" Did you mean {' or '.join(repr(c) for c in close)}?" if close else ""
			issues.append(
				_issue(
					"warning" if partial else "error",
					"sequenceFlow",
					flow["id"],
					f"sequenceFlow {label} {attr}='{ref}' does not match any task, event or gateway id.{hint}{tail}",
					f"Correct {attr} to an existing element id, or add the missing element '{ref}'",
				)
			)
	if flow["source"] and flow["source"] == flow["target"]:
		issues.append(
			_issue(
				"warning",
				"sequenceFlow",
				flow["id"],
				f"sequenceFlow {label} loops from '{flow['source']}' back to itself",
				"Route the loop through a gateway or another step, or remove the flow",
			)
		)


def _check_node(node: dict, nodes: dict, flows: list, partial: bool, issues: list) -> None:
	tag, element_id, el = node["tag"], node["id"], node["el"]
	if not element_id:
		return
	severity = "warning" if partial else "error"
	incoming, outgoing = node["in"], node["out"]
	by_id = {f["id"]: f for f in flows}
	if tag == "startEvent":
		if incoming:
			issues.append(
				_issue(
					"error",
					tag,
					element_id,
					f"start event has incoming sequence flow {', '.join(incoming)}",
					f"A start event cannot be a flow target: change targetRef of {incoming[0]} to the first step, or remove it",
				)
			)
		if not outgoing:
			issues.append(
				_issue(
					severity,
					tag,
					element_id,
					"start event has no outgoing sequence flow",
					f'Add <bpmn:sequenceFlow sourceRef="{element_id}" targetRef="..."/> to the first step',
				)
			)
	elif tag == "endEvent":
		if outgoing:
			issues.append(
				_issue(
					"error",
					tag,
					element_id,
					f"end event has outgoing sequence flow {', '.join(outgoing)}",
					f"An end event cannot be a flow source: remove {outgoing[0]} or replace the end event with an intermediate event",
				)
			)
		if not incoming:
			issues.append(
				_issue(
					severity,
					tag,
					element_id,
					"end event has no incoming sequence flow",
					f'Add <bpmn:sequenceFlow sourceRef="..." targetRef="{element_id}"/> from the last step',
				)
			)
	elif tag == "boundaryEvent":
		attached = el.get("attachedToRef")
		if not attached:
			issues.append(
				_issue(
					"error",
					tag,
					element_id,
					"boundary event has no attachedToRef attribute",
					"Set attachedToRef to the id of the task or sub-process it is attached to",
				)
			)
		elif attached not in nodes and not partial:
			issues.append(
				_issue(
					"error",
					tag,
					element_id,
					f"boundary event attachedToRef='{attached}' does not match any task or sub-process id",
					"Correct attachedToRef to an existing task or sub-process id",
				)
			)
		if incoming:
			issues.append(
				_issue(
					"error",
					tag,
					element_id,
					f"boundary event has incoming sequence flow {', '.join(incoming)}",
					f"Boundary events start a path, they cannot receive one: change targetRef of {incoming[0]}",
				)
			)
		if not outgoing:
			issues.append(
				_issue(
					"warning",
					tag,
					element_id,
					"boundary event has no outgoing sequence flow, so triggering it ends nothing",
					f'Add <bpmn:sequenceFlow sourceRef="{element_id}" targetRef="..."/> to the handling step',
				)
			)
	elif el.get("isForCompensation") != "true" and el.get("triggeredByEvent") != "true":
		if not incoming:
			issues.append(
				_issue(
					severity,
					tag,
					element_id,
					"has no incoming sequence flow, so it can never be reached",
					f'Add <bpmn:sequenceFlow sourceRef="<predecessor id>" targetRef="{element_id}"/>',
				)
			)
		if not outgoing:
			issues.append(
				_issue(
					severity,
					tag,
					element_id,
					"has no outgoing sequence flow (dead end)",
					f'Add <bpmn:sequenceFlow sourceRef="{element_id}" targetRef="<next id>"/> or route it to an end event',
				)
			)
	if tag in TASK_TAGS | {"intermediateCatchEvent", "intermediateThrowEvent"} and not node["name"]:
		issues.append(
			_issue(
				"info",
				tag,
				element_id,
				"has no name, so it shows without a label",
				f'Add a name attribute describing what {element_id} does',
			)
		)
	if tag == "intermediateCatchEvent":
		for flow_id in incoming:
			source = nodes.get(by_id.get(flow_id, {}).get("source", ""))
			if source and source["tag"] in ("exclusiveGateway", "inclusiveGateway", "parallelGateway"):
				issues.append(
					_issue(
						"warning",
						tag,
						element_id,
						f"catch event is placed right after {source['tag']} {source['id']} (flow {flow_id}); "
						"that gateway decides on data and does not wait for events",
						f"To wait for one of several events, replace {source['id']} with a bpmn:eventBasedGateway; "
						"otherwise move the catch event after a task",
					)
				)
	if tag in ("exclusiveGateway", "inclusiveGateway"):
		_check_diverging(node, by_id, issues)
	elif tag == "parallelGateway":
		for flow_id in outgoing:
			if by_id.get(flow_id, {}).get("conditional"):
				issues.append(
					_issue(
						"warning",
						tag,
						element_id,
						f"outgoing flow {flow_id} has a conditionExpression, which a parallel gateway ignores",
						f"Remove the condition from {flow_id}, or use an exclusive or inclusive gateway",
					)
				)
	elif tag == "eventBasedGateway":
		if len(outgoing) < 2:
			issues.append(
				_issue(
					"warning",
					tag,
					element_id,
					"event-based gateway has fewer than two outgoing flows",
					"Give it one flow per event it waits for, each to a catch event or receive task",
				)
			)
		for flow_id in outgoing:
			target = nodes.get(by_id.get(flow_id, {}).get("target", ""))
			if target and target["tag"] not in ("intermediateCatchEvent", "receiveTask"):
				issues.append(
					_issue(
						"error",
						tag,
						element_id,
						f"outgoing flow {flow_id} leads to {target['tag']} {target['id']}, "
						"but an event-based gateway may only lead to catch events or receive tasks",
						f"Point {flow_id} at an intermediateCatchEvent or receiveTask, or use an exclusiveGateway",
					)
				)


def _check_diverging(node: dict, by_id: dict, issues: list) -> None:
	outgoing = node["out"]
	if len(outgoing) < 2:
		return
	default = node["el"].get("default") or ""
	if default and default not in outgoing:
		issues.append(
			_issue(
				"error",
				node["tag"],
				node["id"],
				f"default='{default}' is not one of this gateway's outgoing flows ({', '.join(outgoing)})",
				f"Set default to one of {', '.join(outgoing)}",
			)
		)
	unlabelled = [
		f
		for f in outgoing
		if f != default and not by_id.get(f, {}).get("conditional") and not by_id.get(f, {}).get("name")
	]
	for flow_id in unlabelled:
		issues.append(
			_issue(
				"warning",
				node["tag"],
				node["id"],
				f"outgoing flow {flow_id} has no condition or name, so the branch taken is undefined",
				f"Add a name or <bpmn:conditionExpression> to {flow_id}, or set default=\"{flow_id}\" on {node['id']}",
			)
		)


def _check_event_definitions(node: dict, signals: set, messages: set, check_refs: bool, issues: list) -> None:
	tag, element_id, el = node["tag"], node["id"], node["el"]
	definitions = [c for c in el if _local(c.tag).endswith("EventDefinition")]
	if tag in ("intermediateCatchEvent", "boundaryEvent") and not definitions:
		issues.append(
			_issue(
				"error",
				tag,
				element_id,
				"catch event has no event definition, so it is a blank event that can never be triggered",
				"Add one child such as <bpmn:messageEventDefinition/>, <bpmn:signalEventDefinition signalRef=\"...\"/> "
				"or <bpmn:timerEventDefinition>",
			)
		)
	for definition in definitions:
		kind = _local(definition.tag)
		if tag == "intermediateThrowEvent" and kind in CATCH_ONLY_DEFINITIONS:
			issues.append(
				_issue(
					"error",
					tag,
					element_id,
					f"throw event contains bpmn:{kind}, which can only be caught",
					"Change the element to bpmn:intermediateCatchEvent, or use a signal, message or link definition",
				)
			)
		if kind == "timerEventDefinition" and not any(
			_local(c.tag) in ("timeDate", "timeDuration", "timeCycle") for c in definition
		):
			issues.append(
				_issue(
					"error",
					tag,
					element_id,
					"bpmn:timerEventDefinition has no timeDate, timeDuration or timeCycle",
					'Add <bpmn:timeDuration>PT1H</bpmn:timeDuration> (or timeDate / timeCycle)',
				)
			)
		for kind_name, ref_attr, known in (
			("signalEventDefinition", "signalRef", signals),
			("messageEventDefinition", "messageRef", messages),
		):
			if kind != kind_name:
				continue
			ref = definition.get(ref_attr)
			noun = ref_attr[:-3]
			if not ref:
				issues.append(
					_issue(
						"warning",
						tag,
						element_id,
						f"bpmn:{kind} has no {ref_attr}, so it matches any {noun}",
						f'Declare <bpmn:{noun} id="..." name="..."/> under bpmn:definitions and set {ref_attr} to its id',
					)
				)
			elif check_refs and ref not in known:
				issues.append(
					_issue(
						"error",
						tag,
						element_id,
						f"bpmn:{kind} {ref_attr}='{ref}' does not match any bpmn:{noun} in the definitions",
						f'Add <bpmn:{noun} id="{ref}" name="..."/> under bpmn:definitions, or correct {ref_attr}',
					)
				)


def _check_process(process, partial: bool, issues: list) -> None:
	process_id = process.get("id") or ""
	tags = {_local(c.tag) for c in process.iter()}
	if not tags & FLOW_NODE_TAGS or process.get("isExecutable") is None and False:
		return
	severity = "warning" if partial else "error"
	for required in ("startEvent", "endEvent"):
		if required not in tags:
			issues.append(
				_issue(
					severity,
					"process",
					process_id,
					f"process has no {required}",
					f"Add a bpmn:{required} and connect it with a sequenceFlow",
				)
			)


# ── What the model is shown ──────────────────────────────────────────────────


def format_parse_error(error: dict) -> str:
	"""The parse failure as plain sentences naming line, column and tag."""
	where = f"line {error['line']}, column {error['column']} of the pasted XML"
	tag = f" at tag <{error['tag']}>" if error.get("tag") else ""
	lines = [f"The pasted BPMN XML could not be parsed: {error['message']} ({where}{tag})."]
	if error.get("source_line"):
		lines.append("Offending line: " + error["source_line"])
	return "\n".join(lines)


def _format_issue(issue: dict) -> str:
	where = " ".join(p for p in (issue["tag"], f"id={issue['element_id']}" if issue["element_id"] else "") if p)
	return f"- [{issue['severity'].upper()}] {where}: {issue['message']}. Fix: {issue['suggestion']}"


def build_analysis_block(analysis: dict, max_chars: int = MAX_ANALYSIS_CHARS) -> str:
	"""The text the model receives in place of its own reading of the paste, capped at ``max_chars``.

	Findings come first and the element list after them, so a cap cuts the least useful part first. The
	bpmndi layout section is only counted.
	"""
	if not analysis["ok"]:
		block = [
			"PASTED BPMN XML PARSE FAILURE (found by the server before this turn):",
			format_parse_error(analysis["error"]),
			"Tell the user this exact failure, with its line, column and tag, and say how to correct it "
			"(for example close or rename the tag, quote the attribute value, or declare the namespace). "
			"Do NOT fall back to asking for a plain-text list of steps, and do not ask them to re-type the process.",
		]
		return "\n".join(block)[:max_chars]

	issues = analysis["issues"]
	errors = sum(1 for i in issues if i["severity"] == "error")
	warnings = sum(1 for i in issues if i["severity"] == "warning")
	block = [
		"PASTED BPMN XML ANALYSIS (parsed by the server, so treat it as the user's process definition):",
		"Input: " + ("a partial BPMN fragment" if analysis["partial"] else "a BPMN 2.0 document"),
		"Elements: " + (", ".join(f"{n} {t}" for t, n in analysis["counts"].items()) or "no BPMN flow elements found"),
		f"Findings: {errors} error(s), {warnings} warning(s), {len(issues) - errors - warnings} note(s)",
	]
	block += [_format_issue(i) for i in issues[:MAX_LISTED_ISSUES]]
	if len(issues) > MAX_LISTED_ISSUES:
		block.append(f"- ... and {len(issues) - MAX_LISTED_ISSUES} more findings not listed")
	block.append("Flow elements (id, name, flows in -> out):")
	for node in analysis["nodes"][:MAX_LISTED_ELEMENTS]:
		name = f' "{node["name"]}"' if node["name"] else ""
		block.append(
			f"- bpmn:{node['tag']} {node['id'] or '(no id)'}{name} in=[{', '.join(node['in'])}] out=[{', '.join(node['out'])}]"
		)
	if len(analysis["nodes"]) > MAX_LISTED_ELEMENTS:
		block.append(f"- ... and {len(analysis['nodes']) - MAX_LISTED_ELEMENTS} more elements not listed")
	block.append("Sequence flows (id: source -> target):")
	for flow in analysis["flows"][:MAX_LISTED_FLOWS]:
		label = f' ("{flow["name"]}")' if flow["name"] else ""
		block.append(f"- {flow['id'] or '(no id)'}: {flow['source'] or '?'} -> {flow['target'] or '?'}{label}")
	if len(analysis["flows"]) > MAX_LISTED_FLOWS:
		block.append(f"- ... and {len(analysis['flows']) - MAX_LISTED_FLOWS} more flows not listed")
	if analysis["layout_elements"]:
		block.append(
			f"Diagram layout (bpmndi): {analysis['layout_elements']} shape/edge/bounds elements skipped; "
			"they hold coordinates only and say nothing about the process."
		)
	text = "\n".join(block)
	if len(text) > max_chars:
		text = text[: max_chars - 40].rstrip() + "\n... [analysis truncated to fit]"
	return text


def _fit_message(before: str, xml: str, after: str, error: dict | None) -> str | None:
	"""A shorter version of a very large paste for the model, or None when it is small enough as it is.

	The layout section goes first. If the semantic XML is still too long it is left out (the analysis block
	carries it) or, when it does not parse, cut to the lines around the failure.
	"""
	if len(xml) <= MAX_RAW_XML_CHARS:
		return None
	slim = strip_diagram(xml)
	note = f"[Pasted BPMN XML was {len(xml)} characters; "
	if len(slim) <= MAX_RAW_XML_CHARS:
		body = note + "the bpmndi:BPMNDiagram layout section was removed, the process definition is complete.]\n```xml\n" + slim + "\n```"
	elif error:
		lines = xml.split("\n")
		start = max(0, error["line"] - 1 - ERROR_EXCERPT_LINES)
		excerpt = "\n".join(lines[start : error["line"] + ERROR_EXCERPT_LINES])[:MAX_RAW_XML_CHARS]
		body = note + f"only the lines around the parse failure (line {error['line']}) are shown.]\n```xml\n" + excerpt + "\n```"
	else:
		body = note + "the XML itself is omitted and is summarised in the parsed analysis.]"
	return "\n\n".join(p.strip() for p in (before, body, after) if p.strip())


def prepare_turn(message: str) -> dict | None:
	"""Everything the chat turn needs when the message holds BPMN XML; None when it is ordinary text.

	``{"analysis", "block", "message_override"}`` where ``message_override`` is a size-safe replacement for the
	message, or None to leave it as typed.
	"""
	if not is_bpmn_xml(message):
		return None
	xml, before, after = extract_xml(message)
	analysis = analyze_bpmn_xml(xml)
	return {
		"analysis": analysis,
		"block": build_analysis_block(analysis),
		"message_override": _fit_message(before, xml, after, analysis["error"]),
	}


XML_INPUT_RULES = (
	"BPMN XML INPUT RULES: the user's message contains BPMN 2.0 XML (a complete document or a fragment). "
	"It is a structured process definition, not conversational text. Read it from the parsed analysis above; "
	"never ask the user to re-type the steps as a plain list, and never ask them to describe a process they have "
	"already pasted. Answer with intent GENERAL unless they also ask you to change the diagram. Summarise the "
	"process (its tasks, events, gateways and how sequence flows connect them), then give each finding as a "
	"specific, actionable suggestion that names the element id, the tag and the sequenceFlow involved. If the "
	"analysis reports a parse failure, state that failure with its line, column and tag, and how to correct it. "
	"Ignore bpmndi layout data; it is coordinates only."
)
