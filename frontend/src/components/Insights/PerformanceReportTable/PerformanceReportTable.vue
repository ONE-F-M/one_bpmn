<template>
	<div class="space-y-2">
		<div class="flex flex-wrap items-baseline gap-x-3">
			<h3 class="text-sm font-semibold text-gray-900">{{ __("Slowest elements") }}</h3>
			<span class="text-xs text-gray-500">{{ __("sorted by total agent time · click a row for where the time goes") }}</span>
		</div>
		<div class="overflow-x-auto bg-white rounded-lg border border-gray-200">
			<table class="w-full min-w-[800px] table-fixed">
				<colgroup>
					<col class="w-8">
					<col>
					<col class="w-[18%]">
					<col class="w-20">
					<col class="w-24">
					<col class="w-36">
					<col class="w-32">
				</colgroup>
				<thead>
					<tr class="border-b border-gray-200 text-left text-xs uppercase tracking-wide text-gray-500">
						<th></th>
						<th class="py-2 px-3 font-medium">{{ __("Element") }}</th>
						<th class="py-2 px-3 font-medium">{{ seriesLabel }}</th>
						<th class="py-2 px-3 font-medium text-right">{{ __("Runs") }}</th>
						<th class="py-2 px-3 font-medium text-right">P50</th>
						<th class="py-2 px-3 font-medium text-right">P95</th>
						<th class="py-2 px-3 font-medium text-right">{{ __("Total agent time") }}</th>
					</tr>
				</thead>
				<tbody>
					<template
						v-for="element in elements"
						:key="element.key"
					>
						<tr
							class="border-b border-gray-100 cursor-pointer hover:bg-gray-50"
							@click="toggle(element)"
						>
							<td class="py-3 pl-3">
								<FeatherIcon
									:name="isExpanded(element.key) ? 'chevron-down' : 'chevron-right'"
									class="w-4 h-4 text-gray-400"
								/>
							</td>
							<td
								class="py-3 px-3 whitespace-nowrap overflow-hidden text-ellipsis"
								:title="`${element.bpmn_label} · ${element.process_model}`"
							>
								<span class="text-sm font-semibold text-gray-900">{{ element.bpmn_label }}</span>
								<span class="ml-2 text-xs text-gray-500">{{ element.process_model }}</span>
							</td>
							<td
								class="py-3 px-3 whitespace-nowrap overflow-hidden text-ellipsis text-sm text-gray-700"
								:title="element.series"
							>
								{{ element.series || "-" }}
							</td>
							<td class="py-3 px-3 text-right text-sm text-gray-700">{{ fmtInt(element.runs) }}</td>
							<td class="py-3 px-3 text-right text-sm text-gray-700">{{ fmtDuration(element.p50_ms) }}</td>
							<td class="py-3 px-3 text-right whitespace-nowrap text-sm">
								<span class="font-semibold text-gray-900">{{ fmtDuration(element.p95_ms) }}</span>
								<DeltaPill
									class="ml-1.5"
									:delta="element.delta_p95_pct"
									good-direction="down"
								/>
							</td>
							<td class="py-3 px-3 text-right text-sm font-semibold text-gray-900">{{ fmtDuration(element.total_ms) }}</td>
						</tr>
						<tr
							v-if="isExpanded(element.key)"
							class="border-b border-gray-100"
						>
							<td
								colspan="7"
								class="px-6 pb-4 pt-1 space-y-4"
							>
								<dl class="flex flex-wrap gap-x-8 gap-y-2">
									<div
										v-for="fact in facts(element)"
										:key="fact.label"
									>
										<dt class="text-[10px] uppercase tracking-wide text-gray-500 font-medium">{{ fact.label }}</dt>
										<dd class="text-sm font-semibold text-gray-900">{{ fact.value }}</dd>
									</div>
								</dl>
								<ErrorMessage
									v-if="detail(element.key).error"
									:message="detail(element.key).error"
								/>
								<template v-if="detail(element.key).split">
									<div>
										<div class="text-[10px] uppercase tracking-wide text-gray-500 font-medium mb-1.5">{{ __("Where the time goes") }}</div>
										<PerformanceReportSplitBar :split="detail(element.key).split" />
									</div>
									<div>
										<div class="text-[10px] uppercase tracking-wide text-gray-500 font-medium mb-1">{{ __("Top steps by time") }}</div>
										<div
											v-for="step in detail(element.key).steps"
											:key="`${step.step_kind}|${step.agent_configuration}`"
											class="grid grid-cols-[1fr_4rem_5rem_5rem] gap-3 text-sm"
										>
											<span
												class="truncate text-gray-900"
												:title="step.step_kind"
											>{{ step.step_kind }}</span>
											<span class="text-right text-gray-600">{{ fmtPct(step.share, 0) }}</span>
											<span class="text-right text-gray-600">{{ __("avg") }} {{ fmtDuration(step.avg_ms) }}</span>
											<span class="text-right text-gray-600">{{ __("max") }} {{ fmtDuration(step.max_ms) }}</span>
										</div>
									</div>
									<div>
										<div class="text-[10px] uppercase tracking-wide text-gray-500 font-medium mb-1">
											{{ __("Slowest runs above P95") }} · {{ fmtInt(detail(element.key).total) }}
										</div>
										<div class="border-l-2 border-gray-200 pl-3 space-y-1">
											<div
												v-for="run in detail(element.key).runs"
												:key="run.name"
												class="grid grid-cols-[8rem_5rem_3rem_9rem_1fr_5rem] items-center gap-3 text-sm"
											>
												<span class="text-gray-700 whitespace-nowrap">{{ runTime(run) }}</span>
												<span class="text-right font-semibold text-gray-900">{{ fmtDuration(run.agent_latency_ms) }}</span>
												<span class="text-right text-gray-600">{{ fmtInt(run.step_count) }}</span>
												<span
													class="truncate"
													:class="statusClass(run)"
													:title="runStatus(run)"
												>{{ runStatus(run) }}</span>
												<span
													class="truncate text-gray-600"
													:title="slowestStep(run)"
												>{{ slowestStep(run) }}</span>
												<a
													:href="`/processa/runs/${run.name}`"
													target="_blank"
													rel="noopener"
													class="text-right text-blue-600 hover:underline whitespace-nowrap"
													@click.stop
												>{{ __("Open run") }}</a>
											</div>
										</div>
									</div>
								</template>
								<LoadingIndicator
									v-if="detail(element.key).loading"
									class="w-4 h-4 text-gray-400"
								/>
								<button
									v-if="canShowMore(element.key)"
									class="text-xs text-gray-500"
									@click.stop="load(element, true)"
								>
									{{ moreCount(element.key) }} {{ __("more") }} · <span class="text-blue-600">{{ __("show") }}</span>
								</button>
							</td>
						</tr>
					</template>
				</tbody>
				<tfoot>
					<tr class="border-t border-gray-200 text-sm font-semibold text-gray-900">
						<td></td>
						<td class="py-3 px-3">{{ __("All") }} · {{ fmtInt(elements.length) }} {{ __("elements") }}</td>
						<td></td>
						<td class="py-3 px-3 text-right">{{ fmtInt(summary.runs) }}</td>
						<td class="py-3 px-3 text-right">{{ fmtDuration(summary.p50_ms) }}</td>
						<td class="py-3 px-3 text-right">{{ fmtDuration(summary.p95_ms) }}</td>
						<td class="py-3 px-3 text-right">{{ fmtDuration(summary.total_ms) }}</td>
					</tr>
				</tfoot>
			</table>
		</div>
	</div>
</template>

<script setup>
import { computed } from "vue"
import { ErrorMessage, FeatherIcon, LoadingIndicator } from "frappe-ui"
import { dayjs } from "@/dayjs"
import DeltaPill from "@/components/Insights/DeltaPill/DeltaPill.vue"
import PerformanceReportSplitBar from "@/components/Insights/PerformanceReportSplitBar/PerformanceReportSplitBar.vue"
import { fmtDuration, fmtInt, fmtPct } from "@/utils/formatters"

const props = defineProps({
	elements: { type: Array, required: true },
	summary: { type: Object, required: true },
	groupBy: { type: String, default: "model" },
	elementRuns: { type: Object, required: true },
})

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s
const { entry: detail, load, remaining: moreCount, toggle, isExpanded } = props.elementRuns

const seriesLabel = computed(() => (props.groupBy === "agent" ? __("AI Agent") : __("Model")))

function runTime(run) {
	return dayjs(run.started_at).format("MMM D HH:mm")
}

function canShowMore(elementKey) {
	return moreCount(elementKey) > 0 && !detail(elementKey).loading
}

function statusClass(run) {
	return run.status === "Error" ? "text-red-600" : "text-gray-600"
}

function runStatus(run) {
	return run.status === "Error" ? `${__("Error")} · ${run.error_code}` : __("Success")
}

function slowestStep(run) {
	const step = run.slowest_step
	return step ? `${step.label} · ${fmtDuration(step.latency_ms)}` : ""
}

function facts(element) {
	const previous = element.previous_p95_ms === null ? __("new") : fmtDuration(element.previous_p95_ms)
	return [
		{ label: __("Avg"), value: fmtDuration(element.avg_ms) },
		{ label: __("Max"), value: fmtDuration(element.max_ms) },
		{ label: __("Avg steps"), value: element.avg_steps },
		{ label: __("Errored runs"), value: `${fmtInt(element.error_runs)} ${__("of")} ${fmtInt(element.runs)}` },
		{
			label: __("Human wait"),
			value: `${fmtInt(element.human_wait_runs)} ${__("runs")} · ${__("avg")} ${fmtDuration(element.avg_human_wait_ms)}`,
		},
		{ label: __("P95 vs prior"), value: `${previous} ${__("to")} ${fmtDuration(element.p95_ms)}` },
	]
}
</script>

<style scoped>
</style>
