"""ProsAlly turns diagram lint findings into a fix request and a reply."""

import re
from collections import Counter
from xml.etree import ElementTree as ET

from frappe import _

from one_bpmn.agents.memory.text_clean import strip_html
from one_bpmn.ai_agent_registry.definitions.prosally.helpers import (
	NS,
	confirmation_reply,
	quoted,
	register_namespaces,
)
from one_bpmn.ai_agent_registry.definitions.prosally.tools_subprocess import resolve_scope

LINT_FIX_REQUEST = re.compile(
	r"\b(?:fix|resolve|clear|clean\s*up|correct|repair|solve|sort\s*out)\b[^.:]{0,60}\b(?:lint(?:ing)?|linter|warnings?|errors?|issues?|problems?)\b"
	r"(?!\s+(?:handler|step|task|event|gateway|flow|path|boundary|code))"
	r"|\blint(?:ing)?\b[^.:]{0,40}\b(?:fix|resolve|clear|clean\s*up|correct|repair)",
	re.I,
)
LINT_NOT_FIXABLE = frozenset(
	(
		"no-overlapping-elements",
		"no-crossing-edges",
		"script-task-missing-script",
		"call-activity-missing-process",
		"no-prohibited-shapes",
		"no-bpmndi",
		"ad-hoc-sub-process",
	)
)
LINT_ABOUT_CONTENTS = frozenset(
	("start-event-required", "end-event-required", "sub-process-blank-start-event", "single-blank-start-event")
)
MAX_LINT_FINDINGS = 40


def lint_fix_requested(texts: list) -> bool:
	"""True when the newest message that is not a yes or a no asks to fix lint findings."""
	request = next((strip_html(text) for text in texts if text and not confirmation_reply(text)), "")
	return bool(LINT_FIX_REQUEST.search(request))


def lint_findings(xml: str, issues: list, scope_id: str = "") -> dict | None:
	"""The findings to fix in the process or sub-process to edit, those that need a person, and the rest by place."""
	if not (xml or "").strip() or not issues:
		return None
	register_namespaces()
	root = ET.fromstring(xml)
	sub_tag = "{" + NS["bpmn"] + "}subProcess"
	parents = {child: node for node in root.iter() for child in node}
	elements = {e.get("id"): e for e in root.iter() if e.get("id")}
	subs = {e.get("id"): e for e in root.iter(sub_tag)}
	found = []
	for issue in issues[:MAX_LINT_FINDINGS]:
		element = elements.get(issue.get("id"))
		rule = str(issue.get("rule") or "").rsplit("/", 1)[-1]
		inside = element is not None and element.tag == sub_tag and rule in LINT_ABOUT_CONTENTS
		node = element if inside else parents.get(element)
		while node is not None and node.tag != sub_tag:
			node = parents.get(node)
		found.append(
			{
				"id": str(issue.get("id") or ""),
				"name": (element.get("name") if element is not None else "") or str(issue.get("id") or ""),
				"rule": rule,
				"message": str(issue.get("message") or ""),
				"category": str(issue.get("category") or "warn"),
				"owner": node.get("id") if node is not None else "",
			}
		)
	fixable = [f for f in found if f["rule"] not in LINT_NOT_FIXABLE]
	by_owner = Counter(f["owner"] for f in fixable)
	chosen = scope_id if scope_id in subs else ""
	if not chosen and by_owner and "" not in by_owner:
		chosen = by_owner.most_common(1)[0][0]
	return {
		"scope": resolve_scope(xml, [], chosen) if chosen else None,
		"fix": [f for f in fixable if f["owner"] == chosen],
		"left": [f for f in found if f["rule"] in LINT_NOT_FIXABLE],
		"elsewhere": [
			(subs[owner].get("name") or owner if owner else "", count) for owner, count in by_owner.items() if owner != chosen
		],
	}


def lint_prompt(findings: dict) -> str:
	"""The findings to fix, one per line, under where they sit."""
	where = findings["scope"]["name"] if findings["scope"] else "the main process"
	lines = [
		"- [{0}] {1} (id {2}): {3} ({4})".format(f["category"], quoted(f["name"]), f["id"], f["message"], f["rule"])
		for f in findings["fix"]
	]
	return "In {0}:\n{1}".format(where, "\n".join(lines))


def lint_leftovers(findings: dict) -> str:
	"""What a lint fix did not touch: findings in other places and findings that need a person."""
	parts = []
	for name, count in findings["elsewhere"]:
		parts.append(_("{0} in {1}").format(count, quoted(name) if name else _("the main process")))
	if findings["left"]:
		parts.append(_("{0} that need a person to fix").format(len(findings["left"])))
	if not parts:
		return ""
	return "\n\n" + _("Not fixed: {0}. Ask me again from there, or fix them in the editor.").format(", ".join(parts))


def lint_unfixed_reply(where: str, findings: dict) -> str:
	"""The answer when a lint fix changed nothing: how many findings stayed and which rules they break."""
	count = len(findings["fix"])
	rules = ", ".join(sorted({f["rule"] for f in findings["fix"]}))
	return _(
		"I did not change {0}. I could not fix the {1} lint findings it has ({2}) by editing the steps and paths. "
		"Fix them in the editor, or tell me which steps to connect or add."
	).format(where, count, rules)


def no_lint_fix_reply(findings: dict | None) -> str:
	"""The answer to a request to fix lint findings when there is nothing ProsAlly can change."""
	if not findings:
		return _("The editor shows no lint findings to fix. If you expect some, open the lint panel and ask again.")
	lines = "\n".join("- {0}: {1}".format(quoted(f["name"]), f["message"]) for f in findings["left"])
	return _("None of these findings can be fixed by changing the steps and paths, so they need a person in the editor:") + (
		"\n" + lines
	)
