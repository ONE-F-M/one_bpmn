<template>
	<div
		class="mt-3 bg-white rounded-lg px-4 sm:px-6 py-4 border-t flex flex-wrap gap-2 items-center justify-between text-sm"
	>
		<div class="text-gray-600">
			Showing {{ count ? start + 1 : 0 }} to {{ start + count }} of {{ total }}
		</div>
		<div class="flex items-center gap-2">
			<Button variant="outline" :disabled="start === 0" @click="emit('prev')"
				>Previous</Button
			>
			<Button
				variant="outline"
				:disabled="start + pageLength >= total"
				@click="emit('next')"
			>
				Next
			</Button>
		</div>
	</div>
</template>

<script setup>
import { Button } from "frappe-ui";

defineProps({
	start: { type: Number, required: true },
	count: { type: Number, required: true },
	total: { type: Number, required: true },
	pageLength: { type: Number, required: true },
});
const emit = defineEmits(["prev", "next"]);
</script>
