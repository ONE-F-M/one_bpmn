<template>
	<FormControl
		:type="type"
		dir="rtl"
		:label="label"
		:model-value="modelValue"
		@update:model-value="(value) => emit('update:modelValue', value)"
	>
		<template #description>
			<ErrorMessage
				v-if="error"
				:message="error"
			/>
			<div
				v-else-if="edited"
				class="flex flex-wrap items-center gap-2"
			>
				<p class="text-p-sm text-ink-gray-5">Edited by hand. Changes to the English no longer update it.</p>
				<Button
					size="sm"
					variant="subtle"
					label="Translate again"
					@click="emit('translateAgain')"
				/>
			</div>
			<p
				v-else-if="hint"
				class="text-p-sm text-ink-gray-5"
			>
				{{ hint }}
			</p>
		</template>
	</FormControl>
</template>

<script setup>
import { Button, ErrorMessage, FormControl } from "frappe-ui";

defineProps({
	label: { type: String, required: true },
	modelValue: { type: String, default: "" },
	// true once the author typed in this Arabic field
	edited: { type: Boolean, default: false },
	error: { type: String, default: "" },
	hint: { type: String, default: "" },
	// "text" or "textarea"
	type: { type: String, default: "text" },
});

const emit = defineEmits(["update:modelValue", "translateAgain"]);
</script>
