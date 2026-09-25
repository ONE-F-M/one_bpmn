// Pure helpers for the Cost Allocation tab, unit-tested in costAllocation.test.mjs.

export const OTHER_KEY = "__other__"
export const OTHER_COLOR = "#9ca3af"
const SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
// Series in the chart and slices in the donut before the tail folds into "Other".
export const MAX_SERIES = 6

// Chat users get five, so the chart shows the same "top 5" the scope line counts.
export function seriesCap(axis, groupBy) {
	return axis === "chat_user" && groupBy === "user" ? 5 : MAX_SERIES
}

export function subtitleOf(node, axis) {
	if (node.kind === "more") return `${node.count} not shown`
	if (node.kind !== "department") return ""
	return axis === "chat_user"
		? `${node.users} users · ${node.conversations} conversations`
		: `${node.owners} owners · ${node.processes} processes`
}

export function totalLabel(axis) {
	return `Total ${axis === "chat_user" ? "chat" : "process"} spend`
}

// The heaviest `cap` nodes stay; the rest fold into one "Other" entry that keeps their money.
export function foldTail(nodes, cap) {
	const top = nodes.slice(0, cap)
	const rest = nodes.slice(cap)
	if (!rest.length) return top
	const byBucket = {}
	for (const node of rest) {
		// The agents list behind the chat donut has no buckets.
		for (const [bucket, cost] of Object.entries(node.by_bucket || {})) {
			byBucket[bucket] = (byBucket[bucket] || 0) + cost
		}
	}
	const cost = rest.reduce((sum, node) => sum + node.cost, 0)
	return [...top, { key: OTHER_KEY, label: "Other", cost, by_bucket: byBucket }]
}

// A key keeps its remembered slot while it stays on screen; newcomers take the lowest free slot.
export function assignColors(keys, memo) {
	const taken = new Set()
	const out = { [OTHER_KEY]: OTHER_COLOR }
	for (const key of keys) {
		const slot = memo.get(key)
		if (slot !== undefined && !taken.has(slot)) {
			taken.add(slot)
			out[key] = SERIES_COLORS[slot]
		}
	}
	for (const key of keys.filter((k) => !(k in out))) {
		let slot = 0
		while (taken.has(slot)) slot += 1
		memo.set(key, slot)
		taken.add(slot)
		out[key] = SERIES_COLORS[slot]
	}
	return out
}

// The tree flattened to the rows on screen: children appear only under an open parent.
export function rowsOf(tree, expanded) {
	const out = []
	const walk = (nodes, depth, prefix, rootKey) => {
		for (const node of nodes) {
			const path = `${prefix}/${node.key || node.label}`
			const root = depth === 0 ? node.key : rootKey
			const hasChildren = node.children.length > 0
			const open = hasChildren && expanded.has(path)
			out.push({ path, depth, node, rootKey: root, hasChildren, open })
			if (open) walk(node.children, depth + 1, path, root)
		}
	}
	walk(tree, 0, "", "")
	return out
}

export function chevronOf(row) {
	return row.open ? "lucide:chevron-down" : "lucide:chevron-right"
}

export function toggleLabelOf(row) {
	return `Toggle ${row.node.label}`
}

export function indentOf(row, step) {
	return { paddingLeft: `${row.depth * step}px` }
}

export function pctChange(now, before) {
	return before ? ((now - before) / before) * 100 : null
}

// The AI Model list filtered to the unpriced models, where the rate cards get fixed.
export function pricingLink(models) {
	return `/app/ai-model?name=${encodeURIComponent(JSON.stringify(["in", models]))}`
}

export function bucketTotals(series, buckets) {
	return Object.fromEntries(buckets.map((b) => [b, series.reduce((sum, node) => sum + node.by_bucket[b], 0)]))
}

// The bucket holding today, if the range reaches today; it is still filling up.
export function currentBucket(buckets, toDate, today) {
	if (!buckets.length || today < buckets[0] || today > toDate) return null
	return [...buckets].reverse().find((b) => b <= today)
}

export function rankSlices(slices) {
	const sum = slices.reduce((total, s) => total + s.value, 0)
	return [...slices]
		.sort((a, b) => b.value - a.value)
		.map((s) => ({ ...s, pct: sum ? Math.round((s.value / sum) * 100) : 0 }))
}

// Chart tooltips are HTML; record names go in as text.
export function escapeHtml(text) {
	const el = document.createElement("div")
	el.textContent = text
	return el.innerHTML
}

// Share bars fill against the largest top-level node, so the biggest reads full width.
export function barWidth(node, tree) {
	const max = Math.max(...tree.map((n) => n.share))
	return max ? Math.min(100, (node.share / max) * 100) : 0
}

export function monthColumns(months) {
	return months.length >= 2 && months.length <= 6 ? months : []
}

export function nameOf(node) {
	return node.name || node.label
}

// Counts on a department row, the department on a top-level person or process row, nothing on an agent.
export function chipOf(row, axis) {
	if (row.node.kind === "department" || row.node.kind === "more") return subtitleOf(row.node, axis)
	return row.depth === 0 && row.node.kind !== "agent" ? row.node.department : ""
}
