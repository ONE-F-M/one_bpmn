<template>
	<div class="space-y-2">
		<div class="flex flex-wrap items-baseline gap-x-3">
			<h3 class="text-sm font-semibold text-gray-900">{{ __("What is failing") }}</h3>
			<span class="text-xs text-gray-500">{{ __("one row per error type and element · click a row for details and runs") }}</span>
		</div>
		<div class="overflow-x-auto bg-white rounded-lg border border-gray-200">
			<table class="w-full min-w-[800px] table-fixed">
				<colgroup>
					<col class="w-8">
					<col class="w-[22%]">
					<col>
					<col class="w-24">
					<col class="w-40">
					<col class="w-28">
				</colgroup>
				<thead>
					<tr class="border-b border-gray-200 text-left text-xs uppercase tracking-wide text-gray-500">
						<th></th>
						<th class="py-2 px-3 font-medium">{{ __("Error type") }}</th>
						<th class="py-2 px-3 font-medium">{{ __("Element") }}</th>
						<th class="py-2 px-3 font-medium text-right">{{ __("Errors") }}</th>
						<th class="py-2 px-3 font-medium text-right">{{ __("Error rate") }}</th>
						<th class="py-2 px-3 font-medium">{{ __("Last seen") }}</th>
					</tr>
				</thead>
				<tbody>
					<template
						v-for="issue in issues"
						:key="issue.key"
					>
						<tr
							class="border-b border-gray-100 cursor-pointer hover:bg-gray-50"
							@click="toggle(issue.key)"
						>
							<td class="py-3 pl-3">
								<FeatherIcon
									:name="expanded === issue.key ? 'chevron-down' : 'chevron-right'"
									class="w-4 h-4 text-gray-400"
								/>
							</td>
							<td class="py-3 px-3 whitespace-nowrap overflow-hidden text-ellipsis">
								<span class="font-mono text-sm text-gray-900">{{ issue.error_code }}</span>
								<span
									v-if="issue.is_new"
									class="ml-2 rounded-full bg-blue-50 text-blue-700 px-1.5 text-[10px]"
								>{{ __("new") }}</span>
							</td>
							<td
								class="py-3 px-3 whitespace-nowrap overflow-hidden text-ellipsis"
								:title="`${issue.bpmn_label} · ${issue.process_model}`"
							>
								<span class="text-sm font-semibold text-gray-900">{{ issue.bpmn_label }}</span>
								<span class="ml-2 text-xs text-gray-500">{{ issue.process_model }}</span>
							</td>
							<td class="py-3 px-3 text-right text-sm font-semibold text-gray-900">{{ fmtInt(issue.errors) }}</td>
							<td class="py-3 px-3 text-right whitespace-nowrap text-sm">
								<span
									class="font-semibold"
									:class="errorRateClass(issue.error_rate)"
								>{{ fmtPct(issue.error_rate) }}</span>
								<span class="ml-1 text-xs text-gray-500">{{ __("of") }} {{ fmtInt(issue.runs) }}</span>
							</td>
							<td
								class="py-3 px-3 whitespace-nowrap text-sm"
								:class="isRecent(issue.last_seen) ? 'font-semibold text-gray-900' : 'text-gray-600'"
							>
								{{ lastSeenText(issue.last_seen, __) }}
							</td>
						</tr>
						<tr
							v-if="expanded === issue.key"
							class="border-b border-gray-100"
						>
							<td
								colspan="6"
								class="px-6 pb-4 pt-1"
							>
								<dl class="flex flex-wrap gap-x-8 gap-y-2 mb-3">
									<div
										v-for="fact in facts(issue)"
										:key="fact.label"
									>
										<dt class="text-[10px] uppercase tracking-wide text-gray-500 font-medium">{{ fact.label }}</dt>
										<dd
											class="text-sm font-semibold"
											:class="fact.class || 'text-gray-900'"
										>
											{{ fact.value }}
										</dd>
									</div>
								</dl>
								<div class="text-[10px] uppercase tracking-wide text-gray-500 font-medium mb-1">{{ __("Latest failed runs") }}</div>
								<div class="border-l-2 border-gray-200 pl-3 space-y-1">
									<div
										v-for="run in runsFor(issue.key).runs"
										:key="run.name"
										class="grid grid-cols-[8rem_1fr_5rem_4rem_5rem] items-center gap-3 text-sm"
									>
										<span class="text-gray-700 whitespace-nowrap">{{ dayjs(run.started_at).format("MMM D HH:mm") }}</span>
										<span
											class="font-mono text-xs text-gray-600 truncate"
											:title="run.error_message"
										>{{ run.error_message }}</span>
										<span class="text-right text-gray-600 whitespace-nowrap">{{ retriesText(run.retry_count) }}</span>
										<span class="text-right text-gray-600">{{ fmtDuration(run.duration_ms) }}</span>
										<a
											:href="`/app/ai-agent-run/${run.name}`"
											target="_blank"
											rel="noopener"
											class="text-right text-blue-600 hover:underline whitespace-nowrap"
											@click.stop
										>{{ __("Open run") }}</a>
									</div>
									<LoadingIndicator
										v-if="runsFor(issue.key).loading"
										class="w-4 h-4 text-gray-400"
									/>
									<ErrorMessage
										v-if="runsFor(issue.key).error"
										:message="runsFor(issue.key).error"
									/>
									<button
										v-if="moreCount(issue.key) > 0 && !runsFor(issue.key).loading"
										class="text-xs text-gray-500 py-1"
										@click.stop="load(issue.key, true)"
									>
										{{ moreCount(issue.key) }} {{ __("more") }} · <span class="text-blue-600">{{ __("show") }}</span>
									</button>
								</div>
							</td>
						</tr>
					</template>
				</tbody>
				<tfoot>
					<tr class="border-t border-gray-200 text-sm font-semibold text-gray-900">
						<td></td>
						<td class="py-3 px-3">{{ __("All") }}</td>
						<td class="py-3 px-3">{{ fmtInt(summary.affected_elements) }} {{ __("of") }} {{ fmtInt(summary.elements_with_runs) }} {{ __("elements affected") }}</td>
						<td class="py-3 px-3 text-right">{{ fmtInt(summary.errors) }}</td>
						<td class="py-3 px-3 text-right whitespace-nowrap">
							{{ fmtPct(summary.error_rate) }}
							<span class="ml-1 text-xs font-normal text-gray-500">{{ __("of") }} {{ fmtInt(summary.runs) }}</span>
						</td>
						<td></td>
					</tr>
				</tfoot>
			</table>
		</div>
	</div>
</template>

<script setup>
import { ErrorMessage, FeatherIcon, LoadingIndicator } from "frappe-ui"
import { dayjs } from "@/dayjs"
import { errorRateClass, isRecent, lastSeenText } from "@/composables/useIssueRuns"
import { fmtDelta, fmtDuration, fmtInt, fmtPct } from "@/utils/formatters"

const props = defineProps({
	issues: { type: Array, required: true },
	summary: { type: Object, required: true },
	groupBy: { type: String, default: "model" },
	issueRuns: { type: Object, required: true },
})

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s
const { entry: runsFor, load, remaining: moreCount, toggle, expanded } = props.issueRuns

function retriesText(count) {
	if (!count) return ""
	return count === 1 ? __("1 retry") : `${count} ${__("retries")}`
}

function facts(issue) {
	return [
		{ label: props.groupBy === "agent" ? __("AI Agent") : __("Model"), value: issue.series || "-" },
		{ label: __("First seen"), value: dayjs(issue.first_seen).format("MMM D") },
		{ label: __("Retried"), value: fmtInt(issue.retried) },
		{ label: __("Recovered by retry"), value: fmtInt(issue.retry_recovered) },
		{ label: __("P95 duration"), value: fmtDuration(issue.p95_duration_ms) },
		{
			label: __("vs prior period"),
			value: issue.delta_pt === null ? __("new") : fmtDelta(issue.delta_pt, "pt"),
			class: issue.delta_pt > 0 ? "text-red-600" : issue.delta_pt < 0 ? "text-green-600" : "text-gray-900",
		},
	]
}
</script>
