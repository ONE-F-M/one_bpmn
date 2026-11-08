<template>
	<div class="bg-white rounded-lg shadow-sm">
		<div class="border-b px-4 sm:px-6 py-3 text-sm font-semibold text-gray-700">
			Cases <span class="text-gray-400 font-normal">({{ cases.length }})</span>
		</div>
		<div v-if="loading" class="p-6 space-y-3 animate-pulse">
			<div v-for="n in 3" :key="n" class="h-8 bg-gray-100 rounded"></div>
		</div>
		<div v-else-if="!cases.length" class="p-8 text-center text-sm text-gray-500">
			No cases yet — add one with "New case" or "From run".
		</div>
		<table v-else class="w-full text-sm">
			<thead>
				<tr class="text-left text-xs uppercase tracking-wide text-gray-500 border-b">
					<th class="px-2 sm:px-4 py-3 w-8">
						<input type="checkbox" :checked="allSelected" @change="toggleAll" />
					</th>
					<th class="px-2 sm:px-4 py-3 font-medium">Case</th>
					<th class="hidden md:table-cell px-4 py-3 font-medium">Assertions</th>
					<th class="px-2 sm:px-4 py-3 font-medium text-right">Actions</th>
				</tr>
			</thead>
			<tbody>
				<tr
					v-for="c in cases"
					:key="c.name"
					class="border-b border-gray-100 hover:bg-gray-50"
				>
					<td class="px-2 sm:px-4 py-3">
						<input v-model="selected" type="checkbox" :value="c.name" />
					</td>
					<td class="px-2 sm:px-4 py-3">
						<div class="font-medium text-gray-900">{{ c.title }}</div>
						<div v-if="c.source_run" class="text-xs text-gray-400">from run</div>
						<div class="md:hidden mt-1">
							<span
								v-for="t in c.assertion_types"
								:key="t"
								class="inline-block px-2 py-0.5 rounded-full text-xs bg-gray-100 text-gray-600 mr-1 mb-1"
								>{{ assertionTypeLabel(t) }}</span
							>
						</div>
					</td>
					<td class="hidden md:table-cell px-4 py-3">
						<span
							v-for="t in c.assertion_types"
							:key="t"
							class="inline-block px-2 py-0.5 rounded-full text-xs bg-gray-100 text-gray-600 mr-1"
							>{{ assertionTypeLabel(t) }}</span
						>
						<span v-if="!c.assertion_types.length" class="text-xs text-amber-600"
							>no assertions</span
						>
					</td>
					<td class="px-2 sm:px-4 py-3">
						<div
							class="flex flex-col sm:flex-row items-end sm:items-center justify-end gap-1 whitespace-nowrap"
						>
							<Button variant="ghost" icon-left="pencil" @click="openEditCase(c)"
								>Edit</Button
							>
							<Button
								variant="ghost"
								icon-left="refresh-cw"
								:disabled="!canRecheck"
								:loading="recheckingCase[c.name]"
								:title="
									canRecheck
										? 'Re-evaluate this case\'s assertions against its last stored answer'
										: 'Run this case once before re-checking'
								"
								@click="recheckCase(c)"
								>Re-check</Button
							>
							<Button
								icon-left="play"
								:loading="runningCase[c.name]"
								@click="runCase(c)"
								>Run</Button
							>
						</div>
					</td>
				</tr>
			</tbody>
		</table>
	</div>
</template>

<script setup>
import { inject } from "vue";
import { Button } from "frappe-ui";
import { assertionTypeLabel } from "@/utils/evalLabels";
import { EVAL_SUITE_KEY } from "@/composables/Eval/useEvalSuiteState";

const {
	loading,
	cases,
	selected,
	allSelected,
	canRecheck,
	recheckingCase,
	runningCase,
	toggleAll,
	openEditCase,
	recheckCase,
	runCase,
} = inject(EVAL_SUITE_KEY);
</script>
