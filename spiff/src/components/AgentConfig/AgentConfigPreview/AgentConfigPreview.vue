<template>
	<div class="space-y-5">
		<div class="space-y-3">
			<div>
				<label class="block text-xs font-medium text-gray-700 mb-1">{{ __("Sample variables (JSON)") }}</label>
				<textarea
					v-model="sampleVariables"
					rows="3"
					class="w-full font-mono text-xs border border-gray-300 rounded p-2"
					placeholder='{"doc": {"customer": "Acme"}}'
				></textarea>
				<p class="text-xs text-gray-500 mt-1">{{ __("Stand in for the process variables and the document the prompts read.") }}</p>
			</div>
			<div>
				<label class="block text-xs font-medium text-gray-700 mb-1">{{ __("Sample message") }}</label>
				<input
					v-model="sampleMessage"
					type="text"
					class="w-full text-sm border border-gray-300 rounded p-2"
					:placeholder="__('What a person would send this agent')"
				/>
			</div>
			<Button
				:label="__('Refresh preview')"
				:loading="previewLoading"
				@click="loadPreview"
			/>
		</div>

		<ErrorMessage
			v-if="previewError"
			:message="previewError"
		/>
		<template v-if="preview">
			<section>
				<h4 class="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1">{{ __("System prompt") }}</h4>
				<pre class="preview-block bg-gray-50 border border-gray-200 rounded p-2 text-xs">{{ preview.system_prompt || __("(empty)") }}</pre>
			</section>
			<section>
				<h4 class="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1">{{ __("User prompt") }}</h4>
				<pre class="preview-block bg-gray-50 border border-gray-200 rounded p-2 text-xs">{{ preview.user_prompt || __("(empty)") }}</pre>
				<p class="text-xs text-gray-500 mt-1">{{ __("Long-term memory and earlier conversation turns are added at run time and are not shown.") }}</p>
			</section>
			<section>
				<h4 class="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1">
					{{ __("Tools") }} · {{ preview.tools.length }}
				</h4>
				<p
					v-if="!preview.tools.length"
					class="text-sm text-gray-500"
				>{{ __("No tools. Pick a Tools box in the properties panel to give this agent tools.") }}</p>
				<div
					v-for="tool in preview.tools"
					:key="tool.name"
					class="border border-gray-200 rounded p-3 mb-2"
				>
					<div class="flex items-center gap-2">
						<span class="font-mono text-sm font-semibold text-gray-900">{{ tool.name }}</span>
						<span
							v-if="tool.human"
							class="rounded-full bg-amber-50 text-amber-700 px-2 text-[10px]"
						>{{ __("asks a person") }}</span>
					</div>
					<p class="text-sm text-gray-700 mt-1">{{ tool.description }}</p>
					<pre class="preview-block bg-gray-50 border border-gray-200 rounded p-2 text-xs mt-2">{{ schemaText(tool) }}</pre>
				</div>
			</section>
		</template>

		<section class="border-t border-gray-200 pt-4 space-y-3">
			<h4 class="text-xs font-semibold uppercase tracking-wide text-gray-500">{{ __("Dry run") }}</h4>
			<p class="text-xs text-gray-500">
				{{ __("Sends the sample message to the model once. Tools are not executed: each returns the sample result below, or a placeholder. Nothing is saved, but the model call is real and is billed.") }}
			</p>
			<div>
				<label class="block text-xs font-medium text-gray-700 mb-1">{{ __("Sample tool results (JSON, by tool name)") }}</label>
				<textarea
					v-model="sampleResults"
					rows="3"
					class="w-full font-mono text-xs border border-gray-300 rounded p-2"
					placeholder='{"lookup_customer": {"customer": "Acme Ltd"}}'
				></textarea>
			</div>
			<Button
				variant="solid"
				:label="__('Dry run')"
				:loading="dryRunLoading"
				:disabled="!sampleMessage"
				@click="runDryRun"
			/>
			<ErrorMessage
				v-if="dryRunError"
				:message="dryRunError"
			/>
			<div
				v-if="dryRun"
				class="space-y-2"
			>
				<div
					v-for="(turn, index) in dryRun.turns"
					:key="index"
					class="border-l-2 border-gray-200 pl-3 space-y-1"
				>
					<p
						v-if="turn.content"
						class="text-sm text-gray-800 whitespace-pre-wrap"
					>{{ turn.content }}</p>
					<div
						v-for="(call, callIndex) in turn.tool_calls"
						:key="callIndex"
						class="text-xs"
					>
						<span class="font-mono font-semibold text-gray-900">{{ call.name }}</span>
						<pre class="preview-block bg-gray-50 border border-gray-200 rounded p-2 text-xs mt-1">{{ toolCallText(call) }}</pre>
					</div>
				</div>
				<p
					v-if="dryRun.error_code !== 'SUCCESS'"
					class="text-sm text-red-600"
				>{{ dryRun.error_code }}: {{ dryRun.error_message }}</p>
				<div v-else>
					<h4 class="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1">{{ __("Reply") }}</h4>
					<pre class="preview-block bg-gray-50 border border-gray-200 rounded p-2 text-xs">{{ replyText }}</pre>
				</div>
			</div>
		</section>
	</div>
</template>

<script setup>
import { computed, inject, onMounted } from "vue";
import { Button, ErrorMessage } from "frappe-ui";
import { AGENT_CONFIG_KEY } from "@/composables/AgentConfig/useAgentConfigState";

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s;

const ac = inject(AGENT_CONFIG_KEY);
const {
	sampleVariables,
	sampleMessage,
	sampleResults,
	preview,
	previewLoading,
	previewError,
	loadPreview,
	dryRun,
	dryRunLoading,
	dryRunError,
	runDryRun,
} = ac;

const replyText = computed(() => {
	const output = dryRun.value?.output;
	return typeof output === "string" ? output : JSON.stringify(output, null, 2);
});

function schemaText(tool) {
	return JSON.stringify(tool.parameters, null, 2);
}

function toolCallText(call) {
	return `${__("Arguments")}: ${JSON.stringify(call.arguments, null, 2)}\n${__("Result")}: ${call.result}`;
}

onMounted(loadPreview);
</script>

<style scoped>
.preview-block {
	white-space: pre-wrap;
	word-break: break-word;
	max-height: 320px;
	overflow: auto;
}
</style>
