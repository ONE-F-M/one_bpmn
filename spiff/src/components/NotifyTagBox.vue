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
			<slot
				name="tag"
				:tag="tag"
			/>
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
		<div
			v-if="options"
			class="min-w-[10rem] flex-1"
		>
			<Autocomplete
				:key="picks"
				:compare-fn="compareOption"
				:options="options"
				:model-value="null"
				:placeholder="placeholder"
				@update:model-value="pick"
			/>
		</div>
	</div>
</template>

<script setup>
import { ref } from "vue";
import { Autocomplete, Badge, Button } from "frappe-ui";
import { compareOption } from "@/utils/compareOption";

defineProps({
	// [{ key, label, sub }]; sub is shown after the label, right to left
	tags: { type: Array, required: true },
	// [{ label, value }] for the search box; no search box when null
	options: { type: Array, default: null },
	placeholder: { type: String, default: "" },
});

const emit = defineEmits(["add", "remove"]);

// remounts the search box so it is empty again after each pick
const picks = ref(0);

function pick(option) {
	if (!option) return;
	emit("add", option);
	picks.value += 1;
}
</script>
