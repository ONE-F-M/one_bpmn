<template>
	<div class="h-full flex flex-col bg-gray-50">
		<header class="insights-header bg-white border-b px-4 sm:px-6 py-3 grid grid-cols-2 gap-2 items-center sm:flex sm:flex-wrap sm:gap-3">
			<h1 class="text-xl font-semibold text-gray-900 sm:mr-2">AI Insights</h1>
			<Tooltip :text="disabledReason(['origin'])">
				<div class="justify-self-end">
					<TabButtons
						v-model="origin"
						:buttons="originButtons"
					/>
				</div>
			</Tooltip>
			<Tooltip :text="disabledReason(['dates'])">
				<div :class="{ 'pointer-events-none opacity-60': isDisabled('dates') }">
					<DateRangePicker
						v-model="range"
						:readonly="isDisabled('dates')"
						input-class="w-full sm:w-56"
					/>
				</div>
			</Tooltip>
			<Tooltip :text="disabledReason(['dates'])">
				<div class="justify-self-end">
					<Dropdown
						:options="presetOptions"
						:button="presetButton"
					/>
				</div>
			</Tooltip>
			<Tooltip :text="disabledReason(['model'])">
				<div>
					<FormControl
						v-model="model"
						type="select"
						:options="withAll(__('All models'), filterOptions.models)"
						:disabled="isDisabled('model')"
						class="sm:w-44"
					/>
				</div>
			</Tooltip>
			<Tooltip :text="disabledReason(['provider'])">
				<div>
					<FormControl
						v-model="provider"
						type="select"
						:options="withAll(__('All providers'), filterOptions.providers)"
						:disabled="isDisabled('provider')"
						class="sm:w-44"
					/>
				</div>
			</Tooltip>
			<Tooltip :text="disabledReason(['process'])">
				<div>
					<FormControl
						v-model="processModel"
						type="select"
						:options="withAll(__('All processes'), filterOptions.processes)"
						:disabled="isDisabled('process')"
						class="sm:w-48"
					/>
				</div>
			</Tooltip>
			<div class="justify-self-end">
				<Button
					v-if="!isDefault"
					variant="ghost"
					:label="__('Reset')"
					@click="resetFilters"
				/>
			</div>
		</header>

		<main class="flex-1 p-4 sm:p-6 overflow-auto space-y-6">
			<OverviewCards v-bind="reportProps" />

			<div class="insights-tabs bg-white rounded-lg shadow-sm">
				<Tabs
					v-model="activeIndex"
					:tabs="tabs"
				>
					<template #tab-item="{ tab, selected }">
						<button
							:ref="(el) => setTabElement(tab.key, el)"
							class="flex items-center gap-2 py-3 text-sm font-medium whitespace-nowrap border-b-2"
							:class="selected ? 'text-gray-900 border-gray-900' : 'text-gray-500 border-transparent hover:text-gray-700'"
						>
							<Icon
								:icon="tab.icon"
								class="w-4 h-4"
							/>
							{{ tab.label }}
						</button>
					</template>
					<template #tab-panel="{ tab }">
						<div class="p-4 sm:p-6">
							<UsageReport
								v-if="tab.key === 'cost'"
								v-bind="reportProps"
							/>
							<ErrorReport
								v-if="tab.key === 'errors'"
								:from-date="fromDate"
								:to-date="toDate"
								:origin="origin"
							/>
							<PerformanceReport
								v-if="tab.key === 'performance'"
								:from-date="fromDate"
								:to-date="toDate"
								:origin="origin"
							/>
							<CostAllocationReport
								v-if="tab.key === 'allocation'"
								v-bind="reportProps"
							/>
							<WorkItemCostReport v-if="tab.key === 'work_item_cost'" />
						</div>
					</template>
				</Tabs>
			</div>
		</main>
	</div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from "vue"
import { Button, DateRangePicker, Dropdown, FormControl, frappeRequest, TabButtons, Tabs, Tooltip } from "frappe-ui"
import { Icon } from "@iconify/vue"
import { dayjs } from "@/dayjs"

import OverviewCards from "@/components/insights/OverviewCards.vue"
import UsageReport from "@/components/insights/UsageReport.vue"
import ErrorReport from "@/components/insights/ErrorReport.vue"
import PerformanceReport from "@/components/insights/PerformanceReport.vue"
import CostAllocationReport from "@/components/insights/CostAllocationReport.vue"
import WorkItemCostReport from "@/components/insights/WorkItemCostReport.vue"

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s
const ACTIVE_TAB_KEY = "insights.activeTab"
const DEFAULT_PRESET = "last_7_days"
const EMPTY_OPTIONS = { models: [], providers: [], processes: [] }

const tabs = [
	{ key: "cost", label: __("Usage"), icon: "lucide:credit-card" },
	{ key: "errors", label: __("Errors"), icon: "lucide:alert-triangle" },
	{ key: "performance", label: __("Latency"), icon: "lucide:timer" },
	{ key: "allocation", label: __("Cost Allocation"), icon: "lucide:receipt" },
	{ key: "work_item_cost", label: __("Work Items"), icon: "lucide:package-search" },
]

// The header controls each tab ignores, and the tooltip they show while it is open.
const DISABLED_BY_TAB = {
	allocation: { controls: ["model", "provider"], reason: __("Allocation covers all models") },
	work_item_cost: {
		controls: ["dates", "origin", "model", "provider", "process"],
		reason: __("Not applicable to this report"),
	},
}

const PRESETS = {
	today: { label: __("Today"), range: (d) => [d, d] },
	last_7_days: { label: __("Last 7 days"), range: (d) => [d.subtract(6, "day"), d] },
	last_30_days: { label: __("Last 30 days"), range: (d) => [d.subtract(29, "day"), d] },
	this_month: { label: __("This month"), range: (d) => [d.startOf("month"), d] },
	last_month: {
		label: __("Last month"),
		range: (d) => [d.subtract(1, "month").startOf("month"), d.subtract(1, "month").endOf("month")],
	},
}

const preset = ref(DEFAULT_PRESET)
const range = ref(rangeFor(DEFAULT_PRESET))
const origin = ref("production")
const model = ref("")
const provider = ref("")
const processModel = ref("")
const filterOptions = ref(EMPTY_OPTIONS)
const activeIndex = ref(savedTabIndex())
const tabElements = {}

const fromDate = computed(() => range.value.split(",")[0] || "")
const toDate = computed(() => range.value.split(",")[1] || "")
const activeKey = computed(() => tabs[activeIndex.value]?.key)
const presetButton = computed(() => ({
	label: PRESETS[preset.value]?.label || __("Custom"),
	iconRight: "chevron-down",
	disabled: isDisabled("dates"),
}))
const presetOptions = computed(() =>
	Object.entries(PRESETS).map(([key, { label }]) => ({ label, onClick: () => (preset.value = key) })),
)
const originButtons = computed(() =>
	[
		{ label: __("Production"), value: "production" },
		{ label: __("Evals"), value: "eval" },
		{ label: __("All"), value: "all" },
	].map((button) => ({ ...button, disabled: isDisabled("origin") })),
)
const isDefault = computed(
	() =>
		preset.value === DEFAULT_PRESET &&
		origin.value === "production" &&
		!model.value &&
		!provider.value &&
		!processModel.value,
)
const reportProps = computed(() => ({
	fromDate: fromDate.value,
	toDate: toDate.value,
	origin: origin.value,
	model: model.value,
	provider: provider.value,
	processModel: processModel.value,
}))

function rangeFor(key) {
	const [from, to] = PRESETS[key].range(dayjs())
	return `${from.format("YYYY-MM-DD")},${to.format("YYYY-MM-DD")}`
}

function savedTabIndex() {
	try {
		const index = tabs.findIndex((tab) => tab.key === window.localStorage.getItem(ACTIVE_TAB_KEY))
		return index >= 0 ? index : 0
	} catch {
		return 0
	}
}

function isDisabled(control) {
	return DISABLED_BY_TAB[activeKey.value]?.controls.includes(control) || false
}

function disabledReason(controls) {
	return controls.some(isDisabled) ? DISABLED_BY_TAB[activeKey.value].reason : ""
}

function withAll(label, values) {
	return [{ label, value: "" }, ...(values || []).map((value) => ({ label: value, value }))]
}

function setTabElement(key, el) {
	if (el) tabElements[key] = el
}

function resetFilters() {
	preset.value = DEFAULT_PRESET
	origin.value = "production"
	model.value = ""
	provider.value = ""
	processModel.value = ""
}

async function loadFilterOptions() {
	try {
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.insights_api.get_cost_token_report",
			method: "POST",
			params: { from_date: fromDate.value, to_date: toDate.value, origin: origin.value },
		})
		filterOptions.value = { ...EMPTY_OPTIONS, ...(response?.filter_options || {}) }
	} catch {
		filterOptions.value = EMPTY_OPTIONS
	}
	// A selection with no runs in the new range would filter every tab to nothing.
	if (!filterOptions.value.models.includes(model.value)) model.value = ""
	if (!filterOptions.value.providers.includes(provider.value)) provider.value = ""
	if (!filterOptions.value.processes.includes(processModel.value)) processModel.value = ""
}

watch(preset, (key) => {
	if (PRESETS[key]) range.value = rangeFor(key)
})
watch(range, (value) => {
	if (PRESETS[preset.value] && value !== rangeFor(preset.value)) preset.value = "custom"
})
watch(activeKey, (key) => {
	try {
		window.localStorage.setItem(ACTIVE_TAB_KEY, key)
	} catch {
		// A private window can refuse storage; the tab still opens.
	}
	if (key === "allocation") preset.value = "this_month"
})
watch([fromDate, toDate, origin], loadFilterOptions)

onMounted(() => {
	loadFilterOptions()
	nextTick(() => tabElements[activeKey.value]?.scrollIntoView({ block: "nearest", inline: "nearest" }))
})
</script>

<style scoped>
@media (max-width: 639px) {
	.insights-header :deep(button),
	.insights-header :deep(input),
	.insights-header :deep(select) {
		min-height: 36px;
	}

	.insights-tabs :deep([role="tablist"]) {
		mask-image: linear-gradient(to right, black calc(100% - 24px), transparent);
	}
}
</style>
