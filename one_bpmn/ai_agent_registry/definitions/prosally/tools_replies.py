"""ProsAlly's replies that say what a redraw changed, or why nothing changed."""

import re
from collections import Counter
from xml.etree import ElementTree as ET

from frappe import _

from one_bpmn.ai_agent_memory.text_clean import strip_html
from one_bpmn.ai_agent_registry.definitions.prosally.helpers import (
	NS,
	REQUEST_STOPWORDS,
	STEP_TAGS,
	confirmation_reply,
	quoted,
)
from one_bpmn.ai_agent_registry.definitions.prosally.tools_pipeline import element_names

# Plain words for the element types a designer sees in a change list.
_ELEMENT_WORDS = {
	"startEvent": "the start",
	"endEvent": "the end",
	"exclusiveGateway": "the decision",
	"inclusiveGateway": "the decision",
	"eventBasedGateway": "the decision",
	"parallelGateway": "the parallel split",
	"sequenceFlow": "the path",
	"subProcess": "the sub-process",
	"intermediateCatchEvent": "the event",
	"intermediateThrowEvent": "the event",
	"boundaryEvent": "the event",
	"userTask": "the step",
	"serviceTask": "the step",
	"scriptTask": "the step",
	"manualTask": "the step",
	"sendTask": "the step",
	"receiveTask": "the step",
	"businessRuleTask": "the step",
	"callActivity": "the step",
	"task": "the step",
}


def describe_changes(previous_xml: str, xml: str) -> str:
	"""What a modify added, removed and renamed on the diagram, as plain lines; says so when nothing changed."""
	before = element_names(previous_xml)
	after = element_names(xml)
	lines = []
	for elem_id, (kind, name) in after.items():
		if kind == "sequenceFlow":
			continue
		if elem_id not in before:
			lines.append(_("Added {0}.").format(_element_label(kind, name)))
			continue
		old_name = before[elem_id][1]
		if name and old_name and name != old_name:
			lines.append(_("Renamed {0} to {1}.").format(_element_label(kind, old_name), quoted(name)))
	for elem_id, (kind, name) in before.items():
		if kind != "sequenceFlow" and elem_id not in after:
			lines.append(_("Removed {0}.").format(_element_label(kind, name)))
	# Paths are compared by label, since a modify may give an unchanged path a new id.
	old_paths = Counter(name for kind, name in before.values() if kind == "sequenceFlow" and name)
	new_paths = Counter(name for kind, name in after.values() if kind == "sequenceFlow" and name)
	for name in (new_paths - old_paths).elements():
		lines.append(_("Added {0}.").format(_element_label("sequenceFlow", name)))
	for name in (old_paths - new_paths).elements():
		lines.append(_("Removed {0}.").format(_element_label("sequenceFlow", name)))
	lines += _moved_arrows(previous_xml, xml)
	lines += _changed_kinds(before, after)
	lines += _lane_lines(previous_xml, xml)
	lines += _config_lines(previous_xml, xml)
	if not lines:
		return "\n\n" + _("I could not find any change on the diagram. Check that your request was applied.")
	return "\n\n" + _("What changed:") + "\n" + "\n".join("- " + line for line in lines)


def _changed_kinds(before: dict, after: dict) -> list[str]:
	"""Steps present before and after whose element type changed, as plain lines."""
	return [
		_("Changed {0} to {1}.").format(_element_label(kind, name), _ELEMENT_WORDS.get(after[elem_id][0], "another kind of element"))
		for elem_id, (kind, name) in before.items()
		if elem_id in after and kind != "sequenceFlow" and after[elem_id][0] != kind
	]


def _lanes(xml: str) -> dict:
	"""{lane name: set of step ids} in diagram order; empty when the diagram has no lanes."""
	lanes = {}
	for attrs, body in re.findall(r"<bpmn:lane\s([^>]*)>(.*?)</bpmn:lane>", xml or "", re.S):
		values = dict(re.findall(r'(\w+)="([^"]*)"', attrs))
		lanes[values.get("name") or values.get("id")] = set(re.findall(r"<bpmn:flowNodeRef>([^<]+)</bpmn:flowNodeRef>", body))
	return lanes


def _lane_lines(previous_xml: str, xml: str) -> list[str]:
	"""Lanes added, removed, reordered and steps moved between lanes, as plain lines."""
	old, new = _lanes(previous_xml), _lanes(xml)
	lines = [_("Added the lane {0}.").format(quoted(name)) for name in new if name not in old]
	lines += [_("Removed the lane {0}.").format(quoted(name)) for name in old if name not in new]
	kept_old = [name for name in old if name in new]
	kept_new = [name for name in new if name in old]
	if kept_old != kept_new:
		lines.append(_("Reordered the lanes: {0}.").format(", ".join(new)))
	names = {elem_id: name for elem_id, (_kind, name) in element_names(xml).items()}
	for lane in kept_new:
		for elem_id in sorted(new[lane] - old[lane]):
			home = next((other for other in old if elem_id in old[other]), None)
			if home and elem_id in names:
				lines.append(_("Moved {0} from the lane {1} to {2}.").format(quoted(names[elem_id]), quoted(home), quoted(lane)))
	return lines


def _settings(xml: str) -> dict:
	"""{element id: its prefixed attributes such as spiffworkflow:workflowState} for elements that have any."""
	found = {}
	for attrs in re.findall(r"<bpmn:\w+\s([^>]*?)/?>", xml or ""):
		values = dict(re.findall(r'([\w.-]+:[\w.-]+)="([^"]*)"', attrs))
		values = {key: val for key, val in values.items() if not key.startswith("xmlns")}
		elem_id = re.search(r'\bid="([^"]+)"', attrs)
		if values and elem_id:
			found[elem_id.group(1)] = values
	return found


def _config_lines(previous_xml: str, xml: str) -> list[str]:
	"""Steps present before and after whose settings changed, as plain lines."""
	before, names = _settings(previous_xml), element_names(xml)
	return [
		_("Changed the settings of {0}.").format(quoted(names[elem_id][1] or elem_id))
		for elem_id, values in _settings(xml).items()
		if elem_id in before and before[elem_id] != values and elem_id in names
	]


def _moved_arrows(previous_xml: str, xml: str) -> list[str]:
	"""Arrows between steps that exist before and after whose source or target changed, as plain lines."""
	old_names = {i: name for i, (kind, name) in element_names(previous_xml).items() if kind != "sequenceFlow"}
	new_names = {i: name for i, (kind, name) in element_names(xml).items() if kind != "sequenceFlow"}

	def arrows(text):
		found = Counter()
		for attrs in re.findall(r"<bpmn:sequenceFlow\s([^>]*?)/?>", text or ""):
			values = {key: val for key, val in re.findall(r'(\w+)="([^"]*)"', attrs)}
			found[(values.get("sourceRef"), values.get("targetRef"), values.get("name", ""))] += 1
		return found

	gone = list((arrows(previous_xml) - arrows(xml)).elements())
	lines = []
	for source, target, label in (arrows(xml) - arrows(previous_xml)).elements():
		if source not in old_names or target not in old_names:
			continue
		match = next(
			(
				old
				for old in gone
				if old[2] == label and (old[0] == source) != (old[1] == target) and old[0] in new_names and old[1] in new_names
			),
			None,
		)
		if match:
			gone.remove(match)
			lines.append(
				_("Moved the arrow from {0} to {1}.").format(quoted(new_names[source] or source), quoted(new_names[target] or target))
			)
	return lines


def similar_steps(xml: str, texts: list, skip: str = "") -> list[str]:
	"""Up to three steps in xml sharing two or more significant words with the newest request in texts, best first."""
	request = next((strip_html(text) for text in texts if text and not confirmation_reply(text)), "")
	skipped = {word[:5] for word in re.findall(r"[a-z]{4,}", skip.lower())}
	wanted = {
		word[:5] for word in re.findall(r"[a-z]{4,}", request.split(":", 1)[-1].lower()) if word not in REQUEST_STOPWORDS
	} - skipped
	scored = []
	for elem in ET.fromstring(xml).iter():
		if elem.tag in STEP_TAGS and elem.get("name"):
			shared = len(wanted & {word[:5] for word in re.findall(r"[a-z]{4,}", elem.get("name").lower())})
			if wanted and shared >= min(2, len(wanted)):
				scored.append((shared, elem.get("name")))
	scored.sort(key=lambda entry: -entry[0])
	return [name for _, name in scored[:3]]


def no_change_reply(where: str, similar: list[str]) -> str:
	"""The answer when a modify changed nothing: what already covers the request and what to say next."""
	if not similar:
		return _("I did not change {0}. Tell me which step to add or change, and where it goes.").format(where)
	label = _("the step") if len(similar) == 1 else _("the steps")
	return _("I did not change {0}. It already has {1} {2}. Tell me what else to add or change, and where it goes.").format(
		where, label, ", ".join(quoted(name) for name in similar)
	)


def describe_links(previous_xml: str, xml: str) -> str:
	"""Unlabeled paths added or removed between steps that exist before and after, as plain lines; "" when none."""
	if not (previous_xml or "").strip() or not (xml or "").strip():
		return ""
	old_root, new_root = ET.fromstring(previous_xml), ET.fromstring(xml)
	old_names, new_names = _names_by_id(old_root), _names_by_id(new_root)
	old_links, new_links = _unlabeled_links(old_root), _unlabeled_links(new_root)
	lines = [
		_("Connected {0} to {1}.").format(quoted(new_names[source]), quoted(new_names[target]))
		for source, target in new_links - old_links
		if source in old_names and target in old_names
	]
	lines += [
		_("Disconnected {0} from {1}.").format(quoted(old_names[source]), quoted(old_names[target]))
		for source, target in old_links - new_links
		if source in new_names and target in new_names
	]
	if not lines:
		return ""
	return "\n\n" + _("What changed:") + "\n" + "\n".join("- " + line for line in lines)


def _names_by_id(root: ET.Element) -> dict:
	return {e.get("id"): e.get("name") or e.get("id") for e in root.iter() if e.get("id")}


def _unlabeled_links(root: ET.Element) -> Counter:
	flow = "{" + NS["bpmn"] + "}sequenceFlow"
	return Counter((f.get("sourceRef"), f.get("targetRef")) for f in root.iter(flow) if not f.get("name"))


def describe_flow_references(previous_xml: str, xml: str) -> str:
	"""Steps present before and after whose incoming or outgoing flow references changed, as one plain line; "" when none."""
	if not (previous_xml or "").strip() or not (xml or "").strip():
		return ""
	before, after = _flow_references(ET.fromstring(previous_xml)), _flow_references(ET.fromstring(xml))
	changed = sum(1 for step_id, references in after.items() if step_id in before and before[step_id] != references)
	if not changed:
		return ""
	line = _("Rebuilt the flow references on {0} steps, which the editor's linter reads.").format(changed)
	return "\n\n" + _("What changed:") + "\n- " + line


def _flow_references(root: ET.Element) -> dict:
	"""For each step, the flow ids listed as its incoming and as its outgoing references."""
	bpmn = "{" + NS["bpmn"] + "}"
	return {
		e.get("id"): (
			frozenset(c.text for c in e.findall(bpmn + "incoming")),
			frozenset(c.text for c in e.findall(bpmn + "outgoing")),
		)
		for e in root.iter()
		if e.get("id") and e.tag != bpmn + "sequenceFlow"
	}


def _element_label(kind: str, name: str) -> str:
	return _ELEMENT_WORDS.get(kind, "the element") + (" " + quoted(name) if name else "")
