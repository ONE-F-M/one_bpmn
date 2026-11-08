<template>
	<div class="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-4">
		<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-blue-500">
			<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">Cases</div>
			<div class="text-2xl font-bold text-gray-900">{{ metrics.cases ?? 0 }}</div>
		</div>
		<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-indigo-500">
			<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">Runs</div>
			<div class="text-2xl font-bold text-gray-900">{{ metrics.runs ?? 0 }}</div>
		</div>
		<div
			class="bg-white rounded-lg shadow-sm p-4 border-l-4"
			:class="
				metrics.latest?.status === 'Passed'
					? 'border-green-500'
					: metrics.latest
						? 'border-red-500'
						: 'border-gray-300'
			"
		>
			<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">Latest run</div>
			<div class="text-base font-bold text-gray-900">
				{{
					metrics.latest
						? `${metrics.latest.status} · ${metrics.latest.passed}/${metrics.latest.total}`
						: "—"
				}}
			</div>
		</div>
		<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-green-500">
			<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">Pass rate</div>
			<div class="text-2xl font-bold text-gray-900">
				{{ metrics.pass_rate != null ? metrics.pass_rate + "%" : "—" }}
			</div>
			<svg
				v-if="sparkPoints"
				viewBox="0 0 100 20"
				preserveAspectRatio="none"
				class="w-full h-5 mt-1"
			>
				<polyline
					:points="sparkPoints"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					class="text-green-500"
				/>
			</svg>
		</div>
		<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-amber-500">
			<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">
				Tokens (latest)
			</div>
			<div class="text-2xl font-bold text-gray-900">
				{{ fmt(metrics.latest_tokens ?? 0) }}
			</div>
		</div>
		<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-purple-500">
			<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">
				Cost (latest)
			</div>
			<div class="text-2xl font-bold text-gray-900">
				{{ fmtCost(metrics.latest_cost ?? 0) }}
			</div>
		</div>
		<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-rose-500">
			<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">
				Pass rate (latest)
			</div>
			<div class="text-2xl font-bold" :class="rateColour">
				{{ metrics.latest?.executions ? `${round1(metrics.latest.pass_rate)}%` : "—" }}
			</div>
			<div v-if="metrics.latest?.executions" class="text-xs text-gray-500">
				{{ metrics.latest.executions }} execution(s)<span v-if="suite.min_pass_rate"
					>, needs {{ suite.min_pass_rate }}%</span
				>
			</div>
		</div>
		<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-cyan-500">
			<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">
				Assertion coverage
			</div>
			<div class="text-2xl font-bold text-gray-900">
				{{ metrics.assertion_coverage?.with_assertions ?? 0 }} /
				{{ metrics.assertion_coverage?.total ?? 0 }}
			</div>
		</div>
	</div>
</template>

<script setup>
import { inject } from "vue";
import { fmt, fmtCost, round1 } from "@/utils/evalFormat";
import { EVAL_SUITE_KEY } from "@/composables/useEvalSuiteState";

const { metrics, suite, sparkPoints, rateColour } = inject(EVAL_SUITE_KEY);
</script>
