# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Static context assembly for AI agents (WI-001639).

An agent's context has two layers, and the whole point of this module is that
they never mix:

  * the STATIC layer — Instructions, Examples, Guard Rails. Assembled once per
    run by ``build_static_context`` and sent as the system prompt. It is
    identical on every iteration of the execution loop, on every turn of a
    conversation, and across a human-in-the-loop suspend/resume.
  * the DYNAMIC layer — the message history: the user's text, tool results and,
    since this story, retrieved long-term memory. Everything that varies is
    appended here.

Before WI-001639 the retrieved memory block was appended to the system prompt
at dispatch. Memory is searched with the current user prompt as the query, so
the system prompt differed from turn to turn: the agent's foundational rules
arrived in a slightly different context every time (drift), and the provider's
system-prompt cache breakpoint was invalidated on every call. Memory now goes
into the dynamic layer where it belongs — see ``build_dynamic_preamble``.

``build_static_context`` is a pure function of its input: the same
configuration always produces the byte-identical string. That property is what
makes the layer verifiable (see tests/test_context_assembler.py) and cacheable,
so treat it as part of the contract rather than an implementation detail.
"""

from __future__ import annotations

# Section headers are part of the rendered prompt and appear in AI Agent Run
# transcripts and eval fixtures. Changing them changes every agent's system
# prompt — do not edit them casually.
EXAMPLES_HEADER = "## Examples"
GUARDRAILS_HEADER = "## Guard Rails"
SKILLS_HEADER = "## AI Skills"

# Prefix for the retrieved-memory block in the DYNAMIC layer. The old
# system-prompt header lives on as dispatchers.MEMORY_BLOCK_HEADER, which the
# run inspector and evals key on; this module reuses it rather than inventing a
# second format.
_SECTION_GAP = "\n\n"


def _enabled_rows(rows) -> list:
	"""Rows the model should see, in the order the author put them in.

	Child tables arrive ordered by ``idx`` from Frappe, but a plain list of
	dicts (tests, the create endpoint) has no idx — preserve the given order in
	that case rather than inventing one. A row missing ``enabled`` entirely is
	treated as enabled, so rows created before this field existed still render.
	"""
	out = []
	for row in rows or []:
		get = row.get if isinstance(row, dict) else lambda k, d=None: getattr(row, k, d)
		if get("enabled", 1) in (0, "0", False):
			continue
		out.append(get)
	return out


def _render_examples(rows) -> str:
	"""Few-shot examples as a stable, greppable block. An example with no
	expected output is still worth showing — it demonstrates the shape of a
	request — so only the input is mandatory."""
	blocks = []
	for i, get in enumerate(_enabled_rows(rows), start=1):
		text = str(get("input", "") or "").strip()
		if not text:
			continue
		lines = [f"### Example {i}", "Input:", text]
		output = str(get("expected_output", "") or "").strip()
		if output:
			lines += ["Expected output:", output]
		note = str(get("note", "") or "").strip()
		if note:
			lines.append(f"Note: {note}")
		blocks.append("\n".join(lines))
	if not blocks:
		return ""
	return EXAMPLES_HEADER + "\n\n" + _SECTION_GAP.join(blocks)



def _render_skills_index(skills) -> str:
	if not skills:
		return ""
	lines = [SKILLS_HEADER, "You have the following skills available. Use the load_skill tool to read a skill's full instructions when needed."]
	for skill in skills:
		name = skill.get("name", "")
		desc = skill.get("description", "")
		if name:
			lines.append(f"- **{name}**: {desc}")
	return "\n".join(lines)


def _render_guardrails(rows) -> str:
	"""Guard rails as a numbered list, grouped under their category.

	Numbering is continuous across categories so a rule can be cited ("guard
	rail 4") in a review or an eval assertion without ambiguity.
	"""
	by_category: dict[str, list[str]] = {}
	order: list[str] = []
	for get in _enabled_rows(rows):
		text = str(get("guardrail", "") or "").strip()
		if not text:
			continue
		category = str(get("category", "") or "").strip() or "Other"
		if category not in by_category:
			by_category[category] = []
			order.append(category)
		by_category[category].append(text)

	if not order:
		return ""

	lines = [GUARDRAILS_HEADER, "You must obey every rule below on every turn."]
	n = 0
	for category in order:
		lines.append("")
		lines.append(f"**{category}**")
		for text in by_category[category]:
			n += 1
			lines.append(f"{n}. {text}")
	return "\n".join(lines)


def build_static_context(
	system_prompt: str = "",
	examples=None,
	guardrails=None,
	skills=None,
) -> str:
	"""Assemble the immutable static context layer.

	Composition order is fixed and load-bearing: **Instructions -> Examples ->
	Guard Rails**. Instructions establish the role, examples show it applied,
	and guard rails come last so they are the model's final word before the
	conversation starts.

	Empty sections are omitted entirely rather than rendered as empty headers —
	an agent with no guard rails must produce exactly the prompt it produced
	before this story, so adding the fields changes nothing until they are
	filled in.

	Args:
	    system_prompt: the agent's Instructions (already Jinja-rendered).
	    examples: AI Agent Example rows, or dicts of the same shape.
	    guardrails: AI Agent Guard Rail rows, or dicts of the same shape.
	    skills: List of dicts with name and description.

	Returns:
	    The system prompt string to send. Deterministic: identical inputs
	    always yield an identical string.
	"""
	sections = [
		str(system_prompt or "").strip(),
		_render_skills_index(skills),
		_render_examples(examples),
		_render_guardrails(guardrails),
	]
	return _SECTION_GAP.join(s for s in sections if s)


def build_static_context_from_config(config: dict, system_prompt: str = None) -> str:
	"""``build_static_context`` for a resolved AI Agent Configuration dict.

	``config`` is what ``get_agent_config`` returns. ``system_prompt`` overrides
	the config's own Instructions — the dispatcher passes the Jinja-rendered
	shape prompt, which is the value that actually runs.
	"""
	config = config or {}
	return build_static_context(
		system_prompt=config.get("system_prompt", "") if system_prompt is None else system_prompt,
		examples=config.get("examples"),
		guardrails=config.get("guardrails"),
	)


def load_agent_behaviour(config_name: str) -> dict:
	"""Examples + guard rails for a linked AI Agent Configuration.

	Shared by both shapes that run an agent — the AI Agent Task and the AI Task
	Selector — so the two can never drift apart on what the static layer holds.

	Goes through ``get_agent_config``, so the rows come from the same cached
	read as the rest of the agent's live values and are invalidated by the same
	save hook. That function is keyed by agent_id while a shape stores the
	record NAME, so resolve it first. Returns {} for a missing or disabled
	configuration, leaving the task with its own prompt.
	"""
	import frappe

	from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import (
		get_agent_config,
	)

	agent_id = frappe.db.get_value("AI Agent Configuration", config_name, "agent_id")
	if not agent_id:
		return {}
	return get_agent_config(agent_id) or {}


def build_dynamic_preamble(memory_block: str = "", user_prompt: str = "", active_skills: list[str] = None) -> str:
	"""Compose the DYNAMIC layer's opening message.

	Retrieved long-term memory is dynamic — it is searched with this turn's
	user prompt and differs every turn — so it belongs here, ahead of the user's
	text, and never in the system prompt.

	The memory block is placed FIRST so the provider-side conversation cache
	breakpoint (which the Anthropic adapter puts on the context prefix that
	precedes a "User message:"-style marker) still has a stable prefix to
	attach to.

	Returns the user prompt unchanged when there is no memory to inject, so
	agents without long-term memory send exactly what they sent before.
	"""
	memory_block = str(memory_block or "").strip()
	user_prompt = str(user_prompt or "")
	skills_block = ""
	if active_skills:
		skills_block = "\n\n".join(str(s).strip() for s in active_skills if s)

	parts = []
	if skills_block:
		parts.append(skills_block)
	if memory_block:
		parts.append(memory_block)
	
	combined_prefix = _SECTION_GAP.join(parts)
	
	if not combined_prefix:
		return user_prompt
	if not user_prompt.strip():
		return combined_prefix
	return f"{combined_prefix}{_SECTION_GAP}User message: {user_prompt}"



# Minimum length for a paragraph to count as "an instruction block" worth
# de-duplicating. Short lines repeat legitimately — a heading, a label, the
# user's own words quoted back — and stripping those would change meaning.
_DUPLICATE_MIN_CHARS = 120


def _normalise(text: str) -> str:
	"""Whitespace-insensitive form, so re-indentation does not hide a duplicate."""
	return " ".join((text or "").split())


def drop_duplicated_instructions(system_prompt: str, user_prompt: str) -> str:
	"""Return *user_prompt* without any block the system prompt already carries.

	Stable instructions belong in the system role, which every provider caches;
	repeating them per turn pays for the same tokens again at full price and
	makes the two roles disagree the moment one is edited. Measured on LuCrusher:
	a 950-character "how to work this turn" block rode in EVERY user message,
	which is most of that agent's ~3.6k-character per-turn user step.

	Paragraph-level and verbatim-only (whitespace-insensitive): a block goes only
	when the same text is already in the system prompt, so nothing the model
	would otherwise never see can be lost. The map keeps its template — the
	duplicate is removed at assembly, so no diagram has to be re-exported for an
	agent to stop paying twice.
	"""
	if not system_prompt or not user_prompt:
		return user_prompt

	haystack = _normalise(system_prompt)
	kept = []
	for block in (user_prompt or "").split("\n\n"):
		candidate = _normalise(block)
		if len(candidate) >= _DUPLICATE_MIN_CHARS and candidate in haystack:
			continue
		kept.append(block)

	# Rejoin, then collapse the runs of blank lines the removals leave behind.
	out = "\n\n".join(kept)
	while "\n\n\n" in out:
		out = out.replace("\n\n\n", "\n\n")
	return out.strip("\n")
