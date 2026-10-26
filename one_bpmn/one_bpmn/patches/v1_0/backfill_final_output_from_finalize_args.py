"""WI-002187: recover final_output for Success runs the old loop left empty.

Before this story, a run's final_output came from the model's own narration on
the closing turn — and a turn that ended with a finalize call routinely had
none: the real answer sat in that call's "response" argument the whole time
(LuCrusher run foac1717np: 1,504 chars there, "" on the run). The new loop
reads finalize's arguments directly going forward; this recovers the August
runs that already finished under the old behaviour, from the AI Agent Tool
Call rows their Steps already recorded.

Only "finalize" is checked — the terminal tool every affected agent (Logix,
LuCrusher, Docu) actually used; a shape-specific aiTerminalTools name would
need its own pass, and none of the affected runs used one.
"""

import json

import frappe


def execute():
	frappe.reload_doc("one_bpmn", "doctype", "ai_agent_run")

	runs = frappe.db.sql(
		"""
		select name from `tabAI Agent Run`
		where status = 'Success'
		  and ifnull(final_output, '') = ''
		  and started_at >= '2026-08-01' and started_at < '2026-09-01'
		""",
		as_dict=True,
	)

	fixed = 0
	for run in runs:
		call = frappe.db.sql(
			"""
			select tc.tool_args
			from `tabAI Agent Tool Call` tc
			join `tabAI Agent Step` s on tc.parent = s.name
			where s.run = %s and tc.tool_name = 'finalize'
			order by s.step_index desc
			limit 1
			""",
			(run.name,),
			as_dict=True,
		)
		if not call or not call[0].tool_args:
			continue
		try:
			args = json.loads(call[0].tool_args)
		except (TypeError, ValueError):
			continue
		reply = args.get("response") if isinstance(args, dict) else None
		if not reply:
			reply = json.dumps(args, default=str)
		frappe.db.set_value(
			"AI Agent Run",
			run.name,
			{"final_output": reply, "no_terminal_tool": 0},
			update_modified=False,
		)
		fixed += 1

	frappe.db.commit()
	frappe.logger("one_bpmn").info(
		f"WI-002187 backfill: filled final_output on {fixed} of {len(runs)} empty August Success runs"
	)
