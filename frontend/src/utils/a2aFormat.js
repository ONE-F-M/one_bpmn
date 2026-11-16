const TERMINAL_STATES = ["completed", "canceled", "failed", "rejected", "timed-out"];

// Same wording the escalation notification uses for each limit.
const LIMIT_LABELS = {
	max_recursion_depth: "nesting depth",
	max_task_handoffs: "hand-offs between agents",
	delegation_deadline_minutes: "time allowed",
	turn_cap: "tool-calling turns",
	max_delegation_retries: "retries",
};

export function ordinal(n) {
	const lastTwo = n % 100;
	if (lastTwo >= 11 && lastTwo <= 13) return `${n}th`;
	return `${n}${{ 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th"}`;
}

export function describeAgo(seconds) {
	const s = Number(seconds || 0);
	if (s < 90) return `${Math.round(s)}s`;
	if (s < 5400) return `${Math.round(s / 60)} minutes`;
	return `${(s / 3600).toFixed(1)} hours`;
}

export function limitLabel(reason) {
	return LIMIT_LABELS[reason] || reason;
}

export function isTerminal(state) {
	return TERMINAL_STATES.includes(state);
}

export function statusTheme(status) {
	if (status === "Approved") return "green";
	if (status === "Revoked") return "red";
	return "gray";
}

export function stateTheme(state) {
	if (state === "completed") return "green";
	if (["failed", "timed-out", "rejected"].includes(state)) return "red";
	if (state === "input-required") return "orange";
	if (state === "canceled") return "gray";
	return "blue";
}

export function directionTheme(direction) {
	if (direction === "Inbound") return "blue";
	if (direction === "Outbound") return "green";
	return "gray";
}

export function delegationTheme(status) {
	if (status === "Completed") return "green";
	if (status === "Failed") return "red";
	if (status === "Needs Review") return "orange";
	if (status === "In Progress") return "blue";
	return "gray";
}

export function clarificationTheme(row) {
	if (!row) return "gray";
	if (row.status === "Answered") return "green";
	if (row.status === "Escalated") return "red";
	if (row.status === "Abandoned") return "gray";
	return row.escalated_at ? "red" : "orange";
}

export function clarificationLabel(row) {
	if (!row) return "";
	if (row.status !== "Awaiting Answer") return row.status;
	if (row.escalated_at) return "Escalated";
	if (row.reminded_at) return "Reminded";
	return "Awaiting answer";
}

export function taskBrief(task) {
	try {
		const payload = JSON.parse(task.request_payload || "{}");
		return payload.instruction || payload.text || "";
	} catch {
		return task.request_payload || "";
	}
}

export function initiator(task) {
	return task.delegated_by || task.client || task.remote_agent || "—";
}
