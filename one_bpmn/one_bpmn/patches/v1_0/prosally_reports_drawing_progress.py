"""ProsAlly tells the person waiting which part of a drawing it is on, instead of going quiet for minutes.

Edits the Generate Process and Modify Process scripts in place. One already carrying the change is skipped, and one
whose anchors are not each found exactly once is logged and left as it is.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.prosally_scope_modify_to_subprocess import apply_edits

ATTEMPT = "for attempt in range(_MAX_FIX_PASSES + 1):\n    if attempt == 0:\n        prompt = initial_prompt\n"
GENERATE_ATTEMPT = (
	ATTEMPT,
	'''for attempt in range(_MAX_FIX_PASSES + 1):
    from one_bpmn.agents import turn_signal
    turn_signal.publish_progress("Drawing the process" if attempt == 0 else "Checking the drawing, pass " + str(attempt))
    if attempt == 0:
        prompt = initial_prompt
''',
)
MODIFY_ATTEMPT = (
	ATTEMPT,
	'''for attempt in range(_MAX_FIX_PASSES + 1):
    from one_bpmn.agents import turn_signal
    turn_signal.publish_progress("Updating the diagram" if attempt == 0 else "Checking the result, pass " + str(attempt))
    if attempt == 0:
        prompt = initial_prompt
''',
)
GENERATE_OUTLINE = (
	"        # Too large for one completion: outline it into phases, then generate\n",
	'''        from one_bpmn.agents import turn_signal
        turn_signal.publish_progress("Planning the drawing in parts")
        # Too large for one completion: outline it into phases, then generate
''',
)
GENERATE_PHASE = (
	"            _pi += 1\n            _phase = _phases[_pi]\n",
	'''            _pi += 1
            _phase = _phases[_pi]
            from one_bpmn.agents import turn_signal
            turn_signal.publish_progress("Drawing part " + str(_pi + 1) + " of " + str(len(_phases)) + ": " + _phase.get("name", ""), _pi + 1, len(_phases))
''',
)

# Server Script name pattern -> (edits, marker of an applied change).
SCRIPTS = {
	"ProsAlly%Tool Generate Process": ((GENERATE_ATTEMPT, GENERATE_OUTLINE, GENERATE_PHASE), "publish_progress("),
	"ProsAlly%Tool Modify Process": ((MODIFY_ATTEMPT,), "publish_progress("),
}


def execute():
	for pattern, (edits, marker) in SCRIPTS.items():
		name = frappe.db.get_value("Server Script", {"name": ["like", pattern]}, "name")
		if name:
			apply_edits("Server Script", name, "script", edits, marker)
