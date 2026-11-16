const NUMBER_FORMAT = new Intl.NumberFormat("en-US");
const COST_FORMAT = new Intl.NumberFormat("en-US", {
	style: "currency",
	currency: "USD",
	minimumFractionDigits: 2,
	maximumFractionDigits: 4,
});

export function fmt(n) {
	return NUMBER_FORMAT.format(n || 0);
}

export function fmtCost(n) {
	return COST_FORMAT.format(n || 0);
}

export function round1(n) {
	return Math.round((Number(n) || 0) * 10) / 10;
}

export function runPill(status) {
	if (status === "Passed") return "bg-green-50 text-green-700";
	if (
		status === "Failed" ||
		status === "Error" ||
		status === "Timed Out" ||
		status === "Invalid"
	)
		return "bg-red-50 text-red-700";
	if (status === "Running") return "bg-yellow-50 text-yellow-700 animate-pulse";
	return "bg-gray-100 text-gray-500";
}

// Polyline points for the pass-rate sparkline in a 100 x 20 box; null when there is no line to draw.
export function sparklinePoints(values) {
	if (!values || values.length < 2) return null;
	const step = 100 / (values.length - 1);
	return values
		.map((v, i) => `${(i * step).toFixed(1)},${(20 - (v / 100) * 20).toFixed(1)}`)
		.join(" ");
}

// The state rides in the label so a Draft or disabled agent is chosen knowingly.
export function agentLabel(a) {
	const name = a.agent_name || a.name;
	const bits = [];
	if (a.lifecycle_status && a.lifecycle_status !== "Live") bits.push(a.lifecycle_status);
	if (a.enabled === 0) bits.push("disabled");
	return bits.length ? `${name} — ${bits.join(", ")}` : name;
}

// e.message is often just "<endpoint> PermissionError"; the useful text is in the server messages.
export function errorText(e, fallback) {
	const raw = e?.messages?.length ? e.messages.join(" ") : "";
	const exc = e?.exc_type && e?._error_message ? e._error_message : "";
	return raw || exc || e?.message || fallback;
}
