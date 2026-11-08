<template>
	<div class="border-t pt-3">
		<div class="flex items-center justify-between mb-2">
			<span class="text-sm font-semibold text-gray-700">Assertions</span>
			<Button variant="subtle" icon-left="plus" @click="addAssertion">Add assertion</Button>
		</div>
		<p v-if="!caseForm.assertions.length" class="text-xs text-amber-600 mb-2">
			A case with no assertions is marked Invalid and fails its suite. Add at least one.
		</p>
		<div
			v-for="(a, i) in caseForm.assertions"
			:key="i"
			class="border border-gray-100 rounded-md p-3 mb-2 space-y-2"
		>
			<div class="flex items-center gap-2">
				<FormControl
					v-model="a.assertion_type"
					type="select"
					:options="ASSERTION_TYPES"
					class="w-40"
				/>
				<Button variant="ghost" icon-left="trash-2" @click="removeAssertion(i)" />
			</div>
			<FormControl
				v-if="a.assertion_type === 'tool_calls'"
				v-model="a.value"
				type="select"
				label="Order mode"
				:options="TOOL_CALL_MODES"
			/>
			<FormControl
				v-else
				v-model="a.value"
				type="textarea"
				:label="VALUE_LABELS[a.assertion_type] || 'Expected value / pattern'"
			/>
			<div v-if="a.assertion_type === 'llm_judge'" class="grid grid-cols-3 gap-2">
				<FormControl
					v-model="a.judge_provider"
					type="select"
					label="Judge provider"
					:options="providerOptions"
				/>
				<FormControl
					v-model="a.judge_model"
					type="select"
					label="Judge model"
					:options="aiModelOptions"
				/>
				<FormControl
					v-model="a.pass_threshold"
					type="number"
					label="Pass threshold (1–5)"
				/>
			</div>
		</div>
	</div>
</template>

<script setup>
import { inject } from "vue";
import { Button, FormControl } from "frappe-ui";
import { ASSERTION_TYPES, TOOL_CALL_MODES, VALUE_LABELS } from "@/utils/evalLabels";
import { EVAL_SUITE_KEY } from "@/composables/useEvalSuiteState";

const { caseForm, providerOptions, aiModelOptions, addAssertion, removeAssertion } =
	inject(EVAL_SUITE_KEY);
</script>
