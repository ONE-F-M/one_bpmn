"""Message and signal links between process maps, read only, for the ProsAlly process tools."""

import re

import frappe
from frappe import _

from processa.ai_agent_registry.definitions.shared.tools_process_digest import (
	DOCTYPE,
	EVENT_DEFINITIONS,
	bpmn_tag,
	find_process_models,
	get_process_model_digest,
	local_name,
	parse_bpmn_xml,
)
from processa.processa_engine.agent_runtime.turn_state import get_turn, update_turn
from processa.processa_engine.compiler.called_processes import CALL_SPIFF_NS, called_model

MAX_RELATED_MODELS = 15
MAX_TURN_MAPS = 3
CACHE_TTL = 3600
CATCHING_TAGS = ("startEvent", "intermediateCatchEvent", "boundaryEvent", "receiveTask")
THROWING_TAGS = ("intermediateThrowEvent", "endEvent", "sendTask")
TASK_TAGS = ("receiveTask", "sendTask")
OTHER_MAPS = re.compile(
	r"\b(?:cross[- ]process|related (?:process|map)|other (?:process|maps?)|across (?:\w+ ){0,2}(?:process|maps?)|dependenc)",
	re.I,
)
LINK_WORDS = re.compile(r"\b(?:signals?|messages?|call activit|catch(?:es)?|throws?|senders?|hand-?offs?)", re.I)
DRAW_WORDS = re.compile(r"\b(?:add|draw|create|insert|generate|build|modify|redraw)\b", re.I)


def find_related_processes(process_model: str) -> dict:
	"""Readable active maps tied to this one by Process, call activity or a shared message or signal name."""
	error = _error_unless_readable(process_model)
	if error:
		return error

	related = related_models(process_model, links_of(process_model))
	return {
		"results": [
			{
				"process_model": name,
				"title": frappe.db.get_value(DOCTYPE, name, "title"),
				"reason": reason,
			}
			for name, reason in list(related.items())[:MAX_RELATED_MODELS]
		],
		"truncated": len(related) > MAX_RELATED_MODELS,
	}


def get_process_links(process_model: str) -> dict:
	"""Message and signal throws and catches of one map, with gaps against the related maps the user can read."""
	error = _error_unless_readable(process_model)
	if error:
		return error

	links = links_of(process_model)
	related = related_models(process_model, links)
	shown = list(related.items())[:MAX_RELATED_MODELS]
	others = {name: links_of(name) for name, _reason in shown}
	return {
		"process_model": process_model,
		"catches": links["catches"],
		"throws": links["throws"],
		"calls": links["calls"],
		"related": [{"process_model": name, "reason": reason} for name, reason in shown],
		"truncated": len(related) > len(shown),
		"gaps": find_link_gaps(process_model, links, others),
	}


def process_links_for_turn(conversation: str) -> dict:
	"""The get_process_links tool for the map open in this turn, with its findings kept in the turn store for the stage prompts."""
	found = get_process_links(_open_map(get_turn(conversation)))
	if "error" not in found:
		keep = {key: found[key] for key in ("process_model", "related", "gaps", "truncated")}
		update_turn(conversation, process_links=keep)
	return found


def read_process_map_for_turn(conversation: str, process_model: str) -> dict:
	"""The digest of one readable map, or the maps matching the words given; a digest is kept on the turn for the stage prompts."""
	if not frappe.db.exists(DOCTYPE, process_model or ""):
		return find_process_models(process_model or "")

	found = get_process_model_digest(process_model)
	kept = [row for row in get_turn(conversation).get("process_maps") or [] if row["process_model"] != process_model]
	kept.append({"process_model": process_model, "digest": found["digest"]})
	update_turn(conversation, process_maps=kept[-MAX_TURN_MAPS:])
	return found


def _open_map(turn: dict) -> str:
	"""The saved map open in the turn: its diagram name, else the active map of its process."""
	if turn.get("diagram_name"):
		return turn["diagram_name"]
	process = turn.get("process_name")
	return (process and frappe.db.get_value(DOCTYPE, {"process_name": process, "is_active": 1})) or ""


def asks_for_links_review(text: str) -> bool:
	"""True when the message asks about links to other process maps and does not ask to draw or change steps."""
	text = text or ""
	return bool(OTHER_MAPS.search(text) and LINK_WORDS.search(text) and not DRAW_WORDS.search(text))


def links_review_output(conversation: str) -> dict:
	"""The reply to a review of the open map's links to related maps, built from get_process_links alone."""
	found = process_links_for_turn(conversation)
	if "error" in found:
		response = found["error"]
	else:
		response = "\n\n".join(_review_paragraphs(found))
	return {"intent": "CLARIFY", "action_intent": None, "response": response, "options": []}


def _review_paragraphs(found: dict) -> list[str]:
	if not (found["catches"] or found["throws"] or found["calls"]):
		return [_("This map has no message or signal events and no call activities, so it has no links to other maps.")]

	if found["related"]:
		related = "\n".join(f"- {row['process_model']} ({row['reason']})" for row in found["related"])
		paragraphs = [_("Related maps I can read:") + "\n\n" + related]
	else:
		paragraphs = [_("No map you can read is linked to this one.")]
	if found["truncated"]:
		paragraphs.append(_("There are more related maps than I read. These findings cover the first {0}.").format(len(found["related"])))

	if found["gaps"]:
		gaps = "\n".join(f"- {gap['label'] or gap['element']}: {gap['message']}" for gap in found["gaps"])
		paragraphs.append(_("What to change:") + "\n\n" + gaps)
	else:
		paragraphs.append(_("Every message, signal and call activity in this map matches a map you can read."))
	paragraphs.append(_("I read the saved map and the related maps and changed none of them. Make any change in the map it names."))
	return paragraphs


def _error_unless_readable(process_model: str) -> dict | None:
	if not process_model:
		return {"error": _("I cannot tell which saved map is open. Save the map, then ask again.")}
	if not frappe.db.exists(DOCTYPE, process_model):
		return {"error": _("No process model named {0}.").format(process_model)}
	frappe.get_doc(DOCTYPE, process_model).check_permission("read")
	return None


def links_of(model_name: str) -> dict:
	"""extract_links of a stored map, cached until the map is modified."""
	modified = frappe.db.get_value(DOCTYPE, model_name, "modified")
	key = f"process_links:{model_name}:{modified}"
	links = frappe.cache.get_value(key, expires=True)
	if links is None:
		links = extract_links(frappe.db.get_value(DOCTYPE, model_name, "bpmn_xml"))
		frappe.cache.set_value(key, links, expires_in_sec=CACHE_TTL)
	return links


def extract_links(bpmn_xml: str | None) -> dict:
	"""Message and signal catches and throws, and call activities, of one diagram."""
	links = {"catches": [], "throws": [], "calls": []}
	root = parse_bpmn_xml(bpmn_xml)
	if root is None:
		return links

	names = {
		el.get("id"): (el.get("name") or "").strip()
		for kind in ("message", "signal")
		for el in root.iter(bpmn_tag(kind))
	}
	parents = {child: parent for parent in root.iter() for child in parent}
	for el in root.iter():
		tag = local_name(el.tag)
		if tag in CATCHING_TAGS:
			links["catches"].extend(_link_events(el, tag, names, parents))
		elif tag in THROWING_TAGS:
			links["throws"].extend(_link_events(el, tag, names, parents))
		elif tag == "callActivity":
			links["calls"].append(_call(el, parents))
	return links


def _link_events(el, tag: str, names: dict, parents: dict) -> list[dict]:
	if tag in TASK_TAGS:
		refs = [("message", el.get("messageRef"))]
	else:
		refs = []
		for child in el:
			kind, ref_attr = EVENT_DEFINITIONS.get(local_name(child.tag), (None, None))
			if kind:
				refs.append((kind, child.get(ref_attr)))
	return [
		{
			"kind": kind,
			"name": names[ref],
			"element": el.get("id"),
			"label": el.get("name") or el.get("id"),
			"step": tag,
			"multi_instance": _multi_instance(el, parents),
		}
		for kind, ref in refs
		if names.get(ref)
	]


def _call(el, parents: dict) -> dict:
	return {
		"element": el.get("id"),
		"label": el.get("name") or el.get("id"),
		"process": (el.get(f"{{{CALL_SPIFF_NS}}}calledProcess") or "").strip(),
		"called": (el.get("calledElement") or "").strip(),
		"multi_instance": _multi_instance(el, parents),
	}


def _multi_instance(el, parents: dict) -> bool:
	while el is not None:
		if el.find(bpmn_tag("multiInstanceLoopCharacteristics")) is not None:
			return True
		el = parents.get(el)
	return False


def related_models(model_name: str, links: dict) -> dict:
	"""Name of each readable active map tied to this one, with the reason, in relevance order."""
	related = {}
	for found in (_same_process(model_name), _called_maps(model_name, links), _name_sharing(model_name, links)):
		for name, reason in found:
			related.setdefault(name, reason)
	return related


def _same_process(model_name: str) -> list[tuple]:
	process = frappe.db.get_value(DOCTYPE, model_name, "process_name")
	if not process:
		return []
	names = frappe.get_list(
		DOCTYPE,
		filters={"process_name": process, "is_active": 1, "name": ["!=", model_name]},
		pluck="name",
		limit_page_length=MAX_RELATED_MODELS + 1,
	)
	return [(name, _("same Process")) for name in names]


def _called_maps(model_name: str, links: dict) -> list[tuple]:
	found = []
	for call in links["calls"]:
		target = called_model(call["process"], call["called"])
		if target and target.name != model_name and frappe.has_permission(DOCTYPE, "read", doc=target.name):
			found.append((target.name, _("called by {0}").format(call["label"])))
	return found


def _name_sharing(model_name: str, links: dict) -> list[tuple]:
	found = []
	for name in sorted({link["name"] for link in links["catches"] + links["throws"]}):
		rows = frappe.get_list(
			DOCTYPE,
			filters={"is_active": 1, "name": ["!=", model_name], "bpmn_xml": ["like", f"%{name}%"]},
			pluck="name",
			limit_page_length=MAX_RELATED_MODELS + 1,
		)
		found.extend((row, _("uses '{0}'").format(name)) for row in rows)
	return found


def find_link_gaps(model_name: str, links: dict, others: dict) -> list[dict]:
	"""Gaps for the elements of this map, judged against itself and the related maps given."""
	maps = {model_name: links, **others}
	gaps = []
	for catch in links["catches"]:
		if catch["step"] != "startEvent":
			gaps.append(_link_gap(model_name, catch, maps, "throws"))
	for throw in links["throws"]:
		gaps.append(_link_gap(model_name, throw, maps, "catches"))
	gaps.extend(_call_gaps(links["calls"]))
	return [gap for gap in gaps if gap]


def _link_gap(model_name: str, link: dict, maps: dict, other_side: str) -> dict | None:
	holders = _holders(link, maps, other_side)
	if model_name in holders or (holders and link["kind"] == "message"):
		return None

	name = link["name"]
	if holders:
		message = _(
			"Signal '{0}' is only matched in {1}. A signal reaches only catchers in the same process "
			"instance, so it never crosses to another map. Use a message or a call activity instead."
		).format(name, ", ".join(holders))
		return _gap("signal_other_process", link, message)

	near = _near(link, maps, other_side)
	if near:
		message = _("The {0} '{1}' has no exact match. Similar names: {2}. Make the names identical.").format(
			link["kind"], name, ", ".join(near)
		)
		return _gap("name_mismatch", link, message)

	if other_side == "throws":
		message = _(
			"No throw of the {0} '{1}' in the process maps you can read. If something outside the maps "
			"sends it, no change is needed; otherwise add a throw in the map that should send it."
		).format(link["kind"], name)
		return _gap("no_throw", link, message)
	message = _(
		"No catch of the {0} '{1}' in the process maps you can read. Add a catch in the map that "
		"should wait for it."
	).format(link["kind"], name)
	return _gap("no_catch", link, message)


def _holders(link: dict, maps: dict, other_side: str) -> list[str]:
	return [
		model
		for model, links in maps.items()
		if any(entry["kind"] == link["kind"] and entry["name"] == link["name"] for entry in links[other_side])
	]


def _near(link: dict, maps: dict, other_side: str) -> list[str]:
	def squash(text):
		return " ".join(text.lower().split())

	return [
		f"{model}: '{entry['name']}'"
		for model, links in maps.items()
		for entry in links[other_side]
		if entry["kind"] == link["kind"]
		and entry["name"] != link["name"]
		and squash(entry["name"]) == squash(link["name"])
	]


def _call_gaps(calls: list[dict]) -> list[dict]:
	gaps = []
	for call in calls:
		target = called_model(call["process"], call["called"])
		if not target or not target.bpmn_xml:
			message = _("The call activity '{0}' calls a process that has no active map.").format(call["label"])
			gaps.append(_gap("call_target_missing", call, message))
		elif not frappe.has_permission(DOCTYPE, "read", doc=target.name):
			message = _("The call activity '{0}' calls a map you cannot read.").format(call["label"])
			gaps.append(_gap("call_target_not_visible", call, message))
	return gaps


def _gap(kind: str, link: dict, message: str) -> dict:
	return {"kind": kind, "element": link["element"], "label": link["label"], "message": message}
