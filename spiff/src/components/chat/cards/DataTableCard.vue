<template>
	<CardShell :title="value.title || __('Table')">
		<DataTable
			:columns="value.columns"
			:rows="value.rows"
			:row-action="value.row_action"
			@row-action="(action, row) => $emit('action', action, row)"
		/>
		<template v-if="value.rows && value.rows.length" #expanded>
			<DataTable :columns="value.columns" :rows="value.rows" />
		</template>
	</CardShell>
</template>
<script setup>
// onefm.table goes through CardShell for the shared #expanded window. It is
// data, not a proposal, so it has no action bar and the expanded copy has no
// row actions.
import CardShell from "../primitives/CardShell.vue";
import DataTable from "../primitives/DataTable.vue";

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s;
defineProps({
	value: { type: Object, required: true },
	busy: { type: Boolean, default: false },
	done: { type: Boolean, default: false },
});
defineEmits(["action"]);
</script>
