<template>
	<Dialog
		v-model="showThresholds"
		:options="{ title: 'When this suite runs, and the bar it must clear' }"
	>
		<template #body-content>
			<div class="space-y-3">
				<FormControl
					v-model="thresholdForm.ci_role"
					type="select"
					label="Run automatically as"
					:options="CI_ROLE_OPTIONS"
					description="Smoke runs on every pull request touching agent code and makes no model call. Nightly is the live sweep on a schedule. Blank means it runs only when a person asks."
				/>
				<p
					v-if="thresholdForm.ci_role === 'Smoke' && smokeUncheckableCases.length"
					class="text-sm text-amber-600"
				>
					{{ smokeUncheckableCases.length }} of {{ cases.length }} case(s) here can only
					be judged by a model, so a Smoke run would skip them. A suite where every case
					is skipped fails the check.
				</p>
				<p v-if="thresholdForm.ci_role === 'Nightly'" class="text-xs text-gray-500">
					Nightly calls the agents for real. The ceiling on what one night may spend is
					in Processa Settings.
				</p>
				<FormControl
					v-model="thresholdForm.pass_k"
					type="number"
					label="Runs per case"
					description="Above 1, a case passes only when every one of its runs passes. Every run is a billed model call."
				/>
				<FormControl
					v-model="thresholdForm.min_pass_rate"
					type="number"
					label="Minimum pass rate (%)"
					description="The share of executions that must pass. Above 0, activating this suite's map is refused below it."
				/>
				<label class="flex items-start gap-2 text-sm text-gray-700">
					<input v-model="thresholdForm.gate_deployment" type="checkbox" class="mt-1" />
					<span>
						<span class="font-medium">Block deployment below the rate</span>
						<span class="block text-xs text-gray-500">
							Deploying {{ suite.process_model || "this suite's map" }} is refused
							while this suite is under its minimum. With the minimum at 0 it only
							warns.
						</span>
					</span>
				</label>
				<p v-if="thresholdError" class="text-sm text-red-600">{{ thresholdError }}</p>
				<p
					v-if="thresholdForm.gate_deployment && !suite.process_model"
					class="text-sm text-amber-600"
				>
					This suite names no process map, so there is nothing for the gate to block.
				</p>
				<p
					v-if="Number(thresholdForm.pass_k) > 1 && cases.length"
					class="text-xs text-gray-500"
				>
					{{ cases.length }} case(s) × {{ thresholdForm.pass_k }} =
					{{ cases.length * Number(thresholdForm.pass_k) }}
					executions per run of this suite.
				</p>
			</div>
		</template>
		<template #actions>
			<Button variant="solid" :loading="savingThresholds" @click="saveThresholds"
				>Save</Button
			>
		</template>
	</Dialog>
</template>

<script setup>
import { inject } from "vue";
import { Button, Dialog, FormControl } from "frappe-ui";
import { CI_ROLE_OPTIONS } from "@/utils/evalLabels";
import { EVAL_SUITE_KEY } from "@/composables/Eval/useEvalSuiteState";

const {
	suite,
	cases,
	showThresholds,
	thresholdForm,
	thresholdError,
	savingThresholds,
	smokeUncheckableCases,
	saveThresholds,
} = inject(EVAL_SUITE_KEY);
</script>
