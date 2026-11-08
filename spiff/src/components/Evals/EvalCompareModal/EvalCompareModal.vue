<template>
	<Dialog v-model="showCompare" :options="{ title: 'Compare against another agent' }">
		<template #body-content>
			<div class="space-y-4">
				<p class="text-sm text-gray-600">
					Runs all {{ cases.length }} case{{ cases.length === 1 ? "" : "s" }} twice —
					once against
					<span class="font-medium">{{
						suite.agent_name || suite.agent_configuration || "this suite's agent"
					}}</span
					>, once against the agent you pick — then shows the two side by side. This
					suite stays assigned to its current agent.
				</p>
				<FormControl
					v-model="challenger"
					type="select"
					label="Compare against"
					:options="challengerOptions"
				/>
				<p v-if="cases.length < 10" class="text-xs text-amber-700 bg-amber-50 rounded p-2">
					{{ cases.length }} case{{ cases.length === 1 ? "" : "s" }} is a small sample —
					one case changing its mind moves the pass rate by
					{{ Math.round(100 / cases.length) }} points. Useful as a signal, not as proof.
				</p>
				<p v-if="compareError" class="text-sm text-red-600">{{ compareError }}</p>
			</div>
		</template>
		<template #actions>
			<Button
				variant="solid"
				:loading="startingCompare"
				:disabled="!challenger"
				@click="startComparison"
				>Run both</Button
			>
		</template>
	</Dialog>
</template>

<script setup>
import { inject } from "vue";
import { Button, Dialog, FormControl } from "frappe-ui";
import { EVAL_SUITE_KEY } from "@/composables/useEvalSuiteState";

const {
	suite,
	cases,
	showCompare,
	challenger,
	challengerOptions,
	startingCompare,
	compareError,
	startComparison,
} = inject(EVAL_SUITE_KEY);
</script>
