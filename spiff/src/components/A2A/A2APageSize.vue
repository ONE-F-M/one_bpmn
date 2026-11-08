<template>
	<div class="flex items-center gap-2">
		<span class="text-sm text-gray-600">Page Size:</span>
		<FormControl
			v-model="pageLength"
			type="select"
			:options="PAGE_SIZE_OPTIONS"
			class="w-20"
			@change="emit('change')"
		/>
	</div>
</template>

<script setup>
import { FormControl } from "frappe-ui";

const PAGE_SIZE_OPTIONS = [
	{ label: "10", value: 10 },
	{ label: "20", value: 20 },
	{ label: "50", value: 50 },
	{ label: "100", value: 100 },
];

const pageLength = defineModel({ type: [Number, String], default: 20 });
const emit = defineEmits(["change"]);
</script>
