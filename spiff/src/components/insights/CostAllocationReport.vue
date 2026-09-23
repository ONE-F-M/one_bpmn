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
		<Alert v-if="missingPricing.length" title="Cost may be under-reported" type="warning">
			<span class="text-sm">
				{{ missingPricing.length }}
				{{ missingPricing.length === 1 ? "model" : "models" }} used in this period
				{{ missingPricing.length === 1 ? "has" : "have" }} no rate card, so
				{{ missingPricing.length === 1 ? "its" : "their" }} runs count as $0.00:
			</span>
			<span
				v-for="m in missingPricing"
				:key="m"
				class="inline-block font-mono text-xs bg-white/70 rounded px-1.5 py-0.5 ml-1"
			>{{ m }}</span>
			<template #actions>
				<a class="text-sm underline whitespace-nowrap" :href="pricingLink" target="_blank">
					Add pricing on AI Model
				</a>
			</template>
		</Alert>

		<!-- API failure: one message and a way back, in place of everything else. -->
		<div v-if="error" class="flex flex-col items-center justify-center h-48 text-center gap-3">
			<ErrorMessage :message="error" />
			<Button @click="fetchReport">Retry</Button>
		</div>

		<template v-else>

		<!-- Tiles. Scoped to the selected axis, never the whole period — the
		     label says so, and the note below reports what is excluded. -->
		<div class="grid grid-cols-2 lg:grid-cols-6 gap-4">
			<div v-for="tile in tiles" :key="tile.label" class="bg-white rounded-lg shadow-sm p-4">
				<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">
					{{ isPhone && tile.short ? tile.short : tile.label }}
				</div>
				<div class="text-xl sm:text-2xl font-bold text-gray-900 mt-1 whitespace-nowrap">{{ tile.value }}</div>
				<DeltaBadge
					v-if="tile.delta !== undefined"
					:delta="tile.delta"
					:note="tile.note || priorLabel"
					:good-direction="tile.goodDirection"
					:absolute="tile.absolute"
				/>
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
				<a href="#" class="underline hover:text-gray-700" @click.prevent="toggleAxis">
					{{ otherAxisLabel }}</a>.
			</template>
			<template v-if="axis === 'chat_user' && totals.top5_share">
				Top 5 users account for
				<span class="font-medium text-gray-700">{{ Math.round(totals.top5_share) }}%</span>
				of chat spend.
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
				<div class="bg-white rounded-lg shadow-sm p-2 sm:p-4 lg:col-span-2">
					<div class="alloc-chart" :style="{ height: `${chartHeight}px` }">
						<AxisChart :config="barConfig" />
					</div>
				</div>
				<!-- The donut repeats the table's share column; at phone width the
				     table alone carries it. -->
				<div class="hidden sm:block bg-white rounded-lg shadow-sm p-4">
					<div class="alloc-chart h-[230px]">
						<ECharts :options="donutOptions" />
					</div>
				</div>
			</div>

			<!-- Phone: nested cards, no sideways scrolling. -->
			<div class="sm:hidden divide-y divide-gray-100 border-t border-gray-200">
				<div
					v-for="row in visibleRows"
					:key="row.path"
					class="py-3 pr-1"
					:class="row.node.children.length ? 'cursor-pointer' : ''"
					:style="{ paddingLeft: `${row.depth * 16}px` }"
					@click="row.node.children.length && toggle(row.path)"
				>
					<div class="flex items-center gap-2">
						<Icon
							v-if="row.node.children.length"
							:icon="expanded.has(row.path) ? 'lucide:chevron-down' : 'lucide:chevron-right'"
							class="w-4 h-4 text-gray-400 shrink-0"
						/>
						<span v-else class="w-4 shrink-0"></span>
						<span
							v-if="row.depth === 0"
							class="w-2 h-2 rounded-full shrink-0"
							:style="{ background: colorOf(row.node.key) }"
						></span>
						<span class="text-sm text-gray-900 truncate flex-1" :class="row.depth === 0 ? 'font-medium' : ''">
							{{ row.node.name || row.node.label }}
						</span>
						<span class="text-sm text-gray-900 whitespace-nowrap" :class="row.depth === 0 ? 'font-medium' : ''">
							{{ fmtCost(row.node.cost) }}
						</span>
					</div>
					<div v-if="row.depth === 0" class="flex items-center gap-2 pl-6 mt-1.5">
						<div class="h-1.5 rounded-full bg-gray-100 flex-1 overflow-hidden">
							<div
								class="h-full rounded-full"
								:style="{ width: `${barWidth(row.node)}%`, background: colorOf(row.node.key) }"
							></div>
						</div>
						<span class="text-xs text-gray-500 w-8 text-right">{{ Math.round(row.node.share) }}%</span>
						<DeltaBadge :delta="row.node.delta" />
					</div>
					<div v-else-if="row.depth === 1" class="pl-6 mt-0.5 text-xs text-gray-500">
						{{ Math.round(row.node.share) }}% of {{ axis === "chat_user" ? "chat" : "process" }} spend
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
					<span class="text-sm font-bold text-gray-900 whitespace-nowrap">{{ fmtCost(totals.cost) }}</span>
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
							<th
								v-for="m in monthColumns"
								:key="m"
								class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3 whitespace-nowrap"
							>
								{{ monthHeader(m) }}
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
							:class="row.node.children.length ? 'cursor-pointer' : ''"
							@click="row.node.children.length && toggle(row.path)"
						>
							<td class="py-2.5 px-3 text-sm text-gray-900">
								<div class="flex items-center gap-2" :style="{ paddingLeft: `${row.depth * 20}px` }">
									<Icon
										v-if="row.node.children.length"
										:icon="expanded.has(row.path) ? 'lucide:chevron-down' : 'lucide:chevron-right'"
										class="w-4 h-4 text-gray-400 shrink-0"
									/>
									<span v-else class="w-4 shrink-0"></span>
									<span
										v-if="row.depth === 0"
										class="w-2 h-2 rounded-full shrink-0"
										:style="{ background: colorOf(row.node.key) }"
									></span>
									<Avatar
										v-if="row.node.kind === 'owner' || row.node.kind === 'user'"
										size="sm"
										:label="row.node.name || row.node.label"
									/>
									<span class="truncate" :class="row.depth === 0 ? 'font-medium' : ''">
										{{ row.node.name || row.node.label }}
									</span>
									<span
										v-if="row.node.name"
										class="text-xs text-gray-500 truncate hidden md:inline"
									>{{ row.node.label }}</span>
									<Badge
										v-if="row.node.kind === 'department' && subtitleOf(row.node)"
										size="sm"
										:label="subtitleOf(row.node)"
									/>
									<!-- An agent serves every department; only people and processes have one. -->
									<Badge
										v-else-if="row.depth === 0 && row.node.department && row.node.kind !== 'agent'"
										size="sm"
										:label="row.node.department"
									/>
									<Badge
										v-else-if="row.node.kind === 'more'"
										size="sm"
										:label="subtitleOf(row.node)"
									/>
								</div>
							</td>
							<td class="py-2.5 px-3 text-sm text-gray-600 text-right">{{ fmtNum(row.node.runs) }}</td>
							<td class="py-2.5 px-3 text-sm text-gray-600 text-right">
								{{ fmtCompact(row.node.tokens) }}
							</td>
							<td
								v-for="m in monthColumns"
								:key="m"
								class="py-2.5 px-3 text-sm text-gray-600 text-right"
							>
								{{ row.node.by_month?.[m] ? fmtCost(row.node.by_month[m]) : "—" }}
							</td>
							<td class="py-2.5 px-3 text-sm text-gray-900 text-right font-medium">
								{{ fmtCost(row.node.cost) }}
							</td>
							<td class="py-2.5 px-3">
								<div class="flex items-center gap-2">
									<div class="h-1.5 rounded-full bg-gray-100 flex-1 overflow-hidden">
										<div
											class="h-full rounded-full"
											:style="{ width: `${barWidth(row.node)}%`, background: colorOf(row.rootKey) }"
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
							<td
								v-for="m in monthColumns"
								:key="m"
								class="py-2.5 px-3 text-sm text-gray-900 text-right font-bold"
							>
								{{ fmtCost(monthTotal(m)) }}
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
		</template>
	</div>
</template>

<script setup>
import { ref, computed, watch, onMounted, h } from "vue"
import {
	frappeRequest, Alert, Avatar, AxisChart, Badge, Button, Dropdown, ECharts, ErrorMessage, TabButtons,
} from "frappe-ui"
import { Icon } from "@iconify/vue"
import { dayjs } from "@/dayjs"
import { fmtCompact, fmtCost, fmtNum } from "@/utils/runFormat"

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
// Slots in play before the tail folds into "Other", in the bar and the donut alike.
const MAX_SERIES = 6

const axis = ref("process_owner")
const groupBy = ref("department")
const loading = ref(true)
const error = ref(null)
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
const pricingLink = computed(
	() => `/app/ai-model?name=${encodeURIComponent(JSON.stringify(["in", missingPricing.value]))}`
)

const otherAxisLabel = computed(() =>
	axis.value === "chat_user" ? "By process owner" : "By chat user"
)
const groupLabel = computed(() => groupBy.value)
// The levels under each grouping, in the order the tree nests them — the same
// table the endpoint uses.
const LEVELS = {
	department: ["department", "owner", "process"], owner: ["owner", "process"], process: ["process", "owner"],
	user: ["user", "agent"], agent: ["agent", "user"],
}
const levelHeader = computed(() => {
	const levels = groupBy.value === "department" && axis.value === "chat_user"
		? ["department", "user", "agent"]
		: LEVELS[groupBy.value] || [groupBy.value]
	return levels.join(" / ").toUpperCase()
})
const priorLabel = computed(() => {
	const p = previous.value
	if (!p.from_date) return ""
	const from = dayjs(p.from_date)
	const to = dayjs(p.to_date)
	// Tiles are narrow; the month is only worth repeating when it changes.
	const end = from.isSame(to, "month") ? to.format("D") : to.format("MMM D")
	return `${isPhone.value ? "" : "vs "}${from.format("MMM D")} – ${end}`
})
const rangeLabel = computed(() =>
	report.value.from_date
		? `${fmtDay(report.value.from_date)} – ${fmtDay(report.value.to_date)}`
		: ""
)

// Distinct departments and owners in the tree, whichever level they sit at.
const departmentCount = computed(() => new Set(tree.value.map((n) => n.department).filter(Boolean)).size)
const ownerCount = computed(() => {
	const owners = new Set()
	const walk = (nodes) => nodes.forEach((n) => {
		if (n.kind === "owner" && n.key) owners.add(n.key)
		walk(n.children || [])
	})
	walk(tree.value)
	return owners.size
})

function ratio(now, before) {
	return before ? (now - before) / before : null
}
const costDelta = computed(() => ratio(totals.value.cost, previous.value.cost))

// The department with the most spend and its share, whatever the grouping:
// department nodes when they exist, else the top-level nodes folded by department.
const topDepartment = computed(() => {
	const byDept = {}
	for (const n of tree.value) {
		const key = n.kind === "department" ? n.label : n.department
		if (key) byDept[key] = (byDept[key] || 0) + n.cost
	}
	const [name, cost] = Object.entries(byDept).sort((a, b) => b[1] - a[1])[0] || []
	return name ? { name, share: totals.value.cost ? Math.round((cost / totals.value.cost) * 100) : 0 } : null
})

const tiles = computed(() => {
	const t = totals.value
	const p = previous.value
	const per = (cost, n) => (n ? cost / n : 0)
	const topNote = topDepartment.value ? `Top: ${topDepartment.value.name} ${topDepartment.value.share}%` : ""
	if (axis.value === "chat_user") {
		const users = t.active_users || 0
		return [
			{ label: "Chat spend", value: fmtCost(t.cost), delta: costDelta.value, goodDirection: "down" },
			{ label: "Conversations", value: fmtNum(t.conversations || 0),
				delta: ratio(t.conversations || 0, p.conversations || 0), goodDirection: "up" },
			{ label: "Active users", value: fmtNum(users), absolute: true, goodDirection: "up",
				delta: p.users === undefined ? null : users - (p.users || 0),
				note: `of ${fmtNum(t.seats || 0)} seats` },
			{ label: "Avg cost / user", value: fmtCost(per(t.cost, users)),
				delta: ratio(per(t.cost, users), per(p.cost, p.users)), goodDirection: "down" },
			{ label: "Avg cost / conversation", short: "Avg cost / conv", value: fmtCost(per(t.cost, t.conversations)),
				delta: ratio(per(t.cost, t.conversations), per(p.cost, p.conversations)), goodDirection: "down" },
			{ label: "Departments", value: fmtNum(departmentCount.value), note: topNote },
		]
	}
	return [
		{ label: "Process spend", value: fmtCost(t.cost), delta: costDelta.value, goodDirection: "down" },
		{ label: "Runs", value: fmtNum(t.runs), delta: ratio(t.runs, p.runs), goodDirection: "up" },
		{ label: "Tokens", value: fmtCompact(t.tokens), delta: ratio(t.tokens, p.tokens), goodDirection: "up" },
		{ label: "Avg cost / run", value: fmtCost(per(t.cost, t.runs)),
			delta: ratio(per(t.cost, t.runs), per(p.cost, p.runs)), goodDirection: "down" },
		{ label: "Departments", value: fmtNum(departmentCount.value), note: `${fmtNum(ownerCount.value)} process owners` },
		{ label: "Processes", value: fmtNum(t.processes || 0), note: t.top_process ? `Top: ${t.top_process}` : "" },
	]
})

// -- colours -----------------------------------------------------------
// Assigned over the keys in a stable order, not by cost, so a node keeps its
// colour across the chart, the donut and the table's share bars.
const colorByKey = computed(() => {
	const keys = tree.value.map((n) => n.key).sort()
	return Object.fromEntries(
		keys.map((key, i) => [key, i < MAX_SERIES ? SERIES_COLORS[i] : OTHER_COLOR])
	)
})
function colorOf(key) {
	return colorByKey.value[key] || OTHER_COLOR
}

// Past the last slot the tail folds into one "Other" series rather than being
// handed a made-up colour.
const charted = computed(() => {
	const keys = new Set(Object.entries(colorByKey.value)
		.filter(([, color]) => color !== OTHER_COLOR).map(([key]) => key))
	return tree.value.filter((n) => keys.has(n.key))
})
const otherNodes = computed(() => tree.value.filter((n) => !charted.value.includes(n)))

const chartHeight = computed(() => (isPhone.value ? 170 : 230))
const seriesNodes = computed(() =>
	otherNodes.value.length
		? [...charted.value, { key: "", label: "Other", cost: otherNodes.value.reduce((t, n) => t + n.cost, 0),
			by_bucket: _sumBuckets(otherNodes.value) }]
		: charted.value
)
function _sumBuckets(nodes) {
	const out = {}
	for (const n of nodes) for (const [b, v] of Object.entries(n.by_bucket || {})) out[b] = (out[b] || 0) + v
	return out
}
const bucketTotals = computed(() =>
	Object.fromEntries((report.value.buckets || []).map((b) =>
		[b, seriesNodes.value.reduce((t, n) => t + (n.by_bucket?.[b] || 0), 0)]))
)
// The bucket still being written: it is faded so a short bar is not read as a drop.
const currentBucket = computed(() => {
	const buckets = report.value.buckets || []
	const today = dayjs().format("YYYY-MM-DD")
	if (!buckets.length || today < buckets[0] || today > (report.value.to_date || "")) return null
	return [...buckets].reverse().find((b) => b <= today) || null
})

const barConfig = computed(() => {
	const buckets = report.value.buckets || []
	const border = { borderColor: "#ffffff", borderWidth: 2 }
	const last = seriesNodes.value.length - 1
	const data = buckets.map((bucket) => {
		const row = { date: bucket }
		for (const node of seriesNodes.value) row[node.label] = node.by_bucket?.[bucket] || 0
		return row
	})
	const series = seriesNodes.value.map((node, i) => ({
		name: node.label,
		type: "bar",
		stackName: "cost",
		color: node.key ? colorOf(node.key) : OTHER_COLOR,
		echartOptions: {
			// The point for the bucket in progress carries its own opacity.
			data: buckets.map((b) => ({
				value: [b, node.by_bucket?.[b] || 0],
				itemStyle: b === currentBucket.value ? { opacity: 0.7 } : {},
			})),
			itemStyle: { ...border, borderRadius: i === last ? [2, 2, 0, 0] : 0 },
			// One label per stack, on its top segment, reading the bucket total.
			label: i === last
				? { show: true, position: "top", fontSize: 11, color: "#4b5563",
					formatter: (p) => (bucketTotals.value[p.value[0]] ? fmtCost(bucketTotals.value[p.value[0]]) : "") }
				: { show: false },
		},
	}))
	const perRow = isPhone.value ? 2 : 5
	const legendRows = Math.ceil(series.length / perRow)
	return {
		data,
		title: `Cost by ${groupLabel.value}`,
		subtitle: `${rangeLabel.value}, ${report.value.grain}ly`,
		xAxis: {
			key: "date", type: "time", timeGrain: report.value.grain || "day",
			// One tick per bucket; the time axis would otherwise tick every few days.
			echartOptions: { minInterval: (report.value.grain === "month" ? 28 : 7) * 86400000 },
		},
		yAxis: { title: "Cost (USD)" },
		stacked: true,
		series,
		echartOptions: {
			legend: series.length > 1 ? { type: "plain", bottom: 0 } : { show: false },
			grid: { bottom: series.length > 1 ? 16 + 22 * legendRows : 16, top: 64 },
			tooltip: { formatter: barTooltip },
		},
	}
})

function barTooltip(params) {
	const points = (Array.isArray(params) ? params : [params]).filter((p) => p.value?.[1])
	if (!points.length) return ""
	const bucket = points[0].value[0]
	const buckets = report.value.buckets || []
	const idx = buckets.indexOf(bucket)
	const rows = points
		.sort((a, b) => b.value[1] - a.value[1])
		.map((p) => `<div class="flex items-center justify-between gap-5">
			<div class="flex gap-1 items-center">${p.marker}<div>${p.seriesName}</div></div>
			<div class="font-bold">${fmtCost(p.value[1])}</div></div>`)
	return `<div>${bucketLabel(bucket, buckets[idx + 1])}</div>${rows.join("")}
		<div class="flex items-center justify-between gap-5 border-t mt-1 pt-1">
			<div>Total</div><div class="font-bold">${fmtCost(bucketTotals.value[bucket] || 0)}</div></div>`
}

// Share donut, drawn directly: the shared DonutChart cannot show cost in its
// legend or name the top share in the centre.
const donutOptions = computed(() => {
	const slices = seriesNodes.value
		.map((n) => ({ name: n.label, value: n.cost, key: n.key }))
		.sort((a, b) => b.value - a.value)
	const total = slices.reduce((t, x) => t + x.value, 0)
	const top = slices[0]
	const pct = (v) => (total ? Math.round((v / total) * 100) : 0)
	return {
		animation: true,
		textStyle: { fontFamily: ["InterVar", "sans-serif"] },
		color: slices.map((x) => (x.key ? colorOf(x.key) : OTHER_COLOR)),
		title: {
			text: `Share by ${groupLabel.value}`, subtext: fmtCost(total), left: 0, top: 0, padding: 0,
			textStyle: { fontSize: 14, fontWeight: 500, color: "#374151" },
			subtextStyle: { fontSize: 13, color: "#6b7280" },
		},
		graphic: top ? [{
			type: "text", left: "center", top: "44%",
			style: { text: `${pct(top.value)}%\n${top.name}`, textAlign: "center", fontSize: 12,
				lineHeight: 16, fill: "#4b5563", width: 90, overflow: "truncate" },
		}] : [],
		legend: {
			type: "plain", bottom: 0, icon: "circle", itemGap: 8,
			textStyle: { color: "#374151", fontSize: 11 },
			formatter: (name) => {
				const x = slices.find((y) => y.name === name)
				return x ? `${name}  ${fmtCost(x.value)} · ${pct(x.value)}%` : name
			},
		},
		tooltip: {
			trigger: "item", confine: true,
			formatter: (p) => `<div class="flex items-center justify-between gap-5"><div>${p.name}</div>
				<div class="font-bold">${fmtCost(p.value)} (${pct(p.value)}%)</div></div>`,
		},
		series: [{
			type: "pie", radius: ["46%", "68%"], center: ["50%", "48%"],
			itemStyle: { borderColor: "#ffffff", borderWidth: 2 },
			label: { show: false }, emphasis: { scaleSize: 4 },
			data: slices.map((x) => ({ name: x.name, value: x.value })),
		}],
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

// Month columns only while there are few enough to read; one month is the Cost
// column already, and past six the table stops being a table.
const monthColumns = computed(() => {
	const months = report.value.months || []
	return months.length >= 2 && months.length <= 6 ? months : []
})
function monthHeader(m) {
	const label = dayjs(`${m}-01`).format("MMM YYYY")
	return m === dayjs().format("YYYY-MM") ? `${label} (to date)` : label
}
function monthTotal(m) {
	return tree.value.reduce((t, n) => t + (n.by_month?.[m] || 0), 0)
}

// Share bars fill against the largest top-level node, so the biggest is full width.
const maxTopShare = computed(() => Math.max(0, ...tree.value.map((n) => n.share || 0)))
function barWidth(node) {
	return maxTopShare.value ? Math.min(100, (node.share / maxTopShare.value) * 100) : 0
}

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
function fmtDay(d) { return dayjs(d).format("MMM D") }
function bucketLabel(start, next) {
	if (report.value.grain === "month") return dayjs(start).format("MMM YYYY")
	const end = next ? dayjs(next).subtract(1, "day") : dayjs(report.value.to_date)
	return `${dayjs(start).format("MMM D")} – ${end.format("D")}`
}

const GRAY = "bg-gray-100 text-gray-500"
const DeltaBadge = (p) => {
	const pill = (tone, text) => h("span", { class: `text-xs px-1.5 py-0.5 rounded ${tone}` }, text)
	if (p.delta === null || p.delta === undefined) {
		return h("div", { class: "inline-flex mt-1" }, [pill(GRAY, "new")])
	}
	const n = p.absolute ? Math.round(p.delta) : Math.round(p.delta * 100)
	// Within two points is noise; beyond it, red is the bad way for this tile.
	const bad = p.goodDirection === "up" ? n < 0 : n > 0
	const quiet = p.absolute ? n === 0 : Math.abs(n) < 2
	const tone = quiet ? GRAY : bad ? "bg-red-50 text-red-600" : "bg-green-50 text-green-700"
	return h("div", { class: `inline-flex items-center gap-1.5 mt-1 ${p.note ? "flex-wrap" : ""}` }, [
		pill(tone, `${n > 0 ? "+" : ""}${n}${p.absolute ? "" : "%"}`),
		p.note ? h("span", { class: "text-xs text-gray-400 whitespace-nowrap" }, p.note) : null,
	])
}
DeltaBadge.props = {
	delta: {}, note: String, goodDirection: { type: String, default: "down" }, absolute: Boolean,
}

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
	error.value = null
	try {
		report.value = await frappeRequest({
			url: "/api/method/one_bpmn.api.insights_api.get_cost_allocation",
			method: "POST",
			params: queryParams(),
		})
		expanded.value = new Set((report.value.tree || []).map((n) => `/${n.key || n.label}`))
	} catch (e) {
		error.value = e
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
