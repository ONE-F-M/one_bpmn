"""
WI-002042: ProsAlly must draw the lanes the designer asked for, and no others.

Asked for "3 lanes only: Recruiter, GRD Operator, GRD Manager", it produced four
— the extra one being "System (Automatic)". That lane was not a stray guess; it
was instructed, in three separate places:

  * process_generator, STEP 1: 'Any automated step … → "System (Automatic)"' and
    'Minimum: if only one human is mentioned, still add "System (Automatic)" as a
    second lane'
  * process_generator, STEP 2: 'scriptTask → "system"' / 'serviceTask → "system"'
  * modifier: 'Automated steps → "system" lane, name "System (Automatic)".'

So the model was following orders. This patch makes a designer-named lane set
authoritative: when the request names the lanes, that list IS the lanes array —
nothing added, renamed or dropped — and automated steps are assigned to the role
responsible for them instead of to an invented system lane. When the request
names no lanes, the existing behaviour is untouched: the actors are identified
from the description, automated work still gets its own lane, and the minimum of
two still applies.

The same prompts also gain a rework-loop rule. Every rejection path in a real
approval process tends to be drawn as its own return line back to an early step,
and each of those lines then crosses everything between. Converging them on one
re-entry point is both fewer lines and how a business reader expects to see it —
it is the largest remaining lever on diagram readability now that the router
places nothing through a shape (see one_bpmn/tests/test_lane_layout.py).

The prompts live on the prosally AI Agent Configuration and are read live at
dispatch, so no recompile is needed and running conversations pick them up on
their next turn.

The matching change to "ProsAlly – Tool Generate Process" — whose repair hint
carried the same 'plus System (Automatic)' instruction, and which rejected any IR
with fewer than two lanes — is a Server Script, so it travels by Processa export
rather than by patch.

Idempotent: returns early once the new rules are in place. If a prompt has been
hand-edited away from the expected text it is left alone and logged, never
overwritten.
"""

import frappe

CONFIG_NAME = "prosally"

# Present only once every rule below has been applied — the idempotency marker.
# Deliberately a phrase from the LAST edit rather than the first: an earlier
# revision of this patch added STEP 0 while leaving S3 ("All automated steps
# belong in a dedicated System (Automatic) lane") standing, so the prompt gave
# the model two contradictory orders and the extra lane could come back.
_MARKER = "when the designer has NOT named the lanes"

# ── process_generator ────────────────────────────────────────────────────────

GEN_STEP1_ANCHOR = "=== STEP 1 — IDENTIFY ROLES (DO THIS FIRST, EVERY TIME) ==="

GEN_STEP0 = """=== STEP 0 — LANES THE DESIGNER NAMED WIN, ALWAYS ===

If the request names the lanes — "3 lanes only: Recruiter, GRD Operator, GRD
Manager", "lanes are Employee, Manager, HR", "swimlanes: Customer and Support" —
then the "lanes" array is EXACTLY that list, in that order.

  • Do not add a lane. Do not rename one. Do not drop one.
  • In particular do NOT add a "System (Automatic)" lane. If the designer did not
    name it, it does not exist.
  • Automated steps still have to live somewhere: put each one in the lane of the
    role responsible for it — whoever triggers it, or whoever acts on its result.
    An email to the recruiter after the GRD Operator submits belongs to the GRD
    Operator; a validation that runs while the Recruiter fills the form belongs
    to the Recruiter.
  • The count the designer states is the count you output. "3 lanes only" means
    three.

Only when the request does NOT name the lanes do you identify the actors
yourself — that is STEP 1 below.

"""

GEN_STEP1_HEADER_OLD = "=== STEP 1 — IDENTIFY ROLES (DO THIS FIRST, EVERY TIME) ==="
GEN_STEP1_HEADER_NEW = (
	"=== STEP 1 — IDENTIFY ROLES (ONLY WHEN THE DESIGNER NAMED NO LANES) ==="
)

GEN_STEP2_OLD = '  • scriptTask      → "system"\n  • serviceTask     → "system"\n'
GEN_STEP2_NEW = (
	'  • scriptTask      → "system" if a system lane exists, otherwise the lane of\n'
	'                      the role responsible for that step\n'
	'  • serviceTask     → "system" if a system lane exists, otherwise the lane of\n'
	'                      the role responsible for that step\n'
)

# The three places that ordered a system lane OUTRIGHT. STEP 0 alone does not
# settle it: a model reading "designer's lanes win" and then "ALL automated steps
# belong in a dedicated System (Automatic) lane" three paragraphs later has been
# told two different things, and the stronger, more specific wording tends to
# win. Each becomes conditional instead.
GEN_S3_OLD = (
	'S3  All automated steps (send email, check records, validate, calculate, create/update doc)\n'
	'    belong in a dedicated "System (Automatic)" lane, separate from human lanes.\n'
)
GEN_S3_NEW = (
	'S3  When the designer has NOT named the lanes, all automated steps (send email,\n'
	'    check records, validate, calculate, create/update doc) belong in a dedicated\n'
	'    "System (Automatic)" lane, separate from human lanes. When the designer HAS\n'
	'    named the lanes, there is no such lane unless they named it — each automated\n'
	'    step goes in the lane of the role responsible for it.\n'
)

GEN_FALLBACK_OLD = 'If you cannot identify 2 human roles, use "User" + "System (Automatic)".\n'
GEN_FALLBACK_NEW = (
	'If you cannot identify 2 human roles, use "User" + "System (Automatic)" —\n'
	'but only when the designer has NOT named the lanes. A named lane set is used\n'
	'exactly as given, whatever its size.\n'
)

GEN_CHECK_OLD = '  ✓ "lanes" array is present with 2+ entries — ALWAYS, no exceptions\n'
GEN_CHECK_NEW = (
	'  ✓ "lanes" array matches the lanes the designer named, exactly — same lanes,\n'
	'    same order, nothing added. If they named none, 2+ entries as usual\n'
)

GEN_STEP1_BULLET_OLD = (
	'  • Any automated step (send email, validate, calculate, check, create record, notify) → "System (Automatic)"\n'
)
GEN_STEP1_BULLET_NEW = (
	'  • Any automated step (send email, validate, calculate, check, create record,\n'
	'    notify) → "System (Automatic)" — this step applies only when the designer\n'
	'    named no lanes, so the system lane is yours to add here\n'
)

# NOTE: the replacement must not CONTAIN the text it replaces, or a second run
# matches it again and appends the qualifier twice. Learnt the hard way.
GEN_MIN_OLD = '  • Minimum: if only one human is mentioned, still add "System (Automatic)" as a second lane\n'
GEN_MIN_NEW = (
	'  • Minimum: when only one human is mentioned, add a second lane for the\n'
	'    automated steps — again, only where the designer named no lanes\n'
)

# Appended to both prompts.
REWORK_RULE = """

=== REWORK LOOPS — ONE RE-ENTRY POINT ===

Approval processes send work back: rejected, changes requested, resubmit,
re-check, awaiting quota. When several outcomes return the work to the SAME
stage, route them all into ONE re-entry point — a single join gateway in front of
that stage — instead of drawing a separate return from each rejection.

One shared re-entry:
  gw_pam_reject, gw_moi_reject, gw_mgr_reject  →  gw_back_to_operator  →  task_operator_revise

not three separate flows from three rejection points back across the diagram.

This is how a business reader expects to see rework, and it is also what keeps
the drawing legible: every separate return is a line running the full width of
the diagram, crossing every flow that changes lane along the way.
"""

# ── modifier ─────────────────────────────────────────────────────────────────

MOD_OLD = (
	'  Role identification: any named person/team gets their own lane.\n'
	'  Automated steps → "system" lane, name "System (Automatic)".\n'
	'  Assign: userTask → person\'s lane id; scriptTask/serviceTask → "system";\n'
)
MOD_NEW = (
	'  LANES THE DESIGNER NAMED WIN: if the request names the lanes, the "lanes"\n'
	'  array is exactly that list — nothing added, renamed or dropped, and no\n'
	'  "System (Automatic)" lane unless they asked for one.\n'
	'  Otherwise keep the lanes the current XML already has.\n'
	'  Role identification: any named person/team gets their own lane.\n'
	'  Automated steps → the "system" lane when one exists; when there is none,\n'
	'  the lane of the role responsible for the step.\n'
	'  Assign: userTask → person\'s lane id; scriptTask/serviceTask → the system\n'
	'  lane if there is one, else the responsible role\'s lane;\n'
)


def execute():
	"""Make designer-named lanes authoritative for ProsAlly (WI-002042)."""
	if not frappe.db.exists("AI Agent Configuration", CONFIG_NAME):
		return

	doc = frappe.get_doc("AI Agent Configuration", CONFIG_NAME)
	by_id = {sp.sub_agent_id: sp for sp in (doc.sub_prompts or [])}

	generator = by_id.get("process_generator")
	modifier = by_id.get("modifier")
	if not generator or not modifier:
		_complain("process_generator or modifier sub-prompt is missing")
		return

	if _MARKER in (generator.prompt_text or "") and _MARKER in (modifier.prompt_text or ""):
		return

	gen = generator.prompt_text or ""
	mod = modifier.prompt_text or ""

	# Applied best-effort: a site part-way through an earlier revision of this
	# patch already has some of them, and re-running must finish the job rather
	# than bail. Only a prompt where NOTHING matches has genuinely diverged.
	gen_edits = [
		(GEN_STEP1_ANCHOR, GEN_STEP0 + GEN_STEP1_HEADER_NEW),
		(GEN_STEP2_OLD, GEN_STEP2_NEW),
		(GEN_S3_OLD, GEN_S3_NEW),
		(GEN_FALLBACK_OLD, GEN_FALLBACK_NEW),
		(GEN_CHECK_OLD, GEN_CHECK_NEW),
		(GEN_STEP1_BULLET_OLD, GEN_STEP1_BULLET_NEW),
		(GEN_MIN_OLD, GEN_MIN_NEW),
	]
	applied = 0
	for old, new in gen_edits:
		if old in gen:
			gen = gen.replace(old, new, 1)
			applied += 1
	if not applied:
		_complain("process_generator matched none of the expected passages")
		return
	if "REWORK LOOPS" not in gen:
		gen += REWORK_RULE

	if MOD_OLD in mod:
		mod = mod.replace(MOD_OLD, MOD_NEW, 1)
	elif "LANES THE DESIGNER NAMED WIN" not in mod:
		_complain("modifier no longer contains the expected lane passage")
		return
	if "REWORK LOOPS" not in mod:
		mod += REWORK_RULE

	generator.prompt_text = gen
	modifier.prompt_text = mod

	# db_set on the child rows, not doc.save: saving a Live agent re-runs the AI
	# Agent Creation Process (adversarial suite, real model calls), which is far
	# too much for a prompt correction and would leave the agent mid-provisioning
	# during a migrate. The prompts are read live at dispatch either way.
	generator.db_set("prompt_text", gen, update_modified=False)
	modifier.db_set("prompt_text", mod, update_modified=False)


def _complain(detail: str):
	frappe.log_error(
		title="prosally_lane_fidelity: prompt anchor not found",
		message=(
			f"{detail}. The lane rules were NOT applied. Add them by hand: a lane set "
			"named in the request is authoritative (no invented 'System (Automatic)' "
			"lane), and rework paths converge on one re-entry point."
		),
	)
