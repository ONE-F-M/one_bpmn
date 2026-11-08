<template>
	<Dialog
		v-model="showCaseEditor"
		:options="{ title: caseMode === 'edit' ? 'Edit case' : 'New eval case', size: '3xl' }"
	>
		<template #body-content>
			<div class="space-y-3">
				<div class="text-xs text-gray-500">
					Tests agent:
					<span class="font-medium text-gray-700">{{
						suite.agent_name || suite.agent_configuration || "none"
					}}</span>
					— its provider, model and system prompt are used.
				</div>
				<FormControl v-model="caseForm.title" label="Title" />
				<div class="grid grid-cols-2 gap-3">
					<FormControl
						v-model="caseForm.case_type"
						type="select"
						label="Case type"
						:options="CASE_TYPE_OPTIONS"
						description="What this case measures."
					/>
					<FormControl
						v-model="caseForm.target_skill"
						type="select"
						label="Target skill (optional)"
						:options="skillOptions"
						description="A skill's golden dataset is the cases pointing at it."
					/>
				</div>
				<p v-if="caseSources.length" class="text-xs text-gray-500">
					Came from
					<template v-for="(src, i) in caseSources" :key="src.label">
						<span v-if="i">, </span>
						<router-link
							v-if="src.to"
							:to="src.to"
							class="text-blue-600 hover:underline"
						>
							{{ src.label }}
						</router-link>
						<span v-else>{{ src.label }}</span>
					</template>
				</p>
				<FormControl
					v-model="caseForm.input_user_prompt"
					type="textarea"
					:label="
						isMemoryCase
							? 'Question to recall with (leave empty for a generation-only case)'
							: 'User prompt'
					"
				/>
				<FormControl
					v-model="caseForm.expected_output"
					type="textarea"
					:label="
						isMemoryCase
							? 'Golden memories, one per line'
							: 'Expected output (optional)'
					"
				/>
				<template v-if="isMemoryCase">
					<FormControl
						v-model="caseForm.input_context"
						type="textarea"
						label="Input Context (JSON)"
						placeholder='{"scope": "Agent", "scope_key": "run_general_chat_agent", "k": 5}'
					/>
					<p
						class="text-xs"
						:class="inputContextError ? 'text-red-600' : 'text-gray-500'"
					>
						{{
							inputContextError ||
							"scope and scope_key are required. Optional: k, user, agent_output (distilled and scored), produced_memories (scored as given)."
						}}
					</p>
				</template>
				<EvalCaseContextField
					v-else
					v-model:enabled="startsMidConversation"
					v-model="caseForm.input_context"
					:suite="suiteName"
					@use-prompt="useLoadedPrompt"
				/>

				<div v-if="isMemoryCase" class="border-t pt-3 text-xs text-gray-500">
					A Memory case scores itself: recall, precision and latency come from the memory
					store. Assertions are not used.
				</div>
				<EvalAssertionFields v-else />

				<EvalExpectedToolCalls v-if="wantsToolCalls" />
			</div>
		</template>
		<template #actions>
			<div class="w-full space-y-2">
				<p v-if="caseError" class="text-sm text-red-600">{{ caseError }}</p>
				<p v-else-if="incompleteAssertion !== -1" class="text-sm text-amber-600">
					Assertion {{ incompleteAssertion + 1 }} needs its
					{{
						(
							VALUE_LABELS[
								caseForm.assertions[incompleteAssertion].assertion_type
							] || "expected value"
						).toLowerCase()
					}}.
				</p>
				<Button
					variant="solid"
					:loading="savingCase"
					:disabled="!caseForm.title || incompleteAssertion !== -1"
					@click="saveCase"
				>
					{{ caseMode === "edit" ? "Save changes" : "Create case" }}
				</Button>
			</div>
		</template>
	</Dialog>
</template>

<script setup>
import { inject } from "vue";
import { Button, Dialog, FormControl } from "frappe-ui";
import EvalAssertionFields from "@/components/Evals/EvalAssertionFields.vue";
import EvalCaseContextField from "@/components/Evals/EvalCaseContextField.vue";
import EvalExpectedToolCalls from "@/components/Evals/EvalExpectedToolCalls.vue";
import { CASE_TYPE_OPTIONS, VALUE_LABELS } from "@/utils/evalLabels";
import { EVAL_SUITE_KEY } from "@/composables/useEvalSuiteState";

const {
	suiteName,
	suite,
	showCaseEditor,
	caseMode,
	caseForm,
	caseSources,
	skillOptions,
	isMemoryCase,
	inputContextError,
	startsMidConversation,
	useLoadedPrompt,
	wantsToolCalls,
	caseError,
	incompleteAssertion,
	savingCase,
	saveCase,
} = inject(EVAL_SUITE_KEY);
</script>
