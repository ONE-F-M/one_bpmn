# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""What ProsAlly shows the user and the model about a pasted BPMN XML: parse failures, findings and the analysis block."""

from __future__ import annotations

# The analysis block handed to the model never exceeds this.
MAX_ANALYSIS_CHARS = 12000
MAX_LISTED_ELEMENTS = 150
MAX_LISTED_FLOWS = 150
MAX_LISTED_ISSUES = 40


def format_parse_error(error: dict) -> str:
	"""The parse failure as plain sentences naming line, column and tag."""
	where = f"line {error['line']}, column {error['column']} of the pasted XML"
	tag = f" at tag <{error['tag']}>" if error.get("tag") else ""
	lines = [f"The pasted BPMN XML could not be parsed: {error['message']} ({where}{tag})."]
	if error.get("source_line"):
		lines.append("Offending line: " + error["source_line"])
	return "\n".join(lines)


def parse_failure_reply(error: dict) -> str:
	"""The parse failure as the chat reply: where it failed and how to correct the pasted XML."""
	return (
		format_parse_error(error)
		+ "\nCorrect that tag (close or rename it, quote the attribute value, or declare the namespace) "
		"and paste the XML again."
	)


def analysis_reply(analysis: dict) -> str:
	"""The analysis of parsed XML as the chat reply: what was found, then each finding by element id."""
	issues = analysis["issues"]
	counts = ", ".join(f"{n} {t}" for t, n in analysis["counts"].items()) or "no BPMN flow elements"
	kind = "a partial fragment" if analysis["partial"] else "a BPMN 2.0 document"
	head = f"I parsed the pasted BPMN XML ({kind}): {counts}."
	if not issues:
		return head + "\nNo problems found."
	lines = [head, f"{len(issues)} finding(s):"]
	lines += [_format_issue(i) for i in issues[:MAX_LISTED_ISSUES]]
	if len(issues) > MAX_LISTED_ISSUES:
		lines.append(f"- ... and {len(issues) - MAX_LISTED_ISSUES} more findings not listed")
	lines.append("Ask me to apply any of these fixes and I will update the diagram.")
	return "\n".join(lines)[:MAX_ANALYSIS_CHARS]


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
