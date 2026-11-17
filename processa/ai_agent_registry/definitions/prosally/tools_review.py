"""ProsAlly answers without a redraw: diagnose an error, compare with a spec, tidy the layout, type plain tasks."""

import html
import json
import re
from xml.etree import ElementTree as ET

import frappe
from frappe import _

from processa.ai_agent_memory.text_clean import strip_html
from processa.ai_agent_registry.definitions.prosally.helpers import (
	NS,
	REQUEST_STOPWORDS,
	STEP_TAGS,
	complete_sub_prompt,
	confirmation_reply,
	prosally_config,
	quoted,
	register_namespaces,
)
from processa.ai_agent_registry.definitions.prosally.tools_pipeline import (
	compile_ir,
	element_names,
	has_lanes,
)
from processa.ai_agent_registry.definitions.prosally.tools_properties import transfer_properties
from processa.ai_agent_registry.definitions.shared.helpers import extract_json

DIAGNOSE_ERROR_CHARS = 3000
DIAGNOSE_ELEMENT_CHARS = 1500
DIAGNOSE_MAX_ELEMENTS = 5
DIAGNOSE_SCRIPT_CHARS = 4000
DIAGNOSE_MIN_NAME_CHARS = 3
DIAGNOSE_ORIGINS = frozenset({"map", "server_script", "unknown"})

IR_NODE_TYPES = frozenset(
	{
		"startEvent", "endEvent", "intermediateThrowEvent", "intermediateCatchEvent", "task", "userTask", "scriptTask",
		"serviceTask", "manualTask", "businessRuleTask", "exclusiveGateway", "parallelGateway", "inclusiveGateway",
		"subProcess", "callActivity",
	}
)  # fmt: skip


def xml_to_ir(xml: str) -> dict | None:
	"""The IR that draws xml again, or None when xml has an element the IR cannot hold."""
	bpmn = "{" + NS["bpmn"] + "}"
	process = next(iter(ET.fromstring(xml).iter(bpmn + "process")), None)
	if process is None:
		return None
	lane_of = {}
	lanes = []
	for lane in process.iter(bpmn + "lane"):
		lanes.append({"id": lane.get("id"), "name": lane.get("name") or lane.get("id")})
		for ref in lane.findall(bpmn + "flowNodeRef"):
			lane_of[(ref.text or "").strip()] = lane.get("id")

	def scope(parent):
		nodes, flows = [], []
		for elem in parent:
			tag = elem.tag.removeprefix(bpmn)
			if tag in IR_NODE_TYPES:
				node = {"id": elem.get("id"), "name": elem.get("name") or "", "type": tag}
				if elem.get("id") in lane_of:
					node["lane"] = lane_of[elem.get("id")]
				if elem.get("calledElement"):
					node["calledElement"] = elem.get("calledElement")
				if tag == "subProcess":
					inner = scope(elem)
					if inner is None:
						return None
					node["children"] = inner
				nodes.append(node)
			elif tag == "sequenceFlow":
				flow = {"id": elem.get("id"), "from": elem.get("sourceRef"), "to": elem.get("targetRef")}
				if elem.get("name"):
					flow["name"] = elem.get("name")
				body = elem.find(bpmn + "conditionExpression")
				if body is not None and body.text:
					flow["condition"] = body.text
				if parent.get("default") == elem.get("id"):
					flow["default"] = True
				flows.append(flow)
			elif tag not in ("laneSet", "extensionElements", "incoming", "outgoing", "documentation"):
				return None
		return {"nodes": nodes, "flows": flows}

	body = scope(process)
	if body is None:
		return None
	kind = {} if process.get("isExecutable", "false").strip().lower() == "true" else {"executable": False}
	return {"name": process.get("name") or "", "lanes": lanes, **kind, **body}


def diagram_geometry(xml: str) -> list:
	"""Every drawn shape and arrow of xml with its position, in a stable order."""
	bpmndi, dc, di = ("{" + NS[prefix] + "}" for prefix in ("bpmndi", "dc", "di"))
	drawn = []
	for elem in ET.fromstring(xml).iter():
		if elem.tag in (bpmndi + "BPMNShape", bpmndi + "BPMNEdge"):
			points = [(b.get("x"), b.get("y"), b.get("width"), b.get("height")) for b in elem.iter(dc + "Bounds")]
			points += [(p.get("x"), p.get("y")) for p in elem.iter(di + "waypoint")]
			drawn.append((elem.get("bpmnElement"), tuple(points)))
	return sorted(drawn)


def relayout(xml: str) -> tuple[str | None, str]:
	"""(new xml, "") with the diagram drawn again and every id and setting kept; (None, reason) when it cannot be."""
	if not has_lanes(xml):
		return None, "lane-less"
	ir = xml_to_ir(xml)
	if ir is None:
		return None, "unsupported"
	compiled = compile_ir(ir)
	if not compiled.get("ok") or not compiled.get("xml"):
		return None, "failed"
	merged, _removed = transfer_properties(xml, compiled["xml"])
	if element_names(merged).keys() != element_names(xml).keys():
		return None, "ids-changed"
	if diagram_geometry(merged) == diagram_geometry(xml):
		return None, "same"
	return merged, ""


LIST_ITEM = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)]|[a-z][.)])\s+(.+?)\s*$", re.I)


def spec_items(text: str) -> list[str]:
	"""The bulleted or numbered lines of text, or dash items run together after a comma or colon, without their markers."""
	plain = html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"<(?:br|/p|/li|/div)[^>]*>", "\n", text or "")))
	lines = re.sub(r"[,:]\s+(?=[-*\u2022]\s)", "\n", plain).splitlines()
	return [m.group(1) for line in lines if (m := LIST_ITEM.match(line))]


def missing_spec_items(xml: str, spec: str) -> list[str]:
	"""The list items of spec with no step on the diagram that holds at least 60% of the item's significant words."""

	def stems(text):
		return {word[:5] for word in re.findall(r"[a-z]{4,}", text.lower()) if word not in REQUEST_STOPWORDS}

	steps = [stems(e.get("name")) for e in ET.fromstring(xml).iter() if e.tag in STEP_TAGS and e.get("name")]
	return [
		item
		for item in spec_items(spec)
		if len(item.split()) > 1 and not any(stems(item) and len(stems(item) & step) / len(stems(item)) >= 0.6 for step in steps)
	]


def compare_output(xml: str, texts: list) -> dict:
	"""The reply to a pasted specification asked about "what is missing": the gaps, and a question before adding them."""
	spec = next((text for text in texts if len(spec_items(text or "")) > 1), "")
	if not spec:
		return {
			"intent": "CLARIFY",
			"response": _("Paste the list of steps you want to check, one per line, and I will tell you which are missing."),
		}
	missing = missing_spec_items(xml, spec)
	if not missing:
		return {"intent": "CLARIFY", "response": _("Every item in your list is already on the diagram, so I changed nothing.")}
	listing = "\n".join("- " + item for item in missing)
	return {
		"intent": "CONFIRM",
		"action_intent": "MODIFY_EXISTING",
		"response": _("These items from your list are not on the diagram:") + "\n" + listing + "\n\n" + _("Shall I add them?"),
		"options": [_("Yes, proceed"), _("No, let me adjust")],
	}


def diagnose_inputs(xml: str, error_text: str, lint_issues: list) -> dict:
	"""The pasted error, the lint findings and the diagram elements it names, each capped."""
	elements = {}
	if (xml or "").strip():
		register_namespaces()
		elements = {e.get("id"): e for e in ET.fromstring(xml).iter() if e.get("id")}
	named = [i for i, e in elements.items() if _mentions(error_text, i) or _mentions(error_text, e.get("name"))]
	findings = [i for i in lint_issues or [] if i.get("id") in named]
	return {
		"error": error_text[-DIAGNOSE_ERROR_CHARS:],
		"lint_findings": findings,
		"elements": [ET.tostring(elements[i], encoding="unicode")[:DIAGNOSE_ELEMENT_CHARS] for i in named[:DIAGNOSE_MAX_ELEMENTS]],
		"script_task": script_task_for_error(xml, error_text),
	}


def _mentions(text: str, value: str | None) -> bool:
	"""True when a name or id of at least a few characters appears in the text."""
	return bool(value) and len(value) >= DIAGNOSE_MIN_NAME_CHARS and value in text


def script_task_for_error(xml: str, error_text: str) -> dict | None:
	"""The script task an error names by task id, task name or Server Script, with the script source when readable."""
	if not (xml or "").strip():
		return None
	register_namespaces()
	script_attribute = "{" + NS["spiffworkflow"] + "}serverScript"
	for task in ET.fromstring(xml).iter("{" + NS["bpmn"] + "}scriptTask"):
		script_name = task.get(script_attribute) or ""
		if not any(_mentions(error_text, value) for value in (task.get("id"), task.get("name"), script_name)):
			continue
		readable = frappe.db.exists("Server Script", script_name) and frappe.has_permission(
			"Server Script", "read", doc=script_name
		)
		source = frappe.db.get_value("Server Script", script_name, "script") if readable else ""
		return {
			"id": task.get("id"),
			"name": task.get("name") or "",
			"script_name": script_name,
			"script": (source or "")[:DIAGNOSE_SCRIPT_CHARS],
		}
	return None


def diagnose_output(xml: str, texts: list, lint_issues: list) -> dict:
	"""The reply to a pasted error or a lint finding: the cause and the fix, or a fallback with manual steps."""
	error_text = next((strip_html(text) for text in texts if text and not confirmation_reply(text)), "")
	inputs = {}
	diagnosis = None
	try:
		inputs = diagnose_inputs(xml, error_text, lint_issues)
		raw = complete_sub_prompt(prosally_config(), "error_diagnoser", json.dumps(inputs))
		diagnosis = extract_json(raw)
	except Exception:
		frappe.log_error(title="ProsAlly could not diagnose an error")
	if not diagnosis or diagnosis.get("origin") not in DIAGNOSE_ORIGINS or not diagnosis.get("root_cause"):
		return {"intent": "CLARIFY", "response": diagnose_fallback_reply()}
	steps = [str(step) for step in diagnosis.get("fix_steps") or []]
	body = diagnosis["root_cause"] + ("\n\n" + "\n".join("- " + step for step in steps) if steps else "")
	if diagnosis["origin"] == "server_script":
		task = inputs.get("script_task")
		lead = _("This error comes from a server script, not from the process map, so changing the map will not fix it.")
		if task:
			lead = _(
				'This error comes from the script behind the task "{0}", not from the process map configuration, so changing the map will not fix it.'
			).format(task["name"] or task["id"])
		return {"intent": "CLARIFY", "response": lead + "\n\n" + body + "\n\n" + _("Open the script in Logix to make this change.")}
	if diagnosis["origin"] == "unknown":
		return {"intent": "CLARIFY", "response": body + "\n\n" + diagnose_fallback_reply()}
	return {
		"intent": "CONFIRM",
		"action_intent": "MODIFY_EXISTING",
		"response": _("The cause is in the process map.") + "\n\n" + body + "\n\n" + _("Shall I apply this fix to the diagram?"),
		"options": [_("Yes, proceed"), _("No, let me adjust")],
	}


def diagnose_fallback_reply() -> str:
	"""What to try when ProsAlly cannot find the cause of an error."""
	return _(
		"I could not work out the cause of this error. You can:\n"
		"- Open the Error Log for this process and paste the full traceback here.\n"
		"- Check the configuration of the task, event or gateway named in the error.\n"
		"- Ask Logix if the error mentions a server script.\n"
		"- Contact your Processa administrator with the error text."
	)


def relayout_output(xml: str) -> dict:
	"""The reply to a confirmed re-layout: the diagram drawn again, or why nothing changed, and what the person can do."""
	new_xml, reason = relayout(xml)
	if new_xml:
		return {
			"intent": "BPMN_MODIFIED",
			"action_intent": "RELAYOUT",
			"bpmn_xml": new_xml,
			"response": _("I laid the diagram out again. Every step, arrow and setting is kept. Review it on the canvas.")
			+ " "
			+ layout_is_automatic(),
			"options": [],
		}
	if reason == "same":
		say = _("The layout is already the best I can make, so I changed nothing.")
	elif reason == "lane-less":
		say = _("This diagram has no lanes, so the editor lays it out itself. I changed nothing.")
	else:
		say = _("I could not lay the diagram out again without risking your steps, so I changed nothing.")
	return {"intent": "CLARIFY", "response": say + " " + layout_is_automatic()}


def layout_is_automatic() -> str:
	"""What a person can do about the layout, since no single arrow, label or colour is placed by hand."""
	return _(
		"Layout is computed automatically, so I cannot place one arrow, label or colour by hand. "
		"You can drag shapes on the canvas, or change the flow structure and I will lay it out again."
	)


LANE_MOVE_VERBS = r"\b(?:move|put|bring|shift|place|drag|relocate)\b"
# Words a move may carry before the lane is named, and after it, without asking for anything else.
LANE_MOVE_LEAD = re.compile(LANE_MOVE_VERBS + r"|\b(?:back|the|and|both|steps?|tasks?|please)\b", re.I)
LANE_MOVE_TAIL = re.compile(r"\b(?:lane|swimlane|swim|please)\b", re.I)


def move_to_lane_output(xml: str, text: str) -> dict | None:
	"""The reply to "move this step to that lane": the step moved and the diagram laid out again, no redraw by a model."""
	move = lane_move(xml, text)
	if not move:
		return None
	register_namespaces()
	bpmn = "{" + NS["bpmn"] + "}"
	root = ET.fromstring(xml)
	moving = {step["id"] for step in move["steps"]}
	for lane in root.iter(bpmn + "lane"):
		for ref in [r for r in lane.findall(bpmn + "flowNodeRef") if (r.text or "").strip() in moving]:
			lane.remove(ref)
		if lane.get("id") == move["lane"]["id"]:
			for step in move["steps"]:
				ET.SubElement(lane, bpmn + "flowNodeRef").text = step["id"]
	moved = ET.tostring(root, encoding="unicode", xml_declaration=True)
	new_xml, _reason = relayout(re.sub(r"^<\?xml\s[^?]*\?>", '<?xml version="1.0" encoding="UTF-8"?>', moved))
	if not new_xml:
		return None
	return {
		"intent": "BPMN_MODIFIED",
		"action_intent": "MOVE_TO_LANE",
		"bpmn_xml": new_xml,
		"response": _(
			"I moved {0} to the lane {1}. Every step, arrow and setting is kept. Review it on the canvas."
		).format(", ".join(quoted(step["name"]) for step in move["steps"]), quoted(move["lane"]["name"])),
		"options": [],
	}


def lane_move(xml: str, text: str) -> dict | None:
	"""The steps and the lane of a message that only asks to move steps on the diagram into one of its lanes."""
	if not has_lanes(xml) or not re.search(LANE_MOVE_VERBS, text, re.I):
		return None
	bpmn = "{" + NS["bpmn"] + "}"
	root = ET.fromstring(xml)
	lanes = [(_name_pattern(e.get("name") or ""), e) for e in root.iter(bpmn + "lane")]
	where = lane = None
	for pattern, candidate in sorted(lanes, key=lambda found: -len(found[0])):
		where = pattern and re.search(r"\b(?:in\s?to|to|under|in)\s+(?:the\s+)?" + pattern, text, re.I)
		if where:
			lane = candidate
			break
	if lane is None:
		return None
	here = {(ref.text or "").strip() for ref in lane.findall(bpmn + "flowNodeRef")}
	asked = text[: where.start()]
	steps = []
	# Only top-level steps sit in a lane; a step inside a sub-process moves with it.
	named = [(_name_pattern(e.get("name") or ""), e) for p in root.iter(bpmn + "process") for e in p if e.tag in STEP_TAGS]
	for pattern, step in sorted(named, key=lambda found: -len(found[0])):
		if not pattern:
			continue
		# A step whose own name runs into the lane phrase makes the message read two ways.
		if any(m.start() < where.end() and m.end() > where.start() for m in re.finditer(pattern, text, re.I)):
			return None
		asked, found = re.subn(pattern, " ", asked, flags=re.I)
		if not found:
			continue
		if sum(1 for other, _elem in named if other == pattern) > 1:
			return None
		if step.get("id") not in here:
			steps.append({"id": step.get("id"), "name": step.get("name")})
	# Anything else the message asks for is a change to the process, which this move would drop.
	rest = LANE_MOVE_LEAD.sub(" ", asked) + " " + LANE_MOVE_TAIL.sub(" ", text[where.end() :])
	if not steps or re.search(r"\w", rest):
		return None
	return {"steps": steps, "lane": {"id": lane.get("id"), "name": lane.get("name")}}


def _name_pattern(name: str) -> str:
	"""A pattern for name as a person types it, whole words only; empty when name has no letter or digit."""
	words = [re.escape(word) for word in re.split(r"[\W_]+", name) if word]
	return r"\b" + r"[\s\-]*".join(words) + r"\b" if words else ""


NONE_TASK_KEPT_ATTRIBUTES = ("id", "name", "default")
NONE_TASK_KEPT_CHILDREN = ("incoming", "outgoing", "documentation")


def none_tasks_output(xml: str) -> dict:
	"""The reply to a confirmed replace-all-with-None: every typed task made a plain task, or why nothing changed."""
	if not (xml or "").strip():
		return {"intent": "CLARIFY", "response": _("There is no diagram yet, so I changed nothing.")}
	root = ET.fromstring(xml)
	bpmn = "{" + NS["bpmn"] + "}"
	if any(p.get("isExecutable", "false").strip().lower() == "true" for p in root.iter(bpmn + "process")):
		return {
			"intent": "CLARIFY",
			"response": _("Only a non-executable process can use None tasks. This process is executable, so I changed nothing."),
		}
	register_namespaces()
	typed = [bpmn + tag for tag in ("userTask", "serviceTask", "scriptTask", "manualTask", "businessRuleTask")]
	changed = 0
	for elem in root.iter():
		if elem.tag not in typed:
			continue
		elem.tag = bpmn + "task"
		for attr in [a for a in elem.attrib if a not in NONE_TASK_KEPT_ATTRIBUTES]:
			del elem.attrib[attr]
		for child in [c for c in elem if c.tag.removeprefix(bpmn) not in NONE_TASK_KEPT_CHILDREN]:
			elem.remove(child)
		changed += 1
	if not changed:
		return {"intent": "CLARIFY", "response": _("Every task is already a None task, so I changed nothing.")}
	new_xml = ET.tostring(root, encoding="unicode", xml_declaration=True)
	new_xml = re.sub(r"^<\?xml\s[^?]*\?>", '<?xml version="1.0" encoding="UTF-8"?>', new_xml)
	return {
		"intent": "BPMN_MODIFIED",
		"action_intent": "TASKS_TO_NONE",
		"bpmn_xml": new_xml,
		"response": _("I made {0} tasks None tasks. Every step, arrow and name is kept, and the task settings are removed. Review it on the canvas.").format(changed),
		"options": [],
	}


def keep_process_kind(ir: dict, xml: str) -> None:
	"""Mark ir non-executable, in place, when the diagram being modified is, so its tasks stay None tasks."""
	if not (xml or "").strip():
		return
	flags = [p.get("isExecutable", "false").strip().lower() for p in ET.fromstring(xml).iter("{" + NS["bpmn"] + "}process")]
	if flags and "true" not in flags:
		ir["executable"] = False
