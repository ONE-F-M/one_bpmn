<template>
	<div class="space-y-6">
		<!-- At phone width the axis toggle and Export share row one; grouping takes row two. -->
		<div class="alloc-toolbar flex flex-wrap items-center gap-3">
			<TabButtons
				v-model="axis"
				class="order-1"
				:buttons="axisButtons"
			/>
			<TabButtons
				v-model="groupBy"
				class="order-3 w-full sm:order-2 sm:w-auto"
				:buttons="groupButtons"
			/>
			<div class="order-2 ml-auto sm:order-3">
				<Dropdown
					:options="exportOptions"
					placement="right"
				>
					<Button
						icon-left="download"
						icon-right="chevron-down"
						aria-label="Export"
						:loading="exporting"
						:disabled="!tree.length || exporting"
					>
						<span class="hidden sm:inline">Export</span>
					</Button>
				</Dropdown>
			</div>
		</div>
		<ErrorMessage :message="exportError" />

		<CostAllocationPricingAlert
			v-if="missingPricing.length"
			:models="missingPricing"
		/>

		<div
			v-if="error"
			class="flex flex-col items-center justify-center h-48 text-center gap-3"
		>
			<ErrorMessage :message="error" />
			<Button @click="fetchReport">Retry</Button>
		</div>

		<template v-else>
			<CostAllocationTiles
				v-if="report.totals"
				:report="report"
				@switch-axis="toggleAxis"
			/>

			<div
				v-if="loading && !report.tree"
				class="flex justify-center py-12"
			>
				<LoadingIndicator class="w-6 h-6 text-gray-400" />
			</div>
			<div
				v-else-if="!tree.length"
				class="flex flex-col items-center justify-center h-48 text-center"
			>
				<Icon
					icon="lucide:receipt"
					class="w-12 h-12 text-gray-300 mb-3"
				/>
				<h3 class="text-base font-medium text-gray-900">No usage in this period</h3>
				<p class="text-sm text-gray-500">Adjust the date range above.</p>
			</div>

			<template v-else>
				<div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
					<CostAllocationChart
						class="lg:col-span-2"
						:report="report"
						:series="series"
						:colors="colors"
						:group-label="groupLabel"
					/>
					<CostAllocationDonut
						:slices="donutSlices"
						:colors="colors"
						:title="donutTitle"
						:total="report.totals.cost"
					/>
				</div>
				<CostAllocationCards
					v-if="isMobile"
					:report="report"
					:rows="rows"
					:colors="colors"
					:cost-delta="costDelta"
					@toggle="toggle"
				/>
				<CostAllocationTree
					v-else
					:report="report"
					:rows="rows"
					:colors="colors"
					:level-header="levelHeader"
					:cost-delta="costDelta"
					@toggle="toggle"
				/>
			</template>
		</template>
	</div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from "vue"
import { Button, Dropdown, ErrorMessage, LoadingIndicator, TabButtons } from "frappe-ui"
import { Icon } from "@iconify/vue"
import { useCostAllocation } from "@/composables/useCostAllocation"
import { useWindowSize } from "@/composables/useWindowSize"
import CostAllocationPricingAlert from "@/components/insights/CostAllocationPricingAlert.vue"
import CostAllocationTiles from "@/components/insights/CostAllocationTiles.vue"
import CostAllocationChart from "@/components/insights/CostAllocationChart.vue"
import CostAllocationDonut from "@/components/insights/CostAllocationDonut.vue"
import CostAllocationTree from "@/components/insights/CostAllocationTree.vue"
import CostAllocationCards from "@/components/insights/CostAllocationCards.vue"
import { MAX_SERIES, OTHER_COLOR, OTHER_KEY, assignColors, foldTail, pctChange, rowsOf } from "@/utils/costAllocation"

// model and provider arrive from the shared header and are unused here.
const props = defineProps({
	fromDate: { type: String, default: null },
	toDate: { type: String, default: null },
	origin: { type: String, default: "production" },
	model: { type: String, default: null },
	provider: { type: String, default: null },
	processModel: { type: String, default: null },
})

const LEVELS = {
	process_owner: { department: ["department", "owner", "process"], owner: ["owner", "process"], process: ["process", "owner"] },
	chat_user: { department: ["department", "user", "agent"], user: ["user", "agent"], agent: ["agent", "user"] },
}

const axis = ref("process_owner")
const groupBy = ref("department")
const exportError = ref(null)
const { report, loading, error, exporting, load, exportFile } = useCostAllocation()
const { isMobile } = useWindowSize()

function toggleLabel(text) {
	return isMobile.value ? `${text[0].toUpperCase()}${text.slice(1)}` : `By ${text}`
}
const axisButtons = computed(() => [
	{ label: toggleLabel("process owner"), value: "process_owner" },
	{ label: toggleLabel("chat user"), value: "chat_user" },
])
const groupButtons = computed(() =>
	Object.keys(LEVELS[axis.value]).map((value) => ({ label: toggleLabel(value), value }))
)

const tree = computed(() => report.value.tree || [])
const missingPricing = computed(() => report.value.models_missing_pricing || [])
// Labels follow the report on screen, not the toggle, until the new report arrives.
const groupLabel = computed(() => report.value.group_by)
const levelHeader = computed(() => LEVELS[report.value.axis][report.value.group_by].join(" / ").toUpperCase())
const costDelta = computed(() => pctChange(report.value.totals.cost, report.value.previous.cost))

const colorMemo = new Map()
const series = computed(() => foldTail(tree.value, MAX_SERIES))
const colors = computed(() => {
	const out = assignColors(series.value.map((n) => n.key).filter((k) => k !== OTHER_KEY), colorMemo)
	for (const node of tree.value) {
		if (!(node.key in out)) out[node.key] = OTHER_COLOR
	}
	return out
})
const donutTitle = computed(() => `Share by ${groupLabel.value}`)
const donutSlices = computed(() => series.value.map((n) => ({ key: n.key, label: n.label, value: n.cost })))

const expanded = ref(new Set())
const rows = computed(() => rowsOf(tree.value, expanded.value))
function toggle(path) {
	const next = new Set(expanded.value)
	if (next.has(path)) next.delete(path)
	else next.add(path)
	expanded.value = next
}

function toggleAxis() {
	axis.value = axis.value === "chat_user" ? "process_owner" : "chat_user"
}

function queryParams() {
	return {
		axis: axis.value,
		group_by: groupBy.value,
		origin: props.origin,
		...(props.fromDate ? { from_date: props.fromDate } : {}),
		...(props.toDate ? { to_date: props.toDate } : {}),
		...(props.processModel ? { process_model: props.processModel } : {}),
	}
}

async function exportAs(fmt) {
	exportError.value = null
	try {
		await exportFile({ ...queryParams(), fmt })
	} catch (e) {
		exportError.value = e
	}
}
const exportOptions = [
	{ label: "XLSX", icon: "file-spreadsheet", onClick: () => exportAs("xlsx") },
	{ label: "CSV", icon: "file-text", onClick: () => exportAs("csv") },
]

async function fetchReport() {
	if (!(await load(queryParams()))) return
	const top = report.value.tree?.[0]
	expanded.value = new Set(top ? [`/${top.key || top.label}`] : [])
}

// The two axes group differently, so switching axis resets the grouping.
watch(axis, () => {
	groupBy.value = "department"
})
watch(() => [props.fromDate, props.toDate, props.origin, props.processModel, axis.value, groupBy.value], fetchReport)
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
</style>
