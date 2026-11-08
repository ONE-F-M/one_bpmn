<template>
	<div class="bg-white rounded-lg shadow-sm">
		<div class="border-b px-4 sm:px-6 py-3 flex items-center justify-between gap-2 text-sm">
			<span class="font-semibold text-gray-700">Recent runs</span>
			<FormControl
				v-model="runsPageLength"
				type="select"
				:options="PAGE_SIZES"
				class="w-20"
				@change="loadRunsPage(0)"
			/>
		</div>
		<div v-if="!runs.length" class="p-8 text-center text-sm text-gray-500">No runs yet.</div>
		<table v-else class="w-full text-sm">
			<tbody>
				<tr
					v-for="r in runs"
					:key="r.name"
					class="border-b border-gray-100 hover:bg-gray-50"
				>
					<td class="px-4 sm:px-6 py-3">
						<router-link
							:to="`/processa/evals/run/${encodeURIComponent(r.name)}`"
							class="text-gray-900 hover:underline"
						>
							{{ r.display_title || r.name }}
						</router-link>
						<!-- Only replay is marked: labelling the usual live runs would bury the one distinction that matters. -->
						<span
							v-if="r.backend === 'replay'"
							class="ml-2 inline-block px-2 py-0.5 rounded-full text-xs bg-amber-50 text-amber-700"
							title="Assertions were re-checked against each case's stored answer — the agent was not called"
							>replay</span
						>
						<div class="sm:hidden text-xs text-gray-500 mt-0.5">
							{{ r.case_label }}
						</div>
					</td>
					<td
						class="hidden sm:table-cell px-6 py-3 text-gray-600"
						:title="(r.case_names || []).join(', ')"
					>
						{{ r.case_label }}
					</td>
					<td class="px-2 sm:px-6 py-3">
						<span
							class="inline-block px-2 py-0.5 rounded-full text-xs"
							:class="runPill(r.status)"
							>{{ r.status }}</span
						>
					</td>
					<td class="px-2 sm:px-6 py-3 text-gray-600 text-right sm:text-left">
						{{ r.passed_cases }}/{{ r.total_cases }} passed
						<span
							v-if="r.total_executions > r.total_cases"
							class="text-xs text-gray-400"
						>
							· {{ round1(r.pass_rate) }}% of {{ r.total_executions }}
						</span>
					</td>
					<td class="hidden sm:table-cell px-6 py-3 text-gray-400 text-xs">
						{{ r.started_at }}
					</td>
				</tr>
			</tbody>
		</table>
		<div
			v-if="totalRuns"
			class="border-t px-4 sm:px-6 py-2 flex items-center justify-between text-sm text-gray-600"
		>
			<span>{{ runsRangeLabel }}</span>
			<div class="flex gap-2">
				<Button
					size="sm"
					:disabled="runsStart === 0"
					@click="loadRunsPage(runsStart - runsPageLength)"
					>Previous</Button
				>
				<Button
					size="sm"
					:disabled="runsStart + runs.length >= totalRuns"
					@click="loadRunsPage(runsStart + runsPageLength)"
					>Next</Button
				>
			</div>
		</div>
	</div>
</template>

<script setup>
import { inject } from "vue";
import { Button, FormControl } from "frappe-ui";
import { round1, runPill } from "@/utils/evalFormat";
import { PAGE_SIZES } from "@/utils/evalLabels";
import { EVAL_SUITE_KEY } from "@/composables/useEvalSuiteState";

const { runs, totalRuns, runsStart, runsPageLength, runsRangeLabel, loadRunsPage } =
	inject(EVAL_SUITE_KEY);
</script>
