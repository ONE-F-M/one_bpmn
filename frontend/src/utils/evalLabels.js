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
	{ label: "Tool artifact", value: "tool_artifact" },
	{ label: "Skill in prompt", value: "skill_in_prompt" },
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

// What an assertion's value means depends on its type, so the field says which.
export const VALUE_LABELS = {
	llm_judge: "Rubric",
	max_tokens: "Token ceiling",
	no_tool_call: "Forbidden tool names",
	tool_calls: "Order mode",
	tool_artifact: "Artifact check (JSON)",
	skill_in_prompt: "Skill name",
}

export const CASE_TYPE_OPTIONS = [
	"Output", "Trajectory", "Trigger Positive", "Trigger Negative",
	"Adversarial", "Co-Load Budget", "Memory",
].map((t) => ({ label: t, value: t }))

export const CI_ROLE_OPTIONS = [
	{ label: "Only when asked", value: "" },
	{ label: "Smoke", value: "Smoke" },
	{ label: "Nightly", value: "Nightly" },
]

export const DATASET_SCOPES = [
	{ label: "This suite", value: "suite" },
	{ label: "The whole agent", value: "agent" },
]

export const PAGE_SIZES = [25, 50, 100].map((n) => ({ label: String(n), value: n }))

export const assertionTypeLabel = label(ASSERTION_TYPES)
export const toolCallModeLabel = label(TOOL_CALL_MODES)
