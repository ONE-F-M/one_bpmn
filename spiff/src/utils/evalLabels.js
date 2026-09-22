// What the eval screens call things, in one place. The value is what the
// runner and the doctype store; the label is what a person reads — in the suite
// editor's dropdowns and chips and in the run review alike, so they cannot drift.

export const ASSERTION_TYPES = [
	{ label: "Contains", value: "contains" },
	{ label: "Regex", value: "regex" },
	{ label: "Equals", value: "equals" },
	{ label: "Schema valid", value: "schema_valid" },
	{ label: "LLM judge", value: "llm_judge" },
	{ label: "Max tokens", value: "max_tokens" },
	{ label: "No tool call", value: "no_tool_call" },
	{ label: "Tool calls", value: "tool_calls" },
]

// The three ways a tool_calls assertion reads a trace.
export const TOOL_CALL_MODES = [
	{ label: "Exact", value: "EXACT" },
	{ label: "In Order", value: "IN_ORDER" },
	{ label: "Any Order", value: "ANY_ORDER" },
]

// How an expected tool call's argument is compared.
export const MATCHERS = [
	{ label: "Equals", value: "equals" },
	{ label: "Regex", value: "regex" },
	{ label: "Contains", value: "contains" },
]

const label = (list) => (value) => list.find((m) => m.value === value)?.label || value

export const assertionTypeLabel = label(ASSERTION_TYPES)
export const toolCallModeLabel = label(TOOL_CALL_MODES)
