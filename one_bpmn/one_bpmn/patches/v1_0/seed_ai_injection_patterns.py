"""
WI-001967: ship the prompt-injection rule pack, seeded from public taxonomies.

The pack is data (AI Injection Pattern), so a site can add, tighten or retire a
rule without a code change. This patch puts the shipped baseline in place —
entries drawn from OWASP's LLM Top 10, MITRE ATLAS and the Garak probe families,
each carrying its source so a reviewer can see where the rule came from.

Deliberately conservative. Every rule here targets a phrase whose only plausible
purpose is to redirect the model, because a pack that fires on ordinary business
language gets switched off inside a week and then protects nothing. Coverage is
meant to grow from confirmed ONE-FM events (promote_to_pattern), not from
guessing broadly up front.

Idempotent, and it never overwrites: a rule an admin has since edited or
disabled is left exactly as they left it. Re-running only adds what is missing.
"""

import frappe

# (name, type, severity, pattern, match_mode, boundary, action, taxonomy, reference)
PATTERNS = [
	# ---- Instruction override — OWASP LLM01 -------------------------------
	(
		"ignore-previous-instructions",
		"Instruction Override",
		"High",
		# Determiners are a repeated optional group, not a fixed pair: allowing
		# only "all" and "any" meant "ignore YOUR previous instructions" — one
		# word different — walked straight through the flagship rule of the pack.
		r"\b(?:ignore|disregard|forget|override)\s+(?:all\s+|any\s+|the\s+|your\s+|my\s+)*(?:previous|prior|earlier|above|preceding)\s+(?:instruction|instructions|prompt|prompts|direction|directions|rule|rules)\b",
		"regex",
		"any",
		"Flag",
		"OWASP LLM Top 10",
		"LLM01:2025",
	),
	(
		"disregard-your-instructions",
		"Instruction Override",
		"High",
		r"\b(?:disregard|forget|discard|override)\s+(?:all\s+|any\s+|your\s+)?(?:previous\s+|prior\s+|earlier\s+)?(?:instruction|instructions|rule|rules|guideline|guidelines|system\s+prompt)\b",
		"regex",
		"any",
		"Flag",
		"OWASP LLM Top 10",
		"LLM01:2025",
	),
	(
		"new-instructions-follow",
		"Instruction Override",
		"Medium",
		r"\b(?:new|updated|revised)\s+instructions?\s*(?::|follow|below|are)\b",
		"regex",
		"any",
		"Flag",
		"OWASP LLM Top 10",
		"LLM01:2025",
	),
	# ---- Role manipulation / jailbreak persona ----------------------------
	(
		"you-are-now",
		"Role Manipulation",
		"Medium",
		r"\byou\s+are\s+now\s+(?:a|an|the)\b",
		"regex",
		"input",
		"Flag",
		"MITRE ATLAS",
		"AML.T0051",
	),
	(
		"developer-mode",
		"Jailbreak Persona",
		"High",
		r"\b(?:developer|dev|god|admin|root|debug)\s+mode\b",
		"regex",
		"input",
		"Flag",
		"Garak",
		"dan",
	),
	(
		"do-anything-now",
		"Jailbreak Persona",
		"High",
		r"\bdo\s+anything\s+now\b|\bDAN\s+mode\b",
		"regex",
		"input",
		"Flag",
		"Garak",
		"dan",
	),
	(
		"pretend-you-have-no-restrictions",
		"Jailbreak Persona",
		"High",
		r"\b(?:pretend|act\s+as\s+if|imagine)\b[^.\n]{0,60}\b(?:no\s+(?:restriction|restrictions|rules|limits|filter|filters)|unrestricted|unfiltered)\b",
		"regex",
		"input",
		"Flag",
		"Garak",
		"dan",
	),
	# ---- System prompt extraction — OWASP LLM07 ---------------------------
	(
		"reveal-system-prompt",
		"System Prompt Extraction",
		"Critical",
		r"\b(?:reveal|show|print|repeat|output|display|reproduce)\b[^.\n]{0,40}\b(?:system\s+prompt|initial\s+instructions?|your\s+instructions?|the\s+prompt\s+above)\b",
		"regex",
		"any",
		"Flag",
		"OWASP LLM Top 10",
		"LLM07:2025",
	),
	(
		"repeat-everything-above",
		"System Prompt Extraction",
		"High",
		r"\b(?:repeat|print|output)\b[^.\n]{0,30}\b(?:everything|all\s+text|the\s+text)\b[^.\n]{0,20}\babove\b",
		"regex",
		"any",
		"Flag",
		"OWASP LLM Top 10",
		"LLM07:2025",
	),
	(
		"what-are-your-instructions",
		"System Prompt Extraction",
		"Medium",
		r"\bwhat\s+(?:are|were)\s+your\s+(?:original\s+)?(?:instructions?|rules|system\s+prompt)\b",
		"regex",
		"any",
		"Flag",
		"OWASP LLM Top 10",
		"LLM07:2025",
	),
	# ---- Delimiter / structure injection ----------------------------------
	(
		"fake-system-turn",
		"Delimiter Injection",
		"Critical",
		r"(?:^|\n)\s*(?:\[|<|###\s*)?(?:system|assistant)\s*(?:\]|>|:)\s",
		"regex",
		"any",
		"Flag",
		"OWASP LLM Top 10",
		"LLM01:2025",
	),
	(
		"chatml-tokens",
		"Delimiter Injection",
		"High",
		# \x3c / \x3e rather than literal < and >. Frappe's mandatory-field check
		# runs strip_html() on the value, so a pattern shaped like a tag reads as
		# empty and the row is rejected. The hex escapes match the same text.
		r"\x3c\|(?:im_start|im_end|endoftext|system|user|assistant)\|\x3e",
		"regex",
		"any",
		"Flag",
		"MITRE ATLAS",
		"AML.T0051.000",
	),
	(
		"end-of-prompt-marker",
		"Delimiter Injection",
		"Medium",
		r"\b(?:end\s+of\s+(?:prompt|instructions?)|---\s*end\s*---)\b",
		"regex",
		"any",
		"Flag",
		"Garak",
		"promptinject",
	),
	# ---- Encoding evasion --------------------------------------------------
	(
		"base64-decode-and-execute",
		"Encoding Evasion",
		"High",
		r"\b(?:base64|rot13|hex)\b[^.\n]{0,40}\b(?:decode|decoded|then\s+(?:run|execute|follow))\b",
		"regex",
		"any",
		"Flag",
		"MITRE ATLAS",
		"AML.T0051",
	),
	# ---- Exfiltration — OWASP LLM02 ---------------------------------------
	(
		"exfiltrate-to-url",
		"Exfiltration",
		"Critical",
		r"\b(?:send|post|upload|exfiltrate|forward|leak)\b[^.\n]{0,40}\b(?:to|at)\s+https?://",
		"regex",
		"any",
		"Block",
		"OWASP LLM Top 10",
		"LLM02:2025",
	),
	(
		"markdown-image-exfiltration",
		"Exfiltration",
		"High",
		r"!\[[^\]]*\]\(\s*https?://[^)]*\{",
		"regex",
		"output",
		"Flag",
		"OWASP LLM Top 10",
		"LLM02:2025",
	),
	# ---- Tool abuse — OWASP LLM06 -----------------------------------------
	(
		"call-tool-without-asking",
		"Tool Abuse",
		"High",
		r"\b(?:call|invoke|run|execute)\b[^.\n]{0,30}\btool\b[^.\n]{0,40}\bwithout\b[^.\n]{0,30}\b(?:asking|confirmation|permission|approval)\b",
		"regex",
		"any",
		"Flag",
		"OWASP LLM Top 10",
		"LLM06:2025",
	),
	(
		"delete-all-records",
		"Tool Abuse",
		"Critical",
		r"\b(?:delete|drop|truncate|wipe|purge)\s+(?:all|every|the\s+entire)\b[^.\n]{0,30}\b(?:record|records|table|tables|document|documents|data)\b",
		"regex",
		"any",
		"Block",
		"OWASP LLM Top 10",
		"LLM06:2025",
	),
]


def execute():
	if not frappe.db.table_exists("AI Injection Pattern"):
		return

	created = 0
	for (
		name,
		ptype,
		severity,
		pattern,
		match_mode,
		boundary,
		action,
		taxonomy,
		reference,
	) in PATTERNS:
		# Never overwrite: a rule an admin disabled or tuned stays as they left it.
		if frappe.db.exists("AI Injection Pattern", name):
			continue
		doc = frappe.new_doc("AI Injection Pattern")
		doc.pattern_name = name
		doc.pattern_type = ptype
		doc.severity = severity
		doc.pattern = pattern
		doc.match_mode = match_mode
		doc.boundary_scope = boundary
		doc.action = action
		doc.source_taxonomy = taxonomy
		doc.source_reference = reference
		doc.enabled = 1
		doc.insert(ignore_permissions=True)
		created += 1

	if created:
		frappe.db.commit()

	from one_bpmn.one_bpmn.doctype.ai_injection_pattern.ai_injection_pattern import (
		clear_pattern_cache,
	)

	clear_pattern_cache()
