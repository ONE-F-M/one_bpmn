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
					<col class="w-44">
				</colgroup>
				<thead>
					<tr class="border-b border-gray-200 text-left text-xs uppercase tracking-wide text-gray-500">
						<th></th>
						<th class="py-2 px-3 font-medium">{{ __("Element") }}</th>
						<th class="py-2 px-3 font-medium">{{ seriesLabel }}</th>
						<th class="py-2 px-3 font-medium text-right">{{ __("Runs") }}</th>
						<th class="py-2 px-3 font-medium text-right">P50</th>
						<th class="py-2 px-3 font-medium text-right">P95</th>
						<th class="py-2 px-3 font-medium text-right whitespace-nowrap text-gray-900">
							{{ __("Total agent time") }}
							<FeatherIcon
								name="arrow-down"
								class="inline w-3 h-3"
							/>
						</th>
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
								class="px-6 pb-4 pt-1"
							>
								<PerformanceReportTableDetail
									:element="element"
									:detail="detail(element.key)"
									:remaining="moreCount(element.key)"
									:prior-days="priorDays"
									@more="load(element, true)"
								/>
							</td>
						</tr>
					</template>
				</tbody>
				<tfoot>
					<tr class="border-t border-gray-200 text-sm font-semibold text-gray-900">
						<td></td>
						<td class="py-3 px-3">
							{{ __("All") }}
							<span class="ml-2 text-xs font-normal text-gray-500">{{ fmtInt(elements.length) }} {{ __("elements") }}</span>
						</td>
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
import { FeatherIcon } from "frappe-ui"
import DeltaPill from "@/components/Insights/DeltaPill/DeltaPill.vue"
import PerformanceReportTableDetail from "@/components/Insights/PerformanceReportTableDetail/PerformanceReportTableDetail.vue"
import { fmtDuration, fmtInt } from "@/utils/formatters"

const props = defineProps({
	elements: { type: Array, required: true },
	summary: { type: Object, required: true },
	groupBy: { type: String, default: "model" },
	elementRuns: { type: Object, required: true },
	priorDays: { type: Number, default: 0 },
})

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s
const { entry: detail, load, remaining: moreCount, toggle, isExpanded } = props.elementRuns

const seriesLabel = computed(() => (props.groupBy === "agent" ? __("AI Agent") : __("Model")))
</script>

<style scoped>
</style>
