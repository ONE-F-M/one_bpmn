<template>
	<Dialog
		:model-value="showReassign"
		:options="{ title: 'Run this suite against', size: 'lg' }"
		@update:model-value="
			(v) => {
				if (!v) showReassign = false;
			}
		"
	>
		<template #body-content>
			<div class="space-y-4">
				<p class="text-sm text-gray-600">
					Changes which agent this suite's cases are run against. The cases, their
					assertions and every past run stay exactly as they are — a run records the
					agent it used, so the history stays readable after a reassignment.
				</p>
				<FormControl
					type="autocomplete"
					label="Agent"
					:options="reassignOptions"
					:model-value="reassignAgent"
					@update:model-value="(v) => (reassignAgent = v?.value ?? v ?? '')"
				/>
				<p class="text-xs text-gray-500">
					Every agent is listed, including Draft and Needs Attention ones — running a
					suite is how an agent earns its way to Live. Choosing "none" detaches the suite
					instead, for a template pack that is copied rather than run.
				</p>
				<ErrorMessage :message="reassignError" />
			</div>
		</template>
		<template #actions>
			<div class="flex justify-end gap-2">
				<Button variant="subtle" @click="showReassign = false">Cancel</Button>
				<Button variant="solid" :loading="savingReassign" @click="doReassign">Save</Button>
			</div>
		</template>
	</Dialog>
</template>

<script setup>
import { inject } from "vue";
import { Button, Dialog, ErrorMessage, FormControl } from "frappe-ui";
import { EVAL_SUITE_KEY } from "@/composables/Eval/useEvalSuiteState";

const { showReassign, reassignOptions, reassignAgent, reassignError, savingReassign, doReassign } =
	inject(EVAL_SUITE_KEY);
</script>
