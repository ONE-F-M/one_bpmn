<template>
	<div class="space-y-6">
		<!-- Toolbar. At phone width the axis toggle and Export take the first
		     row and the grouping toggle drops to its own. -->
		<div class="alloc-toolbar flex flex-wrap items-center gap-3">
			<TabButtons class="order-1" v-model="axis" :buttons="axisButtons" />
			<TabButtons
				class="order-3 w-full sm:order-2 sm:w-auto"
				v-model="groupBy"
				:buttons="groupButtons"
			/>
			<div class="order-2 ml-auto sm:order-3">
				<Dropdown :options="exportOptions" placement="right">
					<Button
						icon-left="download"
						icon-right="chevron-down"
						aria-label="Export"
						:disabled="!tree.length"
					>
						<!-- The label costs the row its fit at phone width. -->
						<span class="hidden sm:inline">Export</span>
					</Button>
				</Dropdown>
			</div>
		</div>

		<!-- Pricing gap warning -->
		<div
			v-if="missingPricing.length"
			class="bg-amber-50 text-amber-800 text-sm rounded-lg px-4 py-3"
		>
			<span class="font-medium">Cost may be under-reported.</span>
			{{ missingPricing.length }}
			{{ missingPricing.length === 1 ? "model" : "models" }} used in this period
			{{ missingPricing.length === 1 ? "has" : "have" }} no rate card, so
			{{ missingPricing.length === 1 ? "its" : "their" }} runs count as $0.00:
			<span class="font-mono text-xs">{{ missingPricing.join(", ") }}</span>
			<a class="underline ml-1" href="/app/ai-model" target="_blank">Add pricing on AI Model</a>
		</div>

		<!-- Tiles. Scoped to the selected axis, never the whole period — the
		     label says so, and the note below reports what is excluded. -->
		<div class="grid grid-cols-2 lg:grid-cols-6 gap-4">
			<div v-for="tile in tiles" :key="tile.label" class="bg-white rounded-lg shadow-sm p-4">
				<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">
					{{ tile.label }}
				</div>
				<div class="text-2xl font-bold text-gray-900 mt-1">{{ tile.value }}</div>
				<DeltaBadge v-if="tile.delta !== undefined" :delta="tile.delta" :note="priorLabel" />
				<div v-else-if="tile.note" class="text-xs text-gray-500 mt-1 truncate" :title="tile.note">
					{{ tile.note }}
				</div>
			</div>
		</div>

		<!-- What this axis leaves out, so the tiles are never read as the
		     period's whole AI spend. -->
		<div v-if="!loading && totals.cost !== periodTotals.cost" class="text-sm text-gray-500">
			{{ axis === "chat_user" ? "Chat runs" : "Process runs" }}:
			<span class="font-medium text-gray-700">{{ fmtCost(totals.cost) }}</span>
			of {{ fmtCost(periodTotals.cost) }} total AI spend this period.
			<template v-if="totals.other_axis_cost">
				{{ axis === "chat_user" ? "Process runs" : "Chat runs" }}
				{{ fmtCost(totals.other_axis_cost) }} are allocated under
				<button class="underline hover:text-gray-700" @click="toggleAxis">
					{{ otherAxisLabel }}</button>.
			</template>
		</div>

		<!-- Loading / empty -->
		<div v-if="loading" class="flex items-center justify-center h-48 text-gray-500">Loading…</div>
		<div v-else-if="!tree.length" class="flex flex-col items-center justify-center h-48 text-center">
			<Icon icon="lucide:receipt" class="w-12 h-12 text-gray-300 mb-3" />
			<h3 class="text-base font-medium text-gray-900">No usage in this period</h3>
			<p class="text-sm text-gray-500">Adjust the date range above.</p>
		</div>

		<template v-else>
			<!-- Charts -->
			<div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
				<div class="bg-white rounded-lg shadow-sm p-4 lg:col-span-2">
					<div class="flex items-baseline justify-between">
						<h3 class="text-sm font-medium text-gray-900">Cost by {{ groupLabel }}</h3>
						<span class="text-xs text-gray-500">{{ rangeLabel }}, {{ report.grain }}ly</span>
					</div>
					<div class="alloc-chart h-64">
						<AxisChart :config="barConfig" />
					</div>
				</div>
				<div class="bg-white rounded-lg shadow-sm p-4">
					<div class="flex items-baseline justify-between">
						<h3 class="text-sm font-medium text-gray-900">Share by {{ groupLabel }}</h3>
						<span class="text-xs text-gray-500">{{ fmtCost(totals.cost) }}</span>
					</div>
					<div class="alloc-chart h-64">
						<DonutChart :config="donutConfig" />
					</div>
				</div>
			</div>

			<!-- Phone: one stacked row per node, no sideways scrolling. -->
			<div class="sm:hidden divide-y divide-gray-100 border-t border-gray-200">
				<div
					v-for="row in visibleRows"
					:key="row.path"
					class="py-3 pr-1"
					:style="{ paddingLeft: `${row.depth * 16}px` }"
				>
					<div class="flex items-center gap-2">
						<button
							v-if="row.node.children.length"
							class="text-gray-400 p-1 -m-1"
							@click="toggle(row.path)"
						>
							<Icon
								:icon="expanded.has(row.path) ? 'lucide:chevron-down' : 'lucide:chevron-right'"
								class="w-4 h-4"
							/>
						</button>
						<span v-else class="w-4 shrink-0"></span>
						<span
							v-if="row.depth === 0"
							class="w-2 h-2 rounded-full shrink-0"
							:style="{ background: colorOf(row.node.key) }"
						></span>
						<span class="text-sm text-gray-900 truncate flex-1" :class="row.depth === 0 ? 'font-medium' : ''">
							{{ row.node.label }}
						</span>
						<span class="text-sm text-gray-900 font-medium">{{ fmtCost(row.node.cost) }}</span>
					</div>
					<div class="flex items-center gap-2 pl-6 mt-1 text-xs text-gray-500">
						<span>{{ Math.round(row.node.share) }}%</span>
						<DeltaBadge :delta="row.node.delta" />
						<span v-if="row.node.delta !== null">vs prior</span>
						<span v-if="subtitleOf(row.node)" class="truncate">· {{ subtitleOf(row.node) }}</span>
					</div>
				</div>
				<div class="py-3 flex items-start justify-between gap-3">
					<div>
						<div class="text-sm font-medium text-gray-900">
							Total {{ axis === "chat_user" ? "chat" : "process" }} spend
						</div>
						<div class="text-xs text-gray-500 mt-1">
							{{ fmtNum(totals.runs) }} runs · {{ fmtCompact(totals.tokens) }} tokens
						</div>
						<DeltaBadge :delta="costDelta" :note="priorLabel" />
					</div>
					<span class="text-sm font-bold text-gray-900">{{ fmtCost(totals.cost) }}</span>
				</div>
			</div>

			<!-- Table -->
			<div class="hidden sm:block overflow-x-auto">
				<table class="w-full">
					<thead>
						<tr class="border-b border-gray-200">
							<th class="text-left text-xs uppercase text-gray-500 font-medium py-2 px-3">
								{{ levelHeader }}
							</th>
							<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">Runs</th>
							<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">
								Tokens
							</th>
							<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">Cost ↓</th>
							<th class="text-left text-xs uppercase text-gray-500 font-medium py-2 px-3 w-40">
								Share
							</th>
							<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">Vs prior</th>
						</tr>
					</thead>
					<tbody>
						<tr
							v-for="row in visibleRows"
							:key="row.path"
							class="border-b border-gray-100 hover:bg-gray-50"
						>
							<td class="py-2.5 px-3 text-sm text-gray-900">
								<div class="flex items-center gap-2" :style="{ paddingLeft: `${row.depth * 20}px` }">
									<button
										v-if="row.node.children.length"
										class="text-gray-400 hover:text-gray-600"
										@click="toggle(row.path)"
									>
										<Icon
											:icon="expanded.has(row.path) ? 'lucide:chevron-down' : 'lucide:chevron-right'"
											class="w-4 h-4"
										/>
									</button>
									<span v-else class="w-4"></span>
									<span
										v-if="row.depth === 0"
										class="w-2 h-2 rounded-full shrink-0"
										:style="{ background: colorOf(row.node.key) }"
									></span>
									<Avatar
										v-if="row.node.kind === 'owner' || row.node.kind === 'user'"
										size="sm"
										:label="row.node.label"
									/>
									<div class="min-w-0">
										<div class="truncate" :class="row.depth === 0 ? 'font-medium' : ''">
											{{ row.node.label }}
										</div>
										<div v-if="subtitleOf(row.node)" class="text-xs text-gray-500 truncate">
											{{ subtitleOf(row.node) }}
										</div>
									</div>
								</div>
							</td>
							<td class="py-2.5 px-3 text-sm text-gray-600 text-right">{{ fmtNum(row.node.runs) }}</td>
							<td class="py-2.5 px-3 text-sm text-gray-600 text-right">
								{{ fmtCompact(row.node.tokens) }}
							</td>
							<td class="py-2.5 px-3 text-sm text-gray-900 text-right font-medium">
								{{ fmtCost(row.node.cost) }}
							</td>
							<td class="py-2.5 px-3">
								<div class="flex items-center gap-2">
									<div class="h-1.5 rounded-full bg-gray-100 flex-1 overflow-hidden">
										<div
											class="h-full rounded-full"
											:style="{ width: `${Math.min(row.node.share, 100)}%`, background: colorOf(row.rootKey) }"
										></div>
									</div>
									<span class="text-xs text-gray-500 w-10 text-right">{{ Math.round(row.node.share) }}%</span>
								</div>
							</td>
							<td class="py-2.5 px-3 text-right">
								<DeltaBadge :delta="row.node.delta" />
							</td>
						</tr>
					</tbody>
					<tfoot>
						<tr class="border-t-2 border-gray-200">
							<td class="py-2.5 px-3 text-xs uppercase text-gray-500 font-medium">
								Total {{ axis === "chat_user" ? "chat" : "process" }} spend
							</td>
							<td class="py-2.5 px-3 text-sm text-gray-900 text-right font-bold">{{ fmtNum(totals.runs) }}</td>
							<td class="py-2.5 px-3 text-sm text-gray-900 text-right font-bold">
								{{ fmtCompact(totals.tokens) }}
							</td>
							<td class="py-2.5 px-3 text-sm text-gray-900 text-right font-bold">{{ fmtCost(totals.cost) }}</td>
							<td class="py-2.5 px-3 text-xs text-gray-500">100%</td>
							<td class="py-2.5 px-3 text-right">
								<DeltaBadge :delta="costDelta" />
							</td>
						</tr>
					</tfoot>
				</table>
			</div>
		</template>
	</div>
</template>

<script setup>
import { ref, computed, watch, onMounted, h } from "vue"
import { frappeRequest, Avatar, AxisChart, Button, DonutChart, Dropdown, TabButtons } from "frappe-ui"
import { Icon } from "@iconify/vue"
import { dayjs } from "@/dayjs"

// Defaults keep the tab working whether or not the header passes the shared
// filters yet.
const props = defineProps({
	fromDate: { type: String, default: null },
	toDate: { type: String, default: null },
	origin: { type: String, default: "production" },
	model: { type: String, default: null },
	provider: { type: String, default: null },
	processModel: { type: String, default: null },
})

// Slot order is fixed and assigned by key, so filtering the period out of a
// department never repaints the ones that remain.
const SERIES_COLORS = [
	"#2a78d6", "#eb6834", "#1baf7a", "#eda100",
	"#e87ba4", "#008300", "#4a3aa7", "#e34948",
]
const OTHER_COLOR = "#9ca3af"

const axis = ref("process_owner")
const groupBy = ref("department")
const loading = ref(true)
const report = ref({})

// A phone row fits the toggles and Export only without the "By" prefix.
const isPhone = ref(window.matchMedia("(max-width: 639px)").matches)
window.matchMedia("(max-width: 639px)").addEventListener("change", (e) => {
	isPhone.value = e.matches
})
function toggleLabel(text) {
	return isPhone.value ? text[0].toUpperCase() + text.slice(1) : `By ${text}`
}

const axisButtons = computed(() => [
	{ label: toggleLabel("process owner"), value: "process_owner" },
	{ label: toggleLabel("chat user"), value: "chat_user" },
])

const groupButtons = computed(() =>
	(axis.value === "chat_user"
		? ["department", "user", "agent"]
		: ["department", "owner", "process"]
	).map((value) => ({ label: toggleLabel(value), value }))
)

const tree = computed(() => report.value.tree || [])
const totals = computed(() => report.value.totals || { runs: 0, tokens: 0, cost: 0 })
const periodTotals = computed(() => report.value.period_totals || { runs: 0, tokens: 0, cost: 0 })
const previous = computed(() => report.value.previous || { runs: 0, tokens: 0, cost: 0 })
const missingPricing = computed(() => report.value.models_missing_pricing || [])

const otherAxisLabel = computed(() =>
	axis.value === "chat_user" ? "By process owner" : "By chat user"
)
const groupLabel = computed(() => groupBy.value)
const levelHeader = computed(() =>
	groupButtons.value
		.slice(groupButtons.value.findIndex((b) => b.value === groupBy.value))
		.map((b) => b.value)
		.join(" / ")
		.toUpperCase()
)
const priorLabel = computed(() => {
	const p = previous.value
	if (!p.from_date) return ""
	const from = dayjs(p.from_date)
	const to = dayjs(p.to_date)
	// Tiles are narrow; the month is only worth repeating when it changes.
	const end = from.isSame(to, "month") ? to.format("D") : to.format("MMM D")
	return `vs ${from.format("MMM D")} – ${end}`
})
const rangeLabel = computed(() =>
	report.value.from_date
		? `${fmtDay(report.value.from_date)} – ${fmtDay(report.value.to_date)}`
		: ""
)

function ratio(now, before) {
	return before ? (now - before) / before : null
}
const costDelta = computed(() => ratio(totals.value.cost, previous.value.cost))

const tiles = computed(() => {
	const t = totals.value
	const p = previous.value
	const avgNow = t.runs ? t.cost / t.runs : 0
	const avgBefore = p.runs ? p.cost / p.runs : 0
	const isChat = axis.value === "chat_user"
	return [
		{ label: isChat ? "Chat spend" : "Process spend", value: fmtCost(t.cost), delta: costDelta.value },
		{ label: "Runs", value: fmtNum(t.runs), delta: ratio(t.runs, p.runs) },
		{ label: "Tokens", value: fmtCompact(t.tokens), delta: ratio(t.tokens, p.tokens) },
		{ label: "Avg cost / run", value: fmtCost(avgNow), delta: ratio(avgNow, avgBefore) },
		{
			label: "Departments",
			value: fmtNum(t.departments),
			note: isChat
				? `${fmtNum(t.active_users || 0)} of ${fmtNum(t.seats || 0)} seats active`
				: `${fmtNum(t.people || 0)} process owners`,
		},
		isChat
			? { label: "Conversations", value: fmtNum(t.conversations || 0), note: `${fmtCost(t.avg_cost_per_conversation || 0)} each` }
			: { label: "Processes", value: fmtNum(t.processes || 0), note: t.top_process ? `Top: ${t.top_process}` : "" },
	]
})

// -- colours -----------------------------------------------------------
// Assigned over the keys in a stable order, not by cost, so a node keeps its
// colour across the chart, the donut and the table's share bars.
const colorByKey = computed(() => {
	const keys = tree.value.map((n) => n.key).sort()
	return Object.fromEntries(
		keys.map((key, i) => [key, i < SERIES_COLORS.length ? SERIES_COLORS[i] : OTHER_COLOR])
	)
})
function colorOf(key) {
	return colorByKey.value[key] || OTHER_COLOR
}

// Past eight slots the tail folds into one "Other" series rather than being
// handed a made-up colour.
const charted = computed(() => {
	const keys = new Set(Object.entries(colorByKey.value)
		.filter(([, color]) => color !== OTHER_COLOR).map(([key]) => key))
	return tree.value.filter((n) => keys.has(n.key))
})
const otherNodes = computed(() => tree.value.filter((n) => !charted.value.includes(n)))

const barConfig = computed(() => {
	const buckets = report.value.buckets || []
	const data = buckets.map((bucket, i) => {
		const row = { bucket: bucketLabel(bucket, buckets[i + 1]) }
		for (const node of charted.value) row[node.label] = node.by_bucket?.[bucket] || 0
		if (otherNodes.value.length) {
			row.Other = otherNodes.value.reduce((sum, n) => sum + (n.by_bucket?.[bucket] || 0), 0)
		}
		return row
	})
	const series = charted.value.map((node) => ({
		name: node.label,
		type: "bar",
		stackName: "cost",
		color: colorOf(node.key),
		// A 2px surface gap keeps neighbouring segments readable.
		echartOptions: { itemStyle: { borderColor: "#ffffff", borderWidth: 2 } },
	}))
	if (otherNodes.value.length) {
		series.push({
			name: "Other", type: "bar", stackName: "cost", color: OTHER_COLOR,
			echartOptions: { itemStyle: { borderColor: "#ffffff", borderWidth: 2 } },
		})
	}
	return {
		data,
		title: "",
		xAxis: { key: "bucket", type: "category" },
		yAxis: { title: "Cost" },
		stacked: true,
		series,
	}
})

const donutConfig = computed(() => {
	const slices = charted.value.map((node) => ({ label: node.label, value: node.cost, key: node.key }))
	if (otherNodes.value.length) {
		slices.push({
			label: "Other",
			value: otherNodes.value.reduce((sum, n) => sum + n.cost, 0),
			key: "",
		})
	}
	// The donut sorts its slices by value and applies colours in that order, so
	// the colours are handed over in the same order to stay on their entity.
	slices.sort((a, b) => b.value - a.value)
	return {
		data: slices,
		title: "",
		categoryColumn: "label",
		valueColumn: "value",
		colors: slices.map((s) => (s.key ? colorOf(s.key) : OTHER_COLOR)),
	}
})

// -- table -------------------------------------------------------------
const expanded = ref(new Set())
function toggle(path) {
	const next = new Set(expanded.value)
	next.has(path) ? next.delete(path) : next.add(path)
	expanded.value = next
}

const visibleRows = computed(() => {
	const rows = []
	const walk = (nodes, depth, prefix, rootKey) => {
		for (const node of nodes) {
			const path = `${prefix}/${node.key || node.label}`
			rows.push({ path, depth, node, rootKey: depth === 0 ? node.key : rootKey })
			if (node.children.length && expanded.value.has(path)) {
				walk(node.children, depth + 1, path, depth === 0 ? node.key : rootKey)
			}
		}
	}
	walk(tree.value, 0, "", "")
	return rows
})

function subtitleOf(node) {
	if (node.kind === "more") return `${node.count} not shown`
	if (node.kind === "department") {
		return axis.value === "chat_user"
			? `${node.users} users · ${node.conversations} conversations`
			: `${node.owners} owners · ${node.processes} processes`
	}
	return ""
}

// -- formatting --------------------------------------------------------
const _num = new Intl.NumberFormat("en-US")
const _compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 })
const _cost = new Intl.NumberFormat("en-US", {
	style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 4,
})
function fmtNum(n) { return _num.format(n || 0) }
function fmtCompact(n) { return _compact.format(n || 0) }
function fmtCost(n) { return _cost.format(n || 0) }
function fmtDay(d) { return dayjs(d).format("MMM D") }
function bucketLabel(start, next) {
	if (report.value.grain === "month") return dayjs(start).format("MMM YYYY")
	const end = next ? dayjs(next).subtract(1, "day") : dayjs(report.value.to_date)
	return `${dayjs(start).format("MMM D")} – ${end.format("D")}`
}

const DeltaBadge = (p) => {
	if (p.delta === null || p.delta === undefined) {
		return h("div", { class: "text-xs text-gray-400 mt-1" }, p.note ? "—" : "")
	}
	const pct = Math.round(p.delta * 100)
	const tone = pct > 0 ? "bg-red-50 text-red-600" : pct < 0 ? "bg-green-50 text-green-700" : "bg-gray-100 text-gray-500"
	return h("div", { class: `inline-flex items-center gap-1.5 mt-1 ${p.note ? "flex-wrap" : ""}` }, [
		h("span", { class: `text-xs px-1.5 py-0.5 rounded ${tone}` }, `${pct > 0 ? "+" : ""}${pct}%`),
		p.note ? h("span", { class: "text-xs text-gray-400 whitespace-nowrap" }, p.note) : null,
	])
}
DeltaBadge.props = ["delta", "note"]

// -- data --------------------------------------------------------------
function toggleAxis() {
	axis.value = axis.value === "chat_user" ? "process_owner" : "chat_user"
}

function queryParams(extra = {}) {
	return {
		axis: axis.value,
		group_by: groupBy.value,
		origin: props.origin,
		...(props.fromDate ? { from_date: props.fromDate } : {}),
		...(props.toDate ? { to_date: props.toDate } : {}),
		...(props.model ? { model: props.model } : {}),
		...(props.provider ? { provider: props.provider } : {}),
		...(props.processModel ? { process_model: props.processModel } : {}),
		...extra,
	}
}

// Export goes through a normal browser navigation: the endpoint replies with a
// file download, which fetch/frappeRequest can't hand to the user.
function download(fmt) {
	const params = new URLSearchParams(queryParams({ fmt }))
	window.open(
		`/api/method/one_bpmn.api.insights_api.export_cost_allocation?${params.toString()}`,
		"_blank"
	)
}

const exportOptions = computed(() => [
	{ label: "XLSX", icon: "file-spreadsheet", onClick: () => download("xlsx") },
	{ label: "CSV", icon: "file-text", onClick: () => download("csv") },
])

async function fetchReport() {
	loading.value = true
	try {
		report.value = await frappeRequest({
			url: "/api/method/one_bpmn.api.insights_api.get_cost_allocation",
			method: "POST",
			params: queryParams(),
		})
		const top = report.value.tree?.[0]
		expanded.value = new Set(top ? [`/${top.key || top.label}`] : [])
	} catch (e) {
		console.error("Failed to fetch cost allocation:", e)
		report.value = {}
	} finally {
		loading.value = false
	}
}

// The grouping options differ per axis, so switching axis resets the grouping
// rather than asking for one the other axis does not have.
watch(axis, () => {
	groupBy.value = "department"
})
watch(
	() => [props.fromDate, props.toDate, props.origin, props.model, props.provider,
	       props.processModel, axis.value, groupBy.value],
	fetchReport
)
onMounted(fetchReport)
</script>

<style scoped>
/* Touch targets at phone width: the shared toggles are 28px by default. */
@media (max-width: 639px) {
	.alloc-toolbar :deep([role="radiogroup"] > div),
	.alloc-toolbar :deep(button) {
		min-height: 36px;
	}
	.alloc-toolbar :deep([role="radiogroup"] > div > div) {
		flex: 1;
	}
}
/* The shared chart wrapper carries a 300px floor that overflows a phone. */
.alloc-chart :deep(div) {
	min-width: 0;
	min-height: 0;
}
</style>
