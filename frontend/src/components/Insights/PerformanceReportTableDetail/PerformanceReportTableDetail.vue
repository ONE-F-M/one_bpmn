<template>
	<div class="rounded-lg border border-gray-200 p-4 space-y-4">
		<dl class="flex flex-wrap gap-x-8 gap-y-2">
			<div
				v-for="fact in facts"
				:key="fact.label"
			>
				<dt :class="LABEL">{{ fact.label }}</dt>
				<dd class="text-sm font-semibold text-gray-900">{{ fact.value }}</dd>
			</div>
		</dl>
		<ErrorMessage
			v-if="detail.error"
			:message="detail.error"
		/>
		<template v-if="detail.split">
			<div>
				<div
					class="mb-1.5"
					:class="LABEL"
				>
					{{ __("Where the time goes") }}
				</div>
				<PerformanceReportSplitBar :split="detail.split" />
			</div>
			<table class="w-full table-fixed text-sm">
				<colgroup>
					<col>
					<col class="w-28">
					<col class="w-20">
					<col class="w-20">
					<col class="w-20">
				</colgroup>
				<thead>
					<tr class="border-b border-gray-200 text-left">
						<th :class="HEAD">{{ __("Top steps by time") }}</th>
						<th :class="HEAD">{{ __("Kind") }}</th>
						<th :class="[HEAD, 'text-right']">{{ __("Share") }}</th>
						<th :class="[HEAD, 'text-right']">{{ __("Avg") }}</th>
						<th :class="[HEAD, 'text-right']">{{ __("Max") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr
						v-for="step in detail.steps"
						:key="`${step.step_kind}|${step.agent_configuration}`"
						class="border-b border-gray-100 last:border-0"
					>
						<td
							class="py-2 pr-3 truncate"
							:title="step.step_kind"
						>
							<span class="font-semibold text-gray-900">{{ step.name || step.step_kind }}</span>
							<span
								v-if="step.via"
								class="ml-1.5 text-xs text-gray-500"
							>{{ __("via") }} {{ step.via }}</span>
						</td>
						<td class="py-2 pr-3 text-gray-700">{{ KINDS[step.kind] }}</td>
						<td class="py-2 text-right text-gray-700">{{ fmtPct(step.share, 0) }}</td>
						<td class="py-2 text-right text-gray-700">{{ fmtDuration(step.avg_ms) }}</td>
						<td class="py-2 text-right text-gray-700">{{ fmtDuration(step.max_ms) }}</td>
					</tr>
				</tbody>
			</table>
			<div>
				<div
					class="mb-1"
					:class="LABEL"
				>
					{{ __("Slowest runs above P95") }} · {{ fmtInt(detail.total) }}
				</div>
				<table class="w-full table-fixed text-sm">
					<colgroup>
						<col class="w-36">
						<col class="w-24">
						<col class="w-16">
						<col class="w-40">
						<col>
						<col class="w-20">
					</colgroup>
					<thead>
						<tr class="border-b border-gray-200 text-left">
							<th :class="HEAD">{{ __("When") }}</th>
							<th :class="[HEAD, 'text-right']">{{ __("Agent time") }}</th>
							<th :class="[HEAD, 'text-right']">{{ __("Steps") }}</th>
							<th :class="[HEAD, 'pl-6']">{{ __("Status") }}</th>
							<th :class="HEAD">{{ __("Slowest step") }}</th>
							<th></th>
						</tr>
					</thead>
					<tbody>
						<tr
							v-for="run in detail.runs"
							:key="run.name"
							class="border-b border-gray-100 last:border-0"
						>
							<td class="py-2 pr-3 text-gray-700 whitespace-nowrap">{{ runTime(run) }}</td>
							<td class="py-2 text-right font-semibold text-gray-900">{{ fmtDuration(run.agent_latency_ms) }}</td>
							<td class="py-2 text-right text-gray-700">{{ fmtInt(run.step_count) }}</td>
							<td class="py-2 pl-6 pr-3 truncate">
								<span
									class="rounded px-1.5 py-0.5 text-[11px] font-medium whitespace-nowrap"
									:class="statusTone(run)"
								>{{ runStatus(run) }}</span>
							</td>
							<td
								class="py-2 pr-3 truncate text-gray-700"
								:title="slowestStep(run)"
							>
								{{ slowestStep(run) }}
							</td>
							<td class="py-2 text-right whitespace-nowrap">
								<a
									:href="`/processa/runs/${run.name}`"
									target="_blank"
									rel="noopener"
									class="font-semibold text-blue-600 hover:underline"
									@click.stop
								>{{ __("Open run") }}</a>
							</td>
						</tr>
					</tbody>
				</table>
			</div>
		</template>
		<LoadingIndicator
			v-if="detail.loading"
			class="w-4 h-4 text-gray-400"
		/>
		<button
			v-if="canShowMore"
			class="text-xs text-gray-500"
			@click.stop="emit('more')"
		>
			{{ fmtInt(remaining) }} {{ __("more") }}, <span class="text-blue-600">{{ __("show") }}</span>
		</button>
	</div>
</template>

<script setup>
import { computed } from "vue"
import { ErrorMessage, LoadingIndicator } from "frappe-ui"
import { dayjs } from "@/dayjs"
import PerformanceReportSplitBar from "@/components/Insights/PerformanceReportSplitBar/PerformanceReportSplitBar.vue"
import { fmtDuration, fmtInt, fmtPct } from "@/utils/formatters"

const props = defineProps({
	element: { type: Object, required: true },
	detail: { type: Object, required: true },
	remaining: { type: Number, default: 0 },
	priorDays: { type: Number, default: 0 },
})
const emit = defineEmits(["more"])

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s

const LABEL = "text-[10px] uppercase tracking-wide text-gray-500 font-medium"
const HEAD = `${LABEL} py-1.5 pr-3`
const KINDS = { model: __("Model call"), tool: __("Tool"), sub_call: __("Sub-call") }

const canShowMore = computed(() => props.remaining > 0 && !props.detail.loading)

const facts = computed(() => {
	const element = props.element
	const previous = element.previous_p95_ms === null ? __("new") : fmtDuration(element.previous_p95_ms)
	const prior = props.priorDays ? `${__("P95 vs prior")} ${props.priorDays}d` : __("P95 vs prior")
	return [
		{ label: __("Avg"), value: fmtDuration(element.avg_ms) },
		{ label: __("Max"), value: fmtDuration(element.max_ms) },
		{ label: __("Avg steps"), value: element.avg_steps },
		{ label: __("Errored runs"), value: `${fmtInt(element.error_runs)} ${__("of")} ${fmtInt(element.runs)}` },
		{
			label: __("Human wait"),
			value: `${fmtInt(element.human_wait_runs)} ${__("runs")} · ${__("avg")} ${fmtDuration(element.avg_human_wait_ms)}`,
		},
		{ label: prior, value: `${previous} ${__("to")} ${fmtDuration(element.p95_ms)}` },
	]
})

function runTime(run) {
	return dayjs(run.started_at).format("MMM D, HH:mm")
}

function statusTone(run) {
	return run.status === "Error" ? "bg-red-50 text-red-700" : "bg-green-50 text-green-700"
}

function runStatus(run) {
	return run.status === "Error" ? `${__("Error")} · ${run.error_code}` : __("Success")
}

function slowestStep(run) {
	const step = run.slowest_step
	return step ? `${step.name || step.label} ${fmtDuration(step.latency_ms)}` : ""
}
</script>

<style scoped>
</style>
