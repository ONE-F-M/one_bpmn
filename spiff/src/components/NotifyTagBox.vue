<template>
	<div
		class="flex min-h-9 flex-wrap items-center gap-1.5 rounded bg-surface-gray-2 px-2 py-1.5"
	>
		<Badge
			v-for="tag in tags"
			:key="tag.key"
			variant="outline"
			size="lg"
			class="max-w-full !rounded !border-outline-gray-2 !bg-surface-white !text-ink-gray-8 shadow-sm"
		>
			<span class="max-w-[150px] truncate">{{ tag.label }}</span>
			<span
				v-if="tag.sub"
				dir="rtl"
				class="max-w-[150px] truncate text-ink-gray-5"
			>{{ tag.sub }}</span>
			<template #suffix>
				<Button
					variant="ghost"
					size="sm"
					icon="x"
					class="!h-5 !w-5"
					:label="`Remove ${tag.label}`"
					@click="emit('remove', tag.key)"
				/>
			</template>
		</Badge>
		<Autocomplete
			v-if="options"
			class="min-w-[5rem] flex-1"
			body-classes="min-w-[16rem]"
			:compare-fn="compareOption"
			:model-value="null"
			:options="options"
			@update:model-value="(option) => option && emit('add', option)"
		>
			<template #target="{ togglePopover }">
				<button
					type="button"
					class="w-full rounded py-0.5 text-left text-base text-ink-gray-4 focus:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-3"
					@click="togglePopover()"
				>
					{{ placeholder }}
				</button>
			</template>
		</Autocomplete>
	</div>
</template>

<script setup>
import { Autocomplete, Badge, Button } from "frappe-ui";
import { compareOption } from "@/utils/compareOption";

defineProps({
	// [{ key, label, sub }]; sub is shown after the label, right to left
	tags: { type: Array, required: true },
	// Autocomplete options; no picker when null
	options: { type: Array, default: null },
	placeholder: { type: String, default: "" },
});

const emit = defineEmits(["add", "remove"]);
</script>
