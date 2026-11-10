<template>
	<button
		@click="$emit('click')"
		title="Comment Tool"
		:class="[
			'p-1.5 flex items-center justify-center rounded transition-colors',
			active
				? 'bg-blue-100 text-blue-700 shadow-sm'
				: 'hover:bg-gray-100 text-gray-700'
		]"
	>
		<Icon icon="lucide:message-square" class="w-4 h-4" />
	</button>
</template>

<script setup>
// The Comment Tool is the one canvas tool that survives the read-only lock
// (WI-004178): a comment never mutates the diagram, so it stays available on a
// map that has no editable Process Implementation. It renders in two places in
// BpmnEditor.vue — inside the editing toolbar and beside the "View Only"
// indicator — so it lives here rather than being written out twice.
import { Icon } from "@iconify/vue";

defineProps({
	active: {
		type: Boolean,
		default: false
	}
});

defineEmits(["click"]);
</script>
