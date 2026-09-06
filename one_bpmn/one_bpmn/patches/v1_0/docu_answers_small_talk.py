# Copyright (c) 2026, one-fm and contributors
"""Docu invented work when it was only greeted.

Its intent classifier could return CREATE, MODIFY or DISAMBIGUATE and nothing
else, so "hi" became CREATE and the agent designed a DocType nobody asked for
(run bj5gs3apj6 produced a "Blocker Flagged" form). Greeting-only runs cost
7-8k tokens each — reproduced on this bench at 8,575 tokens over 5 model calls
for "hello" — and "Say OK" ran two full write/review rounds (13,424 tokens).

Three changes, all following the pattern ProsAlly already uses for its
``redirect`` tool — a canned reply written straight to the turn output:

1. Docu gains a ``redirect`` sub-prompt: the greeting and the offer to help.
2. Its ``intent_classifier`` prompt gains SMALL_TALK and OFF_TOPIC.
3. ``Docu – Tool Classify Intent`` decides small talk itself, in the map and
   BEFORE any model call, and answers from the canned reply. ``Docu – Tool Write
   Schema`` refuses a second round once the classifier has said there is nothing
   to design from, so a stray classification cannot loop.

Everything lives in the map: the test is flat code inside the tool script, so a
site takes this change through the patch alone — no Python to deploy.

Idempotent throughout.
"""

import frappe

_AGENT_ID = "docu_agent"

_GREETING = (
	"Hello! I build Frappe forms (DocTypes) for the steps in your process — tell "
	"me what you need to keep track of and I'll put one together. For example: "
	"\"a form to log site inspections with a date, an inspector and a pass/fail "
	"result\". I can also change a form that already exists."
)

# ── 1 + 2. configuration ────────────────────────────────────────────────────

_INTENT_OLD = """- DISAMBIGUATE — the request is vague, could mean more than one thing, or the target DocType is unclear"""

_INTENT_NEW = """- DISAMBIGUATE — the request is vague, could mean more than one thing, or the target DocType is unclear
- SMALL_TALK — a greeting, an acknowledgement or a pleasantry ("hi", "thanks", "ok", "are you there") with nothing to build from. NEVER guess a DocType for one of these.
- OFF_TOPIC — a real request, but for something other than designing a form: ask about the weather, write code, explain a process."""

_INTENT_ENUM_OLD = '{"intent": "CREATE|MODIFY|DISAMBIGUATE", "reason": "one short sentence"}'
_INTENT_ENUM_NEW = '{"intent": "CREATE|MODIFY|DISAMBIGUATE|SMALL_TALK|OFF_TOPIC", "reason": "one short sentence"}'

# ── 3. the tools ────────────────────────────────────────────────────────────

_CLASSIFY_OLD = '''_system = (_subs.get("intent_classifier") or {}).get("prompt") or ""
raw = run_sync(_adapter.complete(system=_system, user=prompt)).text

intent = "MODIFY" if exists else "CREATE"
try:
    intent = json.loads((raw or "").strip()).get("intent", intent).upper()
except (json.JSONDecodeError, TypeError, AttributeError):
    pass
if intent not in ("CREATE", "MODIFY", "DISAMBIGUATE"):
    intent = "MODIFY" if exists else "CREATE"

# Deterministic routing so the orchestrator never skips a stage.
nxt = "clarify" if intent == "DISAMBIGUATE" else "write_schema"

# Seed the MODIFY baseline once so write_schema/finalize can diff against it.
current_ir = read_doctype_definition(doctype) if exists else None
update_turn(context_docname, intent=intent, exists=exists, current_ir=current_ir)
result["intent"] = intent
result["next"] = nxt'''

_CLASSIFY_NEW = '''# ── small-talk test: START (flat, no def/lambda — shape-tool exec) ──
# A greeting is not a specification. Deciding that HERE, before any model call,
# is what stops the classifier having to pick CREATE and the agent inventing a
# form nobody asked for. Conservative on purpose: refusing real work is the
# expensive mistake, so this fires only on a short message that says nothing
# about data, fields or records.
import re

_chatter = set()
for _w in (
    "a afternoon alright am and are back bye can cheers cool day do does evening "
    "excellent fine good goodbye great hallo hello help hey hi hiya how howdy i is "
    "it just k kk later lovely me morning much my name nice night no now ok okay "
    "okey perfect ping please pong really right say see so sup sure test testing "
    "thank thanks thanx there this thx to u up welcome well what who with working "
    "works yeah yep yes yo you your yours yw"
).split():
    _chatter.add(_w)

_substantive = (
    r"\b(doctype|doc\s?type|form|forms|field|fields|table|tables|record|records|"
    r"schema|column|columns|entity|register|registry|log|logs|report|reports|track|"
    r"tracking|capture|store|storing|create|add|remove|rename|change|modify|update|"
    r"delete|drop|link|select|status|state|workflow|approval|request|requests|"
    r"invoice|employee|customer|supplier|item|items|date|amount|currency|attachment|"
    r"child|parent|naming|permission|role|roles|mandatory|required|unique|default|"
    r"option|options|dropdown|checkbox|number|text|data|json|serial|barcode|"
    r"equipment|asset|assets|leave|attendance|payroll|ticket|issue|blocker|"
    r"inspection|survey|feedback)\b"
)

_msg = (message or "").strip()
_words = re.findall(r"[a-z']+", _msg.lower())
_small_talk = False
if not _msg or not _words:
    _small_talk = True
elif re.search(_substantive, _msg, re.IGNORECASE):
    _small_talk = False
elif len(_words) > 8:
    _small_talk = False
else:
    _small_talk = True
    for _w in _words:
        if _w not in _chatter:
            _small_talk = False
            break
# ── small-talk test: END ──

# SMALL_TALK is a greeting or an acknowledgement; OFF_TOPIC is a real request
# for something this agent does not do. Both take the same cheap path, so the
# classifier prompt may return either.
_cheap_intents = ("SMALL_TALK", "OFF_TOPIC")
_greeting = (_subs.get("redirect") or {}).get("prompt") or (
    "Hello! I build Frappe forms (DocTypes) for the steps in your process — tell "
    "me what you need to keep track of and I'll put one together."
)

intent = "SMALL_TALK" if _small_talk else ""

if not intent:
    _system = (_subs.get("intent_classifier") or {}).get("prompt") or ""
    raw = run_sync(_adapter.complete(system=_system, user=prompt)).text
    intent = "MODIFY" if exists else "CREATE"
    try:
        intent = json.loads((raw or "").strip()).get("intent", intent).upper()
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass
    if intent not in ("CREATE", "MODIFY", "DISAMBIGUATE") and intent not in _cheap_intents:
        intent = "MODIFY" if exists else "CREATE"

if intent in _cheap_intents:
    # ProsAlly's redirect pattern: the canned reply IS the turn's output, so no
    # schema stage runs and the turn ends here.
    update_turn(
        context_docname,
        intent=intent,
        exists=exists,
        content_free=True,
        output={
            "intent": intent,
            "response": _greeting,
            "doctype_ir": None,
            "diff": None,
            "options": None,
            "suggested_name": None,
        },
        done=True,
    )
    result["intent"] = intent
    result["next"] = None
    result["response"] = _greeting
else:
    # Deterministic routing so the orchestrator never skips a stage.
    nxt = "clarify" if intent == "DISAMBIGUATE" else "write_schema"

    # Seed the MODIFY baseline once so write_schema/finalize can diff against it.
    current_ir = read_doctype_definition(doctype) if exists else None
    update_turn(context_docname, intent=intent, exists=exists, current_ir=current_ir)
    result["intent"] = intent
    result["next"] = nxt'''

_CLASSIFY_MARKER = "# ── small-talk test: START"

_WRITE_OLD = '''_system = (_subs.get("schema_writer") or {}).get("prompt") or ""
draft = run_sync(_adapter.complete(system=_system, user=prompt, tools=_writer_tools)).text or ""'''

_WRITE_NEW = '''# One round is the cap when the classifier found nothing to design from. "Say OK"
# ran two full write/review cycles for 13,424 tokens; a stray CREATE must not be
# able to spend the turn cap on a message with no form content in it.
_rounds = int(turn.get("write_rounds") or 0)
_content_free = bool(turn.get("content_free"))

if _content_free and _rounds >= 1:
    draft = ""
    result["has_ir"] = False
    result["error"] = (
        "This request has no form content to design from, and one attempt has "
        "already been made. Ask the user what the form should capture instead."
    )
else:
    update_turn(context_docname, write_rounds=_rounds + 1)
    _system = (_subs.get("schema_writer") or {}).get("prompt") or ""
    draft = run_sync(_adapter.complete(system=_system, user=prompt, tools=_writer_tools)).text or ""'''

_WRITE_MARKER = "_rounds = int(turn.get(\"write_rounds\") or 0)"


def _set_config(name):
	"""Add the redirect message and teach the classifier the two cheap intents."""
	rows = frappe.get_all(
		"AI Agent Sub Prompt",
		filters={"parent": name},
		fields=["name", "sub_agent_id", "prompt_text"],
	)
	by_id = {r.sub_agent_id: r for r in rows}

	if "redirect" not in by_id:
		doc = frappe.get_doc("AI Agent Configuration", name)
		doc.append(
			"sub_prompts",
			{
				"sub_agent_id": "redirect",
				"sub_agent_name": "Redirect Message",
				"temperature": 0.0,
				"prompt_text": _GREETING,
			},
		)
		doc.save(ignore_permissions=True)
		print(f"docu_answers_small_talk: added the redirect message to {name}")

	classifier = by_id.get("intent_classifier")
	if classifier and "SMALL_TALK" not in (classifier.prompt_text or ""):
		text = classifier.prompt_text or ""
		if _INTENT_OLD in text:
			text = text.replace(_INTENT_OLD, _INTENT_NEW, 1)
		if _INTENT_ENUM_OLD in text:
			text = text.replace(_INTENT_ENUM_OLD, _INTENT_ENUM_NEW, 1)
		if text != (classifier.prompt_text or ""):
			frappe.db.set_value("AI Agent Sub Prompt", classifier.name, "prompt_text", text,
			                    update_modified=False)
			print(f"docu_answers_small_talk: taught {name}'s classifier SMALL_TALK/OFF_TOPIC")


def _edit_script(script_name, old, new, marker):
	if not frappe.db.exists("Server Script", script_name):
		return
	script = frappe.db.get_value("Server Script", script_name, "script") or ""
	if marker in script or old not in script:
		return
	frappe.db.set_value(
		"Server Script", script_name, "script", script.replace(old, new, 1), update_modified=False
	)
	print(f"docu_answers_small_talk: updated {script_name}")


def execute():
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": _AGENT_ID}, "name")
	if name:
		_set_config(name)
	_edit_script("Docu – Tool Classify Intent", _CLASSIFY_OLD, _CLASSIFY_NEW, _CLASSIFY_MARKER)
	_edit_script("Docu – Tool Write Schema", _WRITE_OLD, _WRITE_NEW, _WRITE_MARKER)
