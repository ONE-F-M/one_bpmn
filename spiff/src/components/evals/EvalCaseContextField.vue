<template>
	<div class="space-y-2">
		<FormControl
			type="checkbox"
			:label="__('Starts mid-conversation')"
			:model-value="enabled"
			@update:model-value="$emit('update:enabled', $event)"
		/>
		<p class="text-xs text-gray-500">
			{{ __("Load earlier messages and saved state into the chat before the user prompt is sent.") }}
		</p>
		<template v-if="enabled">
			<div class="flex items-center justify-between">
				<span class="text-xs text-gray-600">{{ __("Earlier conversation (JSON)") }}</span>
				<Button
					v-if="!modelValue"
					size="sm"
					variant="subtle"
					:label="__('Insert example')"
					@click="$emit('update:modelValue', EXAMPLE_CONTEXT)"
				/>
			</div>
			<FormControl
				type="textarea"
				:rows="10"
				:model-value="modelValue"
				placeholder='{"conversation_messages": [{"message_type": "User", "text": "..."}], "session_state": {}}'
				@update:model-value="$emit('update:modelValue', $event)"
			/>
			<p
				class="text-xs"
				:class="error ? 'text-red-600' : 'text-gray-500'"
			>
				{{ error || __("conversation_messages: oldest first, each with message_type User, Bot or Tool and its text. A Tool row's metadata is the agent's saved progress. session_state: what its tools already fetched.") }}
			</p>
		</template>
	</div>
</template>

<script setup>
import { computed } from "vue"
import { Button, FormControl } from "frappe-ui"
import { EXAMPLE_CONTEXT, midConversationError } from "@/utils/evalContext"

const props = defineProps({
	enabled: { type: Boolean, default: false },
	modelValue: { type: String, default: "" },
})
defineEmits(["update:enabled", "update:modelValue"])

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s
const error = computed(() => (props.enabled ? midConversationError(props.modelValue) : ""))
</script>
