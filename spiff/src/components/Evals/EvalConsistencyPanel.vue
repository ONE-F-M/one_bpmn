<template>
	<div class="bg-white rounded-lg shadow-sm mb-6">
		<div class="border-b px-4 sm:px-6 py-3 flex items-center justify-between gap-2">
			<span class="text-sm font-semibold text-gray-700">
				Consistency
				<span class="text-gray-400 font-normal"
					>({{ consistency.runs?.length || 0 }} run(s) this week)</span
				>
			</span>
			<Button
				variant="subtle"
				icon-left="activity"
				:loading="loadingConsistency"
				@click="loadConsistency"
			>
				{{ consistency.cases ? "Refresh" : "Show" }}
			</Button>
		</div>
		<div
			v-if="consistency.cases && !consistency.cases.length"
			class="p-6 text-sm text-gray-500"
		>
			No results recorded yet — run the suite once.
		</div>
		<div v-else-if="consistency.cases" class="p-4 overflow-x-auto">
			<p v-if="!flakyCases.length" class="text-sm text-green-700">
				Every case has agreed with itself across these runs.
			</p>
			<table v-else class="w-full text-sm">
				<thead>
					<tr class="text-left text-xs uppercase tracking-wide text-gray-500 border-b">
						<th class="px-3 py-2 font-medium">Case</th>
						<th class="px-3 py-2 font-medium text-right">Consistency</th>
						<th class="px-3 py-2 font-medium">History (oldest → newest)</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="c in flakyCases" :key="c.case" class="border-b border-gray-100">
						<td class="px-3 py-2 font-medium text-gray-900">{{ c.title }}</td>
						<td
							class="px-3 py-2 text-right"
							:class="c.consistency_rate < 100 ? 'text-amber-700' : 'text-gray-600'"
						>
							{{ round1(c.consistency_rate) }}%
							<span class="text-xs text-gray-400"
								>({{ c.passes }}/{{ c.executions }})</span
							>
						</td>
						<td class="px-3 py-2">
							<span
								v-for="h in c.history"
								:key="h.run"
								class="inline-block w-6 h-6 mr-1 rounded text-center text-xs leading-6"
								:class="
									h.passes === h.runs
										? 'bg-green-100 text-green-700'
										: h.passes
											? 'bg-amber-100 text-amber-700'
											: 'bg-red-100 text-red-700'
								"
								:title="`${h.run} — ${h.passes}/${h.runs} passed`"
								>{{ h.passes }}/{{ h.runs }}</span
							>
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>
</template>

<script setup>
import { inject } from "vue";
import { Button } from "frappe-ui";
import { round1 } from "@/utils/evalFormat";
import { EVAL_SUITE_KEY } from "@/composables/useEvalSuiteState";

const { consistency, flakyCases, loadingConsistency, loadConsistency } = inject(EVAL_SUITE_KEY);
</script>
