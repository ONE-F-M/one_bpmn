// The three ways a tool_calls assertion reads a trace. The value is what the
// runner matches on; the label is what a person sees, in both the suite editor
// and the run review — one list so the two never drift.
export const TOOL_CALL_MODES = [
	{ label: "Exact", value: "EXACT" },
	{ label: "In Order", value: "IN_ORDER" },
	{ label: "Any Order", value: "ANY_ORDER" },
]

export function toolCallModeLabel(value) {
	return TOOL_CALL_MODES.find((m) => m.value === value)?.label || value
}
