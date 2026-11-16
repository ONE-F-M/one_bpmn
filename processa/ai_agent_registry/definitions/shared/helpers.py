"""Functions more than one agent uses: model reply parsing, chat history and the tool error envelope."""

import functools
import inspect
import json
import re

import frappe

HISTORY_TURNS = 10


def format_history(chat_history: list, agent_label: str = "ProsAlly") -> str:
	"""The last HISTORY_TURNS messages as "User: ..." lines and lines labelled with the agent's name."""
	lines = []
	for entry in (chat_history or [])[-HISTORY_TURNS:]:
		role = entry.get("role") or entry.get("type", "user")
		content = (entry.get("content") or "").strip()
		if content:
			lines.append(("User" if role == "user" else agent_label) + ": " + content)
	return "\n".join(lines)


def extract_json(raw: str) -> dict | None:
	"""The first JSON object found in a model reply: whole, fenced, or embedded in prose.

	Literal newlines inside string values are accepted, since models often write them.
	"""
	if not raw:
		return None
	stripped = raw.strip()
	candidates = [stripped]
	fenced = re.search(r"```(?:json)?\s*\n?([\s\S]*?)```", raw)
	if fenced:
		candidates.append(fenced.group(1).strip())
	greedy = re.search(r"\{[\s\S]*\}", raw)
	if greedy:
		candidates.append(greedy.group(0))
	if stripped.startswith("```"):
		unfenced = stripped.split("\n", 1)[-1]
		if unfenced.rstrip().endswith("```"):
			unfenced = unfenced.rstrip()[: unfenced.rstrip().rfind("```")]
		candidates.append(unfenced.strip())
	start = raw.find("{")
	if start != -1:
		depth = 0
		for i in range(start, len(raw)):
			if raw[i] == "{":
				depth += 1
			elif raw[i] == "}":
				depth -= 1
				if depth == 0:
					candidates.append(raw[start : i + 1])
					break
	for candidate in candidates:
		try:
			parsed = json.loads(candidate, strict=False)
		except json.JSONDecodeError:
			continue
		if isinstance(parsed, dict):
			return parsed
	return None


def tool_envelope(title: str, fallback):
	"""Log an error the tool raises under title and return fallback(**arguments) instead.

	A Server Script cannot catch a Python exception, so a tool it calls answers with an error value.
	"""

	def decorate(fn):
		signature = inspect.signature(fn)

		@functools.wraps(fn)
		def call(*args, **kwargs):
			try:
				return fn(*args, **kwargs)
			except Exception:
				frappe.log_error(title=title, message=frappe.get_traceback())
				bound = signature.bind(*args, **kwargs)
				bound.apply_defaults()
				return fallback(**bound.arguments)

		return call

	return decorate
