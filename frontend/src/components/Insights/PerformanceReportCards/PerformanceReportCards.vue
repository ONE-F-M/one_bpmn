<template>
	<div class="space-y-2">
		<div class="flex flex-wrap items-baseline gap-x-2">
			<h3 class="text-sm font-semibold text-gray-900">{{ __("Slowest elements") }}</h3>
			<span class="text-xs text-gray-500">{{ __("tap a row for where the time goes") }}</span>
		</div>
		<div
			v-for="element in elements"
			:key="element.key"
			class="bg-white rounded-lg border border-gray-200 p-3"
			@click="toggle(element)"
		>
			<div class="flex items-center justify-between gap-3">
				<span class="text-sm font-semibold text-gray-900 truncate">{{ element.bpmn_label }}</span>
				<span class="text-sm font-semibold text-gray-900 whitespace-nowrap">{{ fmtDuration(element.p95_ms) }}</span>
			</div>
			<div class="flex items-center justify-between gap-3 mt-1 text-xs text-gray-500">
				<span class="truncate">{{ element.series || "-" }} · {{ fmtInt(element.runs) }} {{ __("runs") }}</span>
				<DeltaPill
					:delta="element.delta_p95_pct"
					good-direction="down"
				/>
			</div>
			<div class="mt-1 text-xs text-gray-500">
				P50 <span class="font-semibold text-gray-900">{{ fmtDuration(element.p50_ms) }}</span>
				· {{ __("total") }} <span class="font-semibold text-gray-900">{{ fmtDuration(element.total_ms) }}</span>
			</div>
			<div
				v-if="isExpanded(element.key)"
				class="mt-3 space-y-2"
			>
				<PerformanceReportSplitBar
					v-if="detail(element.key).split"
					:split="detail(element.key).split"
					:show-averages="false"
				/>
				<div
					v-for="run in firstRuns(element.key)"
					:key="run.name"
					class="flex items-center gap-3 text-sm"
				>
					<span class="text-gray-700 whitespace-nowrap">{{ runTime(run) }}</span>
					<span class="font-semibold text-gray-900">{{ fmtDuration(run.agent_latency_ms) }}</span>
					<span :class="statusClass(run)">{{ statusLabel(run) }}</span>
					<a
						:href="`/processa/runs/${run.name}`"
						target="_blank"
						rel="noopener"
						class="ml-auto text-blue-600 whitespace-nowrap"
						@click.stop
					>{{ __("Open run") }}</a>
				</div>
				<LoadingIndicator
					v-if="detail(element.key).loading"
					class="w-4 h-4 text-gray-400"
				/>
				<ErrorMessage
					v-if="detail(element.key).error"
					:message="detail(element.key).error"
				/>
			</div>
		</div>
		<div class="bg-gray-50 rounded-lg border border-gray-200 p-3">
			<div class="flex items-center justify-between text-sm font-semibold text-gray-900">
				<span>{{ __("All") }} · {{ fmtInt(elements.length) }} {{ __("elements") }}</span>
				<span>{{ fmtDuration(summary.p95_ms) }}</span>
			</div>
			<div class="text-xs text-gray-500 mt-1">
				{{ fmtInt(summary.runs) }} {{ __("runs") }} · P50 {{ fmtDuration(summary.p50_ms) }} · {{ __("total") }} {{ fmtDuration(summary.total_ms) }}
			</div>
		</div>
	</div>
</template>

<script setup>
import { ErrorMessage, LoadingIndicator } from "frappe-ui"
import { dayjs } from "@/dayjs"
import DeltaPill from "@/components/Insights/DeltaPill/DeltaPill.vue"
import PerformanceReportSplitBar from "@/components/Insights/PerformanceReportSplitBar/PerformanceReportSplitBar.vue"
import { fmtDuration, fmtInt } from "@/utils/formatters"

const props = defineProps({
	elements: { type: Array, required: true },
	summary: { type: Object, required: true },
	elementRuns: { type: Object, required: true },
})

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s
const FIRST_RUNS = 3
const { entry: detail, toggle, isExpanded } = props.elementRuns

function firstRuns(elementKey) {
	return detail(elementKey).runs.slice(0, FIRST_RUNS)
}

function runTime(run) {
	return dayjs(run.started_at).format("MMM D HH:mm")
}

function statusClass(run) {
	return run.status === "Error" ? "text-red-600" : "text-gray-600"
}

function statusLabel(run) {
	return run.status === "Error" ? __("Error") : __("Success")
}
</script>

<style scoped>
</style>
