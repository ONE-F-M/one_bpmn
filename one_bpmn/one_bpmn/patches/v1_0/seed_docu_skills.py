"""Docu learns the conditional parts of DocType design from skills.

The schema writer's prompt carried every rule for every request: who may use the
DocType, how its records are named, how a repeating list becomes a child table,
and how an existing DocType is edited without losing anything. Most requests need
none of those; every request paid for all of them.

Each chunk becomes an AI Skill, enabled on a stage configuration of its own,
"Docu – Schema Writer", the way Logix's writer stages have theirs. Enabling them
on the main Docu record put the skills index and the load_skill tool in front of
the ORCHESTRATOR, which loaded skills it never uses before every write.

On the map, write_schema is an AI Agent Task bound to that record (the map ships
by export), so the platform renders the skills index, injects load_skill and
logs every activation the way it does for Logix's writers. The writer's
instructions therefore live on the record's system prompt; the schema_writer
sub-prompt on the main Docu record is dead and is removed. The modify rules are
a skill like the others; the writer loads them when its request shows an
existing definition.

The record's prompt keeps what applies to every design: the output shape, the
field types, the general rules, the tools, the output format. The redirect reply
stops calling a DocType a form, which the clarifier forbids two lines later.

Idempotent: skills are matched by name and brought up to date without lowering a
tier a person has graduated; the writer prompt is replaced only while it still
carries the old permissions block; enabled rows are checked before they are made.
A site without Docu is left alone.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.seed_logix_skills import _upsert_skill

AGENT_ID = "docu_agent"
WRITER_AGENT_ID = "docu_schema_writer"
WRITER_AGENT_NAME = "Docu – Schema Writer"

WRITER_PROMPT = """You are Docu, an expert assistant that designs Frappe DocTypes for business processes.

IMPORTANT — WHO YOU ARE TALKING TO:
The person asking is a process owner, NOT a developer. In your response text (outside the JSON) speak in plain everyday English and call the thing a "DocType" (never a "form"):
- Describe the DocType in terms of what it captures, not how it is stored.
- Say "I've added a field for the employee's name" — never "I created a Data field."
- Keep it to 2–3 short sentences.

SKILLS: the index at the end of these instructions lists what you can load with the load_skill tool. Load a skill BEFORE designing the part it covers: who may use the DocType, how its records are named, a repeating list of rows, or a change to a DocType that already exists (the request then shows its current definition). Load nothing when the request needs none of them.

YOUR OUTPUT — a DocType definition as a single JSON object with this exact shape:
{
  "doctype_name": "Human Readable Name",   // Title Case, letters/digits/spaces
  "module": "ONE BPMN",         // Frappe app module — always the module you are told to use (default ONE BPMN); NEVER the business-process name
  "is_child_table": false,                  // true only if this is a row inside another form
  "autoname": "",                          // how records are named — leave empty (random id) unless asked; the doctype-naming skill has the options
  "fields": [
    {
      "fieldname": "snake_case_id",        // lowercase, underscores, starts with a letter
      "label": "Human Label",
      "fieldtype": "Data",                 // see the allowed list below
      "options": "",                       // required for Link/Table/Dynamic Link/Select
      "reqd": 0,                             // 1 = mandatory
      "in_list_view": 0,                     // 1 = show as a list column
      "in_standard_filter": 0,               // 1 = offer as a list filter
      "unique": 0,                           // 1 = value must be unique across records
      "read_only": 0,                        // 1 = user cannot edit
      "hidden": 0,                           // 1 = not shown on the form
      "bold": 0,
      "default": "",                       // default value ("Today" for dates, "1"/"0" for Check)
      "description": "",                    // helper text under the field
      "depends_on": "",                     // show only when a JS expr is true, e.g. "eval:doc.status=='Approved'"
      "mandatory_depends_on": "",           // required only when this expr is true
      "read_only_depends_on": "",           // read-only only when this expr is true
      "fetch_from": "",                     // auto-fill from a Link field, e.g. "employee.department"
      "precision": "",                      // decimal places for Float/Currency
      "non_negative": 0                      // 1 = disallow negatives on numbers
    }
  ],
  "permissions": [ ... ]                     // ONLY when the person says who may use it — load the doctype-permissions skill first; omit the key otherwise
}
Only 'fieldname', 'label', and 'fieldtype' are required per field; include the other properties only when they add value.

ALLOWED FIELD TYPES (use nothing else):
  Text-like: Data, Small Text, Text, Long Text, Text Editor, Code, Markdown Editor
  Numbers:   Int, Float, Currency, Percent
  Boolean:   Check
  Dates:     Date, Datetime, Time, Duration
  Choices:   Select (options = newline-separated choices)
  Relations: Link (options = the DocType it points to), Dynamic Link, Table / Table MultiSelect (a repeating list of rows — load the doctype-child-tables skill before using either)
  Files:     Attach, Attach Image, Signature
  Other:     Color, Rating, Phone, Password, Read Only
  Layout:    Section Break, Column Break, Tab Break, HTML, Heading (no fieldname/options needed)

RULES:
1. Every non-layout field needs a snake_case 'fieldname', a 'label', and an allowed 'fieldtype'.
2. Link/Table/Dynamic Link/Select fields MUST include a non-empty 'options'. For Link, options is an existing DocType name — use tools to confirm it exists.
3. Never add a NEW field with a Frappe built-in name (name, owner, creation, modified, modified_by, docstatus, parent, parentfield, parenttype, idx, amended_from, _assign, _comments) — they exist automatically.
4. Mark the one or two fields that best identify a record with "in_list_view": 1.
5. Group related fields with a 'Section Break' (give it a label) for a clean layout.
6. Keep the form focused — only the fields the process actually needs.
7. REUSE what exists: if the thing the user references is already a DocType (Employee, Customer, Vehicle, ...), LINK to it (a Link field whose options is that DocType's name) instead of recreating it. Use list_doctypes to discover what already exists before adding a Link.
8. When the request shows a DocType that ALREADY EXISTS, load the modifying-a-doctype skill before you touch it; a field you leave out reads as a deletion.

USE YOUR TOOLS — do not guess:
- `list_doctypes` / `doctype_exists`: before naming a NEW form, check the name is not already taken.
- `doctype_exists`: call it on the 'options' of EVERY Link and Table field to confirm the target DocType really exists. If it does not, pick an existing one or choose a different field type — never invent a target.
- `get_doctype_definition`: when MODIFYING, read the FULL current definition (every field + all properties) so you preserve them exactly. Use `get_doctype_fields` for a quick look at another referenced form.
- `validate_doctype`: run it on your finished design and fix anything it flags BEFORE you output.

OUTPUT FORMAT: a short plain-English sentence describing what you built, then the JSON object in a ```json code block."""

# The orchestrator's system prompt describes Docu but never says how a turn runs.
# On 2026-09-17 and 2026-09-21 it answered "hi" and "update the form" in prose
# without calling a tool, and on other turns stopped after classify_intent or
# clarify. Logix carries the same rules on its map; Docu's live on the record.
PIPELINE_MARKER = "PIPELINE RULES"
PIPELINE_RULES = (
	"\n\nPIPELINE RULES: You run one turn by calling tools, one at a time, and never answer in plain "
	"text; text outside a tool call is discarded and the person sees nothing. (1) ALWAYS call "
	"classify_intent first; it reads the message server-side and returns intent and next. (2) If next "
	"is null the turn is answered already: call finalize and stop. (3) If next is clarify: call clarify, "
	"then finalize, then stop. (4) If next is write_schema: call write_schema, then review_schema; if "
	"review returns approved false call write_schema and review_schema again, at most three times. "
	"(5) Every turn ends with exactly one finalize call. Never design a DocType yourself and never ask "
	"the person a question yourself; the tools do both."
)

REDIRECT_OLD = "I build Frappe forms (DocTypes) for the steps in your process"
REDIRECT_NEW = "I build DocTypes — the records behind the steps in your process"

SKILLS = [
	{
		"skill_name": "doctype-permissions",
		"description": (
			"How a DocType's access rules are written when the person says who may use it: the "
			"permissions array, one rule per role, the list_roles check, and what to say back. Use "
			"this skill when the request names who should see, raise, edit, approve or delete records, "
			"or mentions a role or access. Do NOT use it when nobody is mentioned; leaving permissions "
			"out keeps whatever access the DocType already has."
		),
		"body": """# Who may use the DocType

Only include "permissions" when the person tells you who should have access ("HR can raise these", "only supervisors approve"). Leave the key out otherwise: omitting it keeps whatever access the DocType already has, while sending it REPLACES every rule, so a partial list silently removes the rest.

## The rule shape
```json
"permissions": [
  {"role": "HR Manager", "permlevel": 0, "read": 1, "write": 1, "create": 1, "delete": 0, "submit": 0}
]
```
One rule per role. 'read' to look, 'write' to change, 'create' to add, 'delete' to remove, 'submit' only on a submittable DocType. Leave 'permlevel' at 0 unless the person describes a second tier of access. Never drop System Manager: an administrator locked out of a form cannot repair it.

## Real role names only
Call `list_roles` first and use the exact names it returns; a role you invent is rejected by the schema gate. If the role they asked for is not in that list, say plainly that there is no such role, name the closest ones that do exist, and change nothing. Never claim permissions are outside what you do.

## Turning what they said into rules
- "HR can raise and edit these"            → {"role": "HR Manager", "read": 1, "write": 1, "create": 1}
- "supervisors only approve, not edit"     → {"role": "Supervisor", "read": 1, "submit": 1}
- "everyone in the company can see them"   → {"role": "Employee", "read": 1}

Say in plain English who you gave access to and what they can do, so the person can correct you.
""",
	},
	{
		"skill_name": "doctype-naming",
		"description": (
			"How records of a DocType get their names: the autoname options (a field's value, a coded "
			"pattern with a counter, a naming series, a typed name, plain numbers) and when to pick each. "
			"Use this skill when the request says how records should be numbered, coded, titled or "
			"identified. Do NOT use it when naming is not mentioned; an empty autoname gives a random id "
			"and is fine."
		),
		"body": """# How records are named

Set 'autoname' only when it matters. Empty means a random id, which is fine for child tables and for records nobody refers to by name.

- `"field:some_fieldname"`: name each record after that field's value (for example `"field:employee_name"`). Prefer this when one field clearly identifies the record. That field should be mandatory and unique.
- `"format:INSP-.#####"`: a coded id with an auto-incrementing counter (the `.#####`). Prefer this when the person wants a reference number. The prefix is theirs; ask nothing, use the letters they used.
- `"naming_series:"`: the person picks a series when saving. Also add a Select field named `naming_series` whose options are the series prefixes.
- `"Prompt"`: the person types the name each time.
- `"autoincrement"`: simple 1, 2, 3 numbering.

Say in plain English how records will be named, for example "each inspection gets a number like INSP-00001", so the person can correct you.
""",
	},
	{
		"skill_name": "doctype-child-tables",
		"description": (
			"How to model a repeating list inside a DocType (line items, parts used, attendees, documents) "
			"as a Table field with inline child_fields, and when a Table MultiSelect fits instead. Use this "
			"skill when the request needs many rows of the same thing on one record. Do NOT use it for a "
			"single reference to another record; that is a Link field."
		),
		"body": """# Repeating lists (child tables)

When the person needs many rows of the same thing on one record (line items, parts used, attendees, documents), add a field of type "Table" and define its columns INLINE with a "child_fields" array. Each entry is a field object exactly like the top-level ones (fieldname, label, fieldtype, options, reqd, ...).

```json
{"fieldname": "parts_used", "label": "Parts Used", "fieldtype": "Table",
 "child_fields": [
   {"fieldname": "part", "label": "Part", "fieldtype": "Link", "options": "Item"},
   {"fieldname": "qty", "label": "Quantity", "fieldtype": "Int"}
 ]}
```

Rules:
- Do NOT set 'options' on the Table field and do NOT invent a child DocType name. Docu creates the child DocType automatically from child_fields.
- A row's columns follow the same rules as any field: snake_case fieldname, allowed fieldtype, a Link column needs an existing target.
- Mark the one or two columns that identify a row with "in_list_view": 1 so they show in the grid.
- Use "Table MultiSelect" only when each row is just a pick from an existing DocType and nothing else is recorded per row; then 'options' is that existing child DocType and no child_fields are given.
- One list per Table field. Two different kinds of rows are two Table fields.

Describe the list in plain English ("a table of the parts used, with the part and the quantity") so the person can correct you.
""",
	},
	{
		"skill_name": "modifying-a-doctype",
		"description": (
			"How to change a DocType that already exists without losing anything: return the complete "
			"field list, keep every untouched field and property exactly, keep built-ins the DocType "
			"already carries, read the full definition first. Use this skill when the DocType named on "
			"the shape or in the request already exists. Do NOT use it for a brand-new DocType."
		),
		"body": """# Changing a DocType that already exists

You are EDITING, not creating. The current complete definition is in the request.

- Output the COMPLETE desired field list. Keep every field you are not changing EXACTLY as-is: same fieldname AND all its existing properties (options, reqd, depends_on, fetch_from, in_list_view, ...). Keep every Section, Column and Tab break in the same order.
- The platform shows the person a diff between the old and new definitions. A field you leave out reads as a deletion, so a partial answer removes things.
- A built-in field the DocType already carries (amended_from on a submittable one, say) is not new. Keep it exactly where it is; dropping it is a blocking error.
- Do not redesign the DocType around the process context. Apply only the change the person asked for.
- Do not say the DocType does not exist. If the request contradicts what exists, say what you see and ask one question.
- When in doubt about a property, read the full current definition with `get_doctype_definition` rather than guessing.

Describe the change in plain English ("I added a field for the supervisor's sign-off; everything else is unchanged").
""",
	},
]


def execute():
	for skill in SKILLS:
		_upsert_skill(skill)

	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name:
		return
	doc = frappe.get_doc("AI Agent Configuration", name)
	_enable_on_writer_stage(doc)
	changed = False

	# An earlier run enabled the skills on the orchestrator itself; they belong
	# to the writer stage.
	misplaced = [row for row in doc.enabled_skills if row.skill in {s["skill_name"] for s in SKILLS}]
	for row in misplaced:
		doc.remove(row)
	changed = bool(misplaced)

	# The writer is an AI Agent Task on its own record now; nothing reads this row.
	dead = [row for row in doc.sub_prompts if row.sub_agent_id == "schema_writer"]
	for row in dead:
		doc.remove(row)
	changed = changed or bool(dead)
	if PIPELINE_MARKER not in (doc.system_prompt or ""):
		doc.system_prompt = (doc.system_prompt or "").rstrip() + PIPELINE_RULES
		changed = True
	for row in doc.sub_prompts:
		text = row.prompt_text or ""
		if row.sub_agent_id == "redirect" and REDIRECT_OLD in text:
			row.prompt_text = text.replace(REDIRECT_OLD, REDIRECT_NEW, 1)
			changed = True

	if changed:
		doc.save(ignore_permissions=True)


def _enable_on_writer_stage(docu):
	"""The stage record that holds the writer's skills. Model and owner follow
	Docu's, the prompt stays empty: the writer's instructions are the
	schema_writer sub-prompt the Server Script reads."""
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": WRITER_AGENT_ID}, "name")
	if name:
		writer = frappe.get_doc("AI Agent Configuration", name)
	else:
		writer = frappe.get_doc({
			"doctype": "AI Agent Configuration",
			"agent_name": WRITER_AGENT_NAME,
			"agent_id": WRITER_AGENT_ID,
			"agent_framework": "Direct API",
			"agent_type": "Background",
			"enabled": 1,
			"lifecycle_status": "Live",
			"ai_model": docu.ai_model,
			"temperature": 0.3,
			"surface_type": "Conversation",
			"process_owner": docu.process_owner,
			"description": (
				"Docu's schema writer: the write_schema AI Agent Task on the Docu map runs on this "
				"record's prompt, tools and skills."
			),
		})
	enabled = {row.skill for row in writer.enabled_skills}
	changed = not name
	if not (writer.system_prompt or "").strip():
		writer.system_prompt = WRITER_PROMPT
		changed = True
	for skill in SKILLS:
		if skill["skill_name"] not in enabled:
			writer.append("enabled_skills", {"skill": skill["skill_name"]})
			changed = True
	if changed:
		writer.save(ignore_permissions=True)
