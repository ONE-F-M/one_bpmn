<template>
	<div class="space-y-2">
		<div class="flex flex-wrap items-baseline gap-x-2">
			<h3 class="text-sm font-semibold text-gray-900">{{ __("What is failing") }}</h3>
			<span class="text-xs text-gray-500">{{ __("tap a row to open its runs") }}</span>
			<span class="ml-auto flex gap-3 text-xs text-gray-500">
				<button
					class="hover:text-gray-900"
					@click="setAll(visibleIssues.map((i) => i.key))"
				>{{ __("Expand all") }}</button>
				<button
					class="hover:text-gray-900"
					@click="setAll([])"
				>{{ __("Collapse all") }}</button>
			</span>
		</div>
		<div
			v-for="issue in visibleIssues"
			:key="issue.key"
			class="bg-white rounded-lg border border-gray-200 p-3"
			@click="toggle(issue.key)"
		>
			<div class="flex items-center justify-between gap-3">
				<span class="font-mono text-sm text-gray-900 truncate">
					{{ issue.error_code }}
					<span
						v-if="issue.is_new"
						class="ml-1 rounded-full bg-blue-50 text-blue-700 px-1.5 text-[10px] font-sans"
					>{{ __("new") }}</span>
				</span>
				<span class="text-sm font-semibold text-gray-900">{{ fmtInt(issue.errors) }}</span>
			</div>
			<div class="text-sm font-semibold text-gray-900 truncate mt-1">{{ issue.bpmn_label }}</div>
			<div class="text-xs mt-1">
				<span
					class="font-semibold"
					:class="errorRateClass(issue.error_rate)"
				>{{ fmtPct(issue.error_rate) }}</span>
				<span class="ml-1 text-gray-500">{{ __("error rate") }} · {{ __("last") }} {{ lastSeenText(issue.last_seen, __) }}</span>
			</div>
			<div
				v-if="isExpanded(issue.key)"
				class="mt-3 space-y-2"
			>
				<div class="text-xs text-gray-600">
					{{ groupBy === "agent" ? __("AI Agent") : __("Model") }} <span class="font-semibold text-gray-900">{{ issue.series || "-" }}</span>
					· {{ __("Since") }} <span class="font-semibold text-gray-900">{{ dayjs(issue.first_seen).format("MMM D") }}</span>
					· {{ __("Recovered") }} <span class="font-semibold text-gray-900">{{ fmtInt(issue.retry_recovered) }} {{ __("of") }} {{ fmtInt(issue.retried) }}</span> {{ __("retried") }}
				</div>
				<div
					v-for="run in runsFor(issue.key).runs"
					:key="run.name"
					class="flex items-center justify-between gap-3 text-sm"
				>
					<span class="font-semibold text-gray-900">{{ dayjs(run.started_at).format("MMM D HH:mm") }}</span>
					<span class="text-gray-600">{{ fmtDuration(run.duration_ms) }}</span>
					<a
						:href="`/processa/runs/${run.name}`"
						target="_blank"
						rel="noopener"
						class="ml-auto text-blue-600"
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
					class="text-xs text-gray-500"
					@click.stop="load(issue.key, true)"
				>
					{{ moreCount(issue.key) }} {{ __("more") }} · <span class="text-blue-600">{{ __("show") }}</span>
				</button>
			</div>
		</div>
		<button
			v-if="hiddenCount > 0"
			class="text-xs text-gray-500"
			@click="showAll = true"
		>
			{{ hiddenCount }} {{ __("more") }} · <span class="text-blue-600">{{ __("show") }}</span>
		</button>
		<div class="bg-gray-50 rounded-lg border border-gray-200 p-3">
			<div class="flex items-center justify-between text-sm font-semibold text-gray-900">
				<span>{{ __("All") }}</span>
				<span>{{ fmtInt(summary.errors) }} {{ summary.errors === 1 ? __("error") : __("errors") }}</span>
			</div>
			<div class="text-xs text-gray-500 mt-1">{{ fmtPct(summary.error_rate) }} {{ __("of") }} {{ fmtInt(summary.runs) }} {{ __("runs") }}</div>
		</div>
	</div>
</template>

<script setup>
import { computed, ref } from "vue"
import { ErrorMessage, LoadingIndicator } from "frappe-ui"
import { dayjs } from "@/dayjs"
import { errorRateClass, lastSeenText } from "@/composables/useIssueRuns"
import { fmtDuration, fmtInt, fmtPct } from "@/utils/formatters"

const props = defineProps({
	issues: { type: Array, required: true },
	summary: { type: Object, required: true },
	groupBy: { type: String, default: "model" },
	issueRuns: { type: Object, required: true },
})

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s
const { entry: runsFor, load, remaining: moreCount, toggle, isExpanded, setAll } = props.issueRuns
const FIRST_ISSUES = 4

const showAll = ref(false)
const visibleIssues = computed(() => (showAll.value ? props.issues : props.issues.slice(0, FIRST_ISSUES)))
const hiddenCount = computed(() => props.issues.length - visibleIssues.value.length)
</script>
