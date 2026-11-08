"""ProsAlly finds the step or subprocess a request names and draws subprocesses into the diagram."""

import copy
import difflib
import re
from xml.etree import ElementTree as ET

import frappe

from one_bpmn.agents.memory.text_clean import strip_html
from one_bpmn.ai_agent_registry.definitions.prosally.helpers import (
	DIAGRAM_REPLIES,
	NS,
	STEP_TAGS,
	confirmation_reply,
	register_namespaces,
)
from one_bpmn.ai_agent_registry.definitions.prosally.tools_pipeline import element_names

SUBPROCESS_KEPT_TAGS = tuple(
	"{" + NS["bpmn"] + "}" + tag for tag in ("incoming", "outgoing", "extensionElements", "documentation")
)
ID_REF_ATTRS = ("id", "sourceRef", "targetRef", "bpmnElement", "default", "attachedToRef")

SUBPROCESS_REQUEST = re.compile(r"sub[\s-]?process\s+(?:for|of|on)\s+(?:the\s+)?(?:step\s+)?([^:,.;\n]+)", re.I)
BECOME_SUBPROCESS = re.compile(
	r"([^:,.;\n]+?)\s+(?:should\s+be|must\s+be|needs?\s+to\s+be|to\s+be|become|becomes|into|as|a|an)\s+(?:a\s+|an\s+)?(?:expanded\s+)?sub[\s-]?process",
	re.I,
)

RECENT_REPLIES = 10
DEFINITE_SUBPROCESS = re.compile(r"(?<!new\s)\b(?:the|that|this|my|your)\s+sub[\s-]?p(?:ro|or)ces{1,2}\b", re.I)
TYPO_SIMILARITY = 0.75
POSITION_WORDS = (
	r"\b(?:after|before|following|preceding|then|next\s+to|beside|alongside|near|adjacent\s+to|above|below)\s+(?:the\s+|a\s+)?$"
)
CALL_ACTIVITY_CONVERSION = re.compile(
	r"\b(?:as|into|to)\s+(?:a\s+|an\s+)?call[\s-]?activit|\b(?:make|turn|convert|change)\b[^.:]{0,80}\bcall[\s-]?activit", re.I
)
EXPANDED_PAD = 24
EXPANDED_HEADER = 36


def resolve_scope(xml: str, texts: list, scope_id: str = "") -> dict | None:
	"""The sub-process a request is about: the one open on the canvas, else the one the newest message names."""
	if not (xml or "").strip():
		return None
	register_namespaces()
	subs = {e.get("id"): e for e in ET.fromstring(xml).iter("{" + NS["bpmn"] + "}subProcess") if e.get("id")}
	chosen = subs.get(scope_id)
	for text in texts:
		if chosen is not None:
			break
		named = [e for e in subs.values() if e.get("name") and _is_named(text or "", e.get("name"))]
		outermost = [e for e in named if not any(e is not o and e.get("name").lower() in o.get("name").lower() for o in named)]
		if len(outermost) > 1:
			return None
		if outermost:
			chosen = outermost[0]
	if chosen is None:
		return None
	return {"id": chosen.get("id"), "name": chosen.get("name") or chosen.get("id"), "xml": ET.tostring(chosen, encoding="unicode")}


def _is_named(text: str, name: str) -> bool:
	"""True when text names the sub-process as the thing to edit, not as a place to put a step before or after."""
	pattern = r"[\s\-]*".join(re.escape(word) for word in re.split(r"[^A-Za-z0-9]+", name) if word)
	for match in re.finditer(pattern, text, re.I):
		if not re.search(POSITION_WORDS, text[: match.start()], re.I):
			return True
	return False


def splice_subprocess(xml: str, child_xml: str, scope_id: str) -> str:
	"""xml with the sub-process scope_id holding the steps compiled in child_xml and its own plane redrawn."""
	register_namespaces()
	root = ET.fromstring(xml)
	child_root = ET.fromstring(child_xml)
	bpmn, bpmndi = "{" + NS["bpmn"] + "}", "{" + NS["bpmndi"] + "}"
	sub = next(e for e in root.iter(bpmn + "subProcess") if e.get("id") == scope_id)
	for step in [e for e in sub if e.tag not in SUBPROCESS_KEPT_TAGS]:
		sub.remove(step)
	for diagram in root.findall(bpmndi + "BPMNDiagram"):
		if diagram.find(bpmndi + "BPMNPlane").get("bpmnElement") == scope_id:
			root.remove(diagram)
	di_prefixes = tuple("{" + NS[prefix] for prefix in ("bpmndi", "dc", "di"))
	semantic = {e.get("id") for e in root.iter() if e.get("id") and not e.tag.startswith(di_prefixes)}
	for diagram in root.findall(bpmndi + "BPMNDiagram"):
		plane = diagram.find(bpmndi + "BPMNPlane")
		for gone in [e for e in plane if e.get("bpmnElement") not in semantic]:
			plane.remove(gone)
		for shape in plane.findall(bpmndi + "BPMNShape"):
			if shape.get("bpmnElement") == scope_id:
				shape.set("isExpanded", "false")

	_rename_taken_ids(child_root, {e.get("id") for e in root.iter() if e.get("id")}, scope_id)
	sub.extend(child_root.find(bpmn + "process"))
	for scope in sub.iter(bpmn + "subProcess"):
		add_flow_references(scope)
	for diagram in child_root.findall(bpmndi + "BPMNDiagram"):
		diagram.set("id", "BPMNDiagram_" + scope_id)
		plane = diagram.find(bpmndi + "BPMNPlane")
		plane.set("id", "BPMNPlane_" + scope_id)
		plane.set("bpmnElement", scope_id)
		root.append(diagram)
	spliced = ET.tostring(root, encoding="unicode", xml_declaration=True)
	return re.sub(r"^<\?xml\s[^?]*\?>", '<?xml version="1.0" encoding="UTF-8"?>', spliced)


def _rename_taken_ids(child_root: ET.Element, taken: set, suffix: str) -> None:
	"""Rename every id in child_root that is already in taken, and every reference to it."""
	bpmn = "{" + NS["bpmn"] + "}"
	renames = {e.get("id"): e.get("id") + "_" + suffix for e in child_root.iter() if e.get("id") in taken}
	for e in child_root.iter():
		for attr in ID_REF_ATTRS:
			if e.get(attr) in renames:
				e.set(attr, renames[e.get(attr)])
		if e.tag in (bpmn + "incoming", bpmn + "outgoing") and e.text in renames:
			e.text = renames[e.text]


def add_flow_references(scope: ET.Element) -> None:
	"""Give each step of scope the incoming and outgoing flow references the editor and its linter read."""
	bpmn = "{" + NS["bpmn"] + "}"
	steps = {e.get("id"): e for e in scope if e.get("id") and e.tag != bpmn + "sequenceFlow"}
	for flow in scope.findall(bpmn + "sequenceFlow"):
		for ref, tag in ((flow.get("sourceRef"), "outgoing"), (flow.get("targetRef"), "incoming")):
			step = steps.get(ref)
			if step is not None and flow.get("id") not in [c.text for c in step.findall(bpmn + tag)]:
				ET.SubElement(step, bpmn + tag).text = flow.get("id")


def restore_call_activities(old_xml: str, new_xml: str) -> str:
	"""new_xml with each call activity of old_xml put back as it was, so a modify never changes one."""
	register_namespaces()
	call = "{" + NS["bpmn"] + "}callActivity"
	bpmn = "{" + NS["bpmn"] + "}"
	originals = {e.get("id"): e for e in ET.fromstring(old_xml).iter(call) if e.get("id")}
	if not originals:
		return new_xml
	root = ET.fromstring(new_xml)
	for parent in list(root.iter()):
		for index, child in enumerate(list(parent)):
			original = originals.get(child.get("id"))
			if original is not None:
				kept = copy.deepcopy(original)
				for reference in [c for c in kept if c.tag in (bpmn + "incoming", bpmn + "outgoing")]:
					kept.remove(reference)
				parent[index] = kept
	restored = ET.tostring(root, encoding="unicode", xml_declaration=True)
	return re.sub(r"^<\?xml\s[^?]*\?>", '<?xml version="1.0" encoding="UTF-8"?>', restored)


def unapplied_proposal(conversation: str, current_xml: str, message: str = "") -> dict | None:
	"""What the newest diagram reply adds that the canvas lacks, the request behind it, and which of those the message names."""
	if not (current_xml or "").strip():
		return None
	replies = frappe.get_all(
		"Chat Message",
		filters={"conversation": conversation, "message_type": "Bot"},
		fields=["metadata", "creation"],
		order_by="creation desc",
		limit=RECENT_REPLIES,
	)
	found = [(frappe.parse_json(reply.metadata or "{}").get("agent_result"), reply.creation) for reply in replies]
	result, replied_at = next(
		((r, at) for r, at in found if isinstance(r, dict) and r.get("intent") in DIAGRAM_REPLIES and r.get("bpmn_xml")),
		(None, None),
	)
	if result is None:
		return None
	on_canvas = element_names(current_xml)
	proposed = [
		(kind, name)
		for element_id, (kind, name) in element_names(result["bpmn_xml"]).items()
		if name and kind != "sequenceFlow" and element_id not in on_canvas
	]
	if not proposed:
		return None
	added = [name for _, name in proposed]
	earlier = frappe.get_all(
		"Chat Message",
		filters={"conversation": conversation, "message_type": "User", "creation": ["<", replied_at]},
		fields=["text"],
		order_by="creation desc",
		limit=RECENT_REPLIES,
	)
	request = next((strip_html(m.text) for m in earlier if m.text and not confirmation_reply(m.text)), "")
	named = [name for name in added if _squash(name) in _squash(message or "")]
	existing = [name for kind, name in on_canvas.values() if kind == "subProcess" and name]
	refers_to_it = DEFINITE_SUBPROCESS.search(message or "") and not any(_is_named(message, name) for name in existing)
	if not named and refers_to_it:
		named = [name for kind, name in proposed if kind == "subProcess"][:1]
	return {"added": added[:8], "request": request, "named": named}


def asks_to_make_call_activity(text: str) -> bool:
	"""True when the message asks to show or turn something into a call activity, which runs a separate process."""
	return bool(CALL_ACTIVITY_CONVERSION.search(text or ""))


def find_missing_target(xml: str, texts: list) -> dict | None:
	"""The name a message asks for a sub-process on when no step or sub-process has it, with the closest names that exist."""
	if not (xml or "").strip():
		return None
	register_namespaces()
	sub_tag = "{" + NS["bpmn"] + "}subProcess"
	root = ET.fromstring(xml)
	parents = {child: parent for parent in root.iter() for child in parent}
	depth = {}
	known = {}
	existing = [e.get("name") for e in root.iter() if e.tag == "{" + NS["bpmn"] + "}callActivity" and e.get("name")]
	for e in root.iter():
		if e.tag in (*STEP_TAGS, sub_tag) and e.get("id") and e.get("name"):
			ancestors, node = 0, e
			while node in parents:
				node = parents[node]
				ancestors += node.tag == sub_tag
			known.setdefault(e.get("name"), "sub-process" if e.tag == sub_tag else "step")
			depth[e.get("name")] = min(ancestors, depth.get(e.get("name"), ancestors))
	for text in texts:
		match = SUBPROCESS_REQUEST.search(text or "")
		if not match:
			continue
		asked = match.group(1).strip()
		if any(_squash(name) in _squash(asked) or _squash(asked) in _squash(name) for name in (*known, *existing)):
			return None
		similarity = {name: difflib.SequenceMatcher(None, asked.lower(), name.lower()).ratio() for name in known}
		asks_for_new = re.search(r"\bnew\s+sub[\s-]?process", text, re.I)
		close = sorted(
			(name for name in known if similarity[name] >= TYPO_SIMILARITY and not asks_for_new),
			key=lambda name: (depth[name], -similarity[name]),
		)
		return {"asked": asked, "text": text, "candidates": [{"name": name, "kind": known[name]} for name in close[:3]]}
	return None


def _squash(text: str) -> str:
	return re.sub(r"[^a-z0-9]", "", text.lower())


def resolve_step(xml: str, texts: list) -> dict | None:
	"""The step the newest message asking for a sub-process names; a call activity is never converted."""
	if not (xml or "").strip():
		return None
	register_namespaces()
	steps = [e for e in ET.fromstring(xml).iter() if e.tag in STEP_TAGS and e.get("id") and e.get("name")]
	for text in texts:
		targets = [match[1] for match in (*SUBPROCESS_REQUEST.finditer(text or ""), *BECOME_SUBPROCESS.finditer(text or ""))]
		squashed = _squash(" ".join(targets))
		named = [e for e in steps if _squash(e.get("name")) in squashed]
		if named:
			chosen = max(named, key=lambda e: len(e.get("name")))
			return {"id": chosen.get("id"), "name": chosen.get("name")}
	return None


def convert_step_to_subprocess(xml: str, step_id: str, child_xml: str) -> str:
	"""xml with the step step_id turned into an expanded sub-process holding the steps compiled in child_xml."""
	register_namespaces()
	root = ET.fromstring(xml)
	child_root = ET.fromstring(child_xml)
	bpmn, bpmndi = "{" + NS["bpmn"] + "}", "{" + NS["bpmndi"] + "}"
	parent = next(p for p in root.iter() if any(c.get("id") == step_id for c in p))
	step = next(c for c in parent if c.get("id") == step_id)
	sub = ET.Element(bpmn + "subProcess", {"id": step_id, "name": step.get("name", "")})
	sub.extend([c for c in step if c.tag in (bpmn + "documentation", bpmn + "incoming", bpmn + "outgoing")])
	parent[list(parent).index(step)] = sub
	_rename_taken_ids(child_root, {e.get("id") for e in root.iter() if e.get("id")}, step_id)
	sub.extend(child_root.find(bpmn + "process"))
	add_flow_references(sub)
	plane = next((p for p in root.iter(bpmndi + "BPMNPlane") if any(s.get("bpmnElement") == step_id for s in p)), None)
	if plane is not None:
		_draw_expanded(plane, step_id, child_root.find(bpmndi + "BPMNDiagram/" + bpmndi + "BPMNPlane"))
	converted = ET.tostring(root, encoding="unicode", xml_declaration=True)
	return re.sub(r"^<\?xml\s[^?]*\?>", '<?xml version="1.0" encoding="UTF-8"?>', converted)


def _draw_expanded(plane: ET.Element, step_id: str, child_plane: ET.Element) -> None:
	"""Grow the step's box to hold the child drawing, make room for it, and draw the steps inside."""
	dc, bpmndi = "{" + NS["dc"] + "}", "{" + NS["bpmndi"] + "}"
	shape = next(s for s in plane.findall(bpmndi + "BPMNShape") if s.get("bpmnElement") == step_id)
	bounds = shape.find(dc + "Bounds")
	x, y, w, h = (float(bounds.get(k)) for k in ("x", "y", "width", "height"))
	left, top, right, bottom = _extent(child_plane)
	new_w = max(200.0, right - left + 2 * EXPANDED_PAD)
	new_h = max(120.0, bottom - top + EXPANDED_PAD + EXPANDED_HEADER)
	_make_room(plane, shape, (x + w, y + h, y + h / 2), max(0.0, new_w - w), max(0.0, new_h - h))
	bounds.set("width", _num(max(w, new_w)))
	bounds.set("height", _num(max(h, new_h)))
	shape.set("isExpanded", "true")
	for drawn in child_plane:
		moved = copy.deepcopy(drawn)
		_shift(moved, x + EXPANDED_PAD - left, y + EXPANDED_HEADER - top, lambda px, py: (px, py))
		plane.append(moved)


def _extent(drawing: ET.Element) -> tuple:
	"""The left, top, right and bottom edges of everything drawn under drawing."""
	dc, di = "{" + NS["dc"] + "}", "{" + NS["di"] + "}"
	xs, ys = [], []
	for b in drawing.iter(dc + "Bounds"):
		xs += [float(b.get("x")), float(b.get("x")) + float(b.get("width"))]
		ys += [float(b.get("y")), float(b.get("y")) + float(b.get("height"))]
	for p in drawing.iter(di + "waypoint"):
		xs.append(float(p.get("x")))
		ys.append(float(p.get("y")))
	return min(xs), min(ys), max(xs), max(ys)


def _make_room(plane: ET.Element, step_shape: ET.Element, edges: tuple, dw: float, dh: float) -> None:
	"""Move what is right of the step by dw and what is below it by dh; widen and heighten the lanes and pool."""
	dc, bpmndi = "{" + NS["dc"] + "}", "{" + NS["bpmndi"] + "}"
	right, bottom, centre = edges
	horizontal = [s for s in plane.findall(bpmndi + "BPMNShape") if s.get("isHorizontal") == "true"]
	containing = []
	for lane in horizontal:
		b = lane.find(dc + "Bounds")
		if float(b.get("y")) <= centre <= float(b.get("y")) + float(b.get("height")):
			containing.append(float(b.get("y")) + float(b.get("height")))
	lane_bottom = min(containing) if containing else None
	for drawn in plane:
		if drawn is step_shape:
			continue
		if drawn in horizontal:
			b = drawn.find(dc + "Bounds")
			b.set("width", _num(float(b.get("width")) + dw))
			top, height = float(b.get("y")), float(b.get("height"))
			if top <= centre <= top + height:
				b.set("height", _num(height + dh))
			elif lane_bottom is not None and top >= lane_bottom:
				b.set("y", _num(top + dh))
			continue
		_shift(drawn, 0, 0, lambda px, py: (px + dw if px >= right else px, py + dh if py >= bottom else py))


def _shift(drawn: ET.Element, dx: float, dy: float, rule) -> None:
	"""Move a shape, with its label, or an edge point by point: each point moves as rule says, then by dx and dy."""
	dc, di = "{" + NS["dc"] + "}", "{" + NS["di"] + "}"
	own = drawn.find(dc + "Bounds")
	pinned = None if own is None else _offset(own, rule)
	for b in drawn.iter(dc + "Bounds"):
		ox, oy = pinned or _offset(b, rule)
		b.set("x", _num(float(b.get("x")) + ox + dx))
		b.set("y", _num(float(b.get("y")) + oy + dy))
	for p in drawn.iter(di + "waypoint"):
		ox, oy = _offset(p, rule)
		p.set("x", _num(float(p.get("x")) + ox + dx))
		p.set("y", _num(float(p.get("y")) + oy + dy))


def _offset(point: ET.Element, rule) -> tuple:
	x, y = float(point.get("x")), float(point.get("y"))
	new_x, new_y = rule(x, y)
	return new_x - x, new_y - y


def _num(value: float) -> str:
	return str(int(value)) if value == int(value) else str(round(value, 2))
