# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""One-time cleanup of the AI Memory store: 272 rows down to 97.

The store had grown to 272 rows with no cleanup ever run, and every row read the
same way to a human as it did to the retrieval query: no distinction between a
durable fact and the agent's own system prompt talking to itself. Every one of
the 175 rows this deletes (and the one it rewrites) was read individually and
classified by hand before this patch was written — nothing here is decided at
migrate time. What follows is what that read found, not a live classifier.

WHAT WAS ACTUALLY IN THERE
---------------------------
- 107 rows were the tool-protocol system prompt re-stored as if it were a
  learned fact ("always call classify_intent first...", "the agent cannot see
  the conversation itself..."). One 42-row cluster alone was a single sentence
  repeated with cosmetic rewording every time it was distilled again.
- 9 more were exact-content duplicates outside that pattern.
- 45 were near-duplicates that only differ in phrasing — the same lesson
  distilled slightly differently on separate runs (e.g. five different ways of
  saying the sandbox's test suite has known pre-existing failures and no
  detailed logs, so an ambiguous failure needs a human, not a guess).
- 11 were already expired/superseded (invalidated by write-time reconciliation)
  and simply never got removed.
- 1 (qq9gekd7ah) was flatly false: it claimed the agent has no memory across
  conversations, stored inside the very system that gives it exactly that.
- 1 (36jr4rba7k) was the escaped-content row from the story's original report
  ("&lt;PROJECT&gt;..." instead of "<PROJECT>...") — already dead (expired) and,
  once read, also a reworded duplicate of a live row (5sar9q5u78) that already
  states the same naming convention correctly. Deleted rather than fixed in
  place, since a dead, duplicate row's content isn't worth correcting.
- 1 (eush7eer9d) named a specific person as a workflow approver. The approval
  rule is durable; the named individual isn't, so this one is REWRITTEN
  in place rather than deleted or kept as-is.
- One live contradiction surfaced only by reading both sides: one row said
  Vue/CSS/JS work is delegated to the Frontend Agent, another said Frontend
  Agent delegation is refused and to use the Dev Agent instead. Confirmed
  which is current and deleted the stale one.

WHY 97, NOT THE ~25-30 ORIGINALLY HOPED FOR
--------------------------------------------
That estimate was made before anyone had read every row. 64% of the store really
was duplication (175 of 272 rows) — but the agents behind this store
(run_logix_agent, run_docu_agent, orchestrate, run_prosally_agent,
run_general_chat_agent) cover a lot of genuinely distinct ground: PAM/visa
validation, DSOT overtime approval, exit workflows, DocType design conventions,
script-writing constraints. 97 rows is what's actually left once the noise is
gone, not a number chosen to hit a target.

SAFE TO RUN MORE THAN ONCE, AND SAFE ON A SITE WITH NONE OF THIS DATA
-----------------------------------------------------------------------
Every name is existence-checked before anything happens to it, so a partial
failure can be re-run without erroring on rows already handled, and this is a
harmless no-op on any site that doesn't carry these specific rows (this data
lives on one site; the patch still runs everywhere one_bpmn is installed).
Deletion goes through frappe.delete_doc (never raw SQL), so every removed row
still gets Frappe's own Deleted Document audit record.
"""

import frappe

# Every name below was read individually and classified as an instruction echo,
# an exact or reworded duplicate of a row that stays, already expired, false, or
# (for 36jr4rba7k) a dead duplicate of a live row — never decided by a rule
# running here.
DELETE_NAMES = (
	"0r12pqv9jh", "0ranckontg", "0v7luj27hh", "12nrirc8bh", "13ak84viqt", "17ulqusmfv",
	"18sbo29h7p", "1bok0rl3fu", "22cucl5c02", "25e020kqop", "2bkg4kmis2", "2mvrjkcvjj",
	"2ravo72kcg", "35ursrlbd9", "36jr4rba7k", "390ssa9bin", "3b75ihr4ip", "3bjpuqmrpg",
	"3cfs4euuf2", "3dp3jmc8lh", "3ece5mudpd", "3fhcdpg8li", "3g62j8s960", "3l5bdvoahc",
	"3o8vkep9c3", "3t52jkkeit", "431b790fp6", "46flgn9k02", "46jjnji5gf", "47kfo1a4h0",
	"47kju14a95", "4abs0ij28s", "51ks1nfc8b", "56vhi5co7v", "5ap5rbrrfd", "5l6stmqngp",
	"5p7qpsd4fg", "5r1dv25d2v", "5s8pd8mhlj", "5t0ulrl6g7", "5v6gsce1ss", "60n3eoddi8",
	"619qdaj96n", "64lc39flej", "67d911gg76", "67qcphu0cq", "6a5777rmvf", "6btibiugtt",
	"6d01hud3mk", "6fhjva4lio", "6g72cmbv27", "6mb3b9nv8o", "6mofbm7s7m", "6nu2s64oh6",
	"6slvo8kutp", "6vq8t7qh9m", "73mujvj2cq", "74uhvbodu3", "781a6enj73", "78nbgb8pg0",
	"7avvq2akc7", "7di310f9jo", "7grmq64drq", "7jsn4ic2mj", "7nsmmirfna", "7rn2b26ui1",
	"83mng58njr", "87dorme9mq", "8admbjq907", "8f2u9b4c2m", "8fmolh8i1m", "8jm73c74so",
	"8n53cpveb7", "8vu73kje7i", "90p6ogfnqk", "93gpkrud5k", "97uui248iq", "9bn3rdncso",
	"9e9em59f31", "9indkrv4l4", "9m6k5jo92o", "9nfeh5t20c", "9nhcdfpnuu", "9qo6tgsq54",
	"9ri3ke6ost", "9v9bcgmiqj", "a055tdieme", "a06ihsisfs", "a3qbhijtcq", "a5fe1k939a",
	"ab3ve2nefm", "af2pqb9hur", "arlgj1jn4p", "articqi749", "b1v6ngkq03", "b5qds20h31",
	"bfpa1p2k06", "bjdtmq013f", "bmtfpsorlt", "bnag3dm1el", "bpd71m9qhu", "cj41makcak",
	"cuonm9s5uu", "d1dvoprq5b", "d2sno3bv1b", "d7k8mr7etd", "e5q5j0k46v", "e8m50jj7lp",
	"efhse1od1j", "efi5clrq7e", "eh2s11h3t3", "epei0s80id", "ertgulra8c", "f442el5qfc",
	"f5d5937pb4", "fed4uo0upf", "fi2hohg4e1", "g73iigac31", "ga3qa99ud9", "h77aso8d22",
	"hiuq4mnpha", "hmq9pcd4m4", "i3j714vjus", "i7app2hugj", "ib3suu6smc", "ica35nlq4g",
	"ik3shjjn0n", "irrt99nlsg", "ivd6aum4d1", "joal5ugdks", "jrrd68247k", "k4lv0vouev",
	"k7p39arsd3", "kaqchvdimt", "kb05fc8r09", "ke19iebvoo", "lc5bkl7gtg", "lfnq79kobq",
	"m466uea2bg", "m7q8v9ao2p", "mfqv1pn2bm", "miprg0kgbi", "nc1eo6u6dh", "ncf0v5celv",
	"nfvugfa7ah", "ng6adufmgg", "nhkesonrdm", "nvufvmno2m", "o0pdakq69i", "o3mvb8pqu8",
	"o55et1gpqn", "omjfj4ec05", "ov4ttsofoj", "p22bitjdh1", "p3limfh342", "p46t3f2bqo",
	"p5cibda7n9", "p7ek35pdv7", "p8i8l64bol", "qilsemrbva", "qndqvo5icn", "qq9gekd7ah",
	"rahh0qvbrt", "rdmgnrkssh", "rtp4q9m6p3", "s36pokqpnt", "t4fs8ri23h", "t6jnfolg10",
	"t8ldsm3hdv", "tij05rsp6h", "tl7uodaer9", "ubf86dc167", "uf6hm74pn1", "v2cklgljll",
	"v69obg28c9",
)

# The one row kept but corrected rather than deleted: the workflow rule (critical
# severity needs an approval step) is durable, the named individual it originally
# stored was not.
REWRITE = {
	"name": "eush7eer9d",
	"content": (
		"When severity is marked as critical, records require approval from a "
		"designated approver before submission, typically handled through "
		"workflow configuration."
	),
}


def execute():
	if not frappe.db.exists("DocType", "AI Memory"):
		return

	deleted, missing, failed = 0, 0, 0
	for name in DELETE_NAMES:
		if not frappe.db.exists("AI Memory", name):
			missing += 1
			continue
		try:
			# force=True: an AI Memory row is a leaf record nothing else links
			# to, so this is the same choice the doctype's own dedup-overwrite
			# already makes. Not delete_permanently, so the Deleted Document
			# audit record is still written.
			frappe.delete_doc("AI Memory", name, ignore_permissions=True, force=True)
			deleted += 1
		except Exception:
			failed += 1
			frappe.log_error(
				title="AI Memory cleanup: could not delete a reviewed row",
				message=f"name={name}\n{frappe.get_traceback()}",
			)

	rewritten = False
	if frappe.db.exists("AI Memory", REWRITE["name"]):
		try:
			doc = frappe.get_doc("AI Memory", REWRITE["name"])
			doc.content = REWRITE["content"]
			doc.save(ignore_permissions=True)
			rewritten = True
		except Exception:
			frappe.log_error(
				title=f"AI Memory cleanup: could not rewrite {REWRITE['name']}",
				message=frappe.get_traceback(),
			)

	frappe.db.commit()
	print(
		f"AI Memory cleanup: deleted {deleted}, already gone {missing}, "
		f"failed {failed} (of {len(DELETE_NAMES)} reviewed rows); "
		f"rewrote {'1' if rewritten else '0'}/1 flagged row"
	)
