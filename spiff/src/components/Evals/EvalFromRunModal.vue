<template>
	<Dialog v-model="showFromRun" :options="{ title: 'Create case from a run' }">
		<template #body-content>
			<div class="space-y-3">
				<p v-if="loadingAgentRuns" class="text-sm text-gray-500">Loading runs…</p>
				<p v-else-if="!agentRuns.length" class="text-sm text-gray-500">
					No runs to build a case from yet — this suite's agent has not run outside the
					eval system.
				</p>
				<FormControl
					v-else
					v-model="fromRun.run_name"
					type="select"
					label="AI Agent Run"
					:options="agentRunOptions"
					@change="onRunPicked"
				/>
				<p v-if="loadingSteps" class="text-xs text-gray-500">Loading steps…</p>
				<FormControl
					v-if="runSteps.length"
					v-model="fromRun.step_name"
					type="select"
					label="Step (optional)"
					:options="stepOptions"
				/>
			</div>
		</template>
		<template #actions>
			<Button variant="solid" :loading="savingFromRun" @click="createFromRun"
				>Create case</Button
			>
		</template>
	</Dialog>
</template>

<script setup>
import { inject } from "vue";
import { Button, Dialog, FormControl } from "frappe-ui";
import { EVAL_SUITE_KEY } from "@/composables/useEvalSuiteState";

const {
	showFromRun,
	loadingAgentRuns,
	agentRuns,
	agentRunOptions,
	fromRun,
	onRunPicked,
	loadingSteps,
	runSteps,
	stepOptions,
	savingFromRun,
	createFromRun,
} = inject(EVAL_SUITE_KEY);
</script>
