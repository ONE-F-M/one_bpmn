<template>
	<div class="border-t pt-3">
		<div class="flex items-center justify-between mb-2">
			<span class="text-sm font-semibold text-gray-700">Expected tool calls</span>
			<Button variant="subtle" icon-left="plus" @click="addExpectedCall">Add call</Button>
		</div>
		<p class="text-xs text-gray-500 mb-2">
			One row per thing to check. Rows sharing a Call number describe the same call — give a
			tool and, if the arguments matter, one row per argument. Leave the argument blank to
			require only that the tool ran.
		</p>
		<p v-if="!caseForm.expected_tool_calls.length" class="text-xs text-amber-600 mb-2">
			The tool_calls assertion has nothing to check until you add a call.
		</p>
		<div
			v-for="(e, i) in caseForm.expected_tool_calls"
			:key="i"
			class="flex items-end gap-2 mb-2"
		>
			<FormControl v-model="e.call_order" type="number" label="Call" class="w-16" />
			<FormControl v-model="e.tool_name" label="Tool" class="flex-1" />
			<FormControl v-model="e.argument" label="Argument" class="flex-1" />
			<FormControl
				v-model="e.matcher"
				type="select"
				label="Matcher"
				:options="MATCHERS"
				class="w-28"
			/>
			<FormControl v-model="e.expected_value" label="Expected value" class="flex-1" />
			<Button variant="ghost" icon-left="trash-2" @click="removeExpectedCall(i)" />
		</div>
	</div>
</template>

<script setup>
import { inject } from "vue";
import { Button, FormControl } from "frappe-ui";
import { MATCHERS } from "@/utils/evalLabels";
import { EVAL_SUITE_KEY } from "@/composables/useEvalSuiteState";

const { caseForm, addExpectedCall, removeExpectedCall } = inject(EVAL_SUITE_KEY);
</script>
