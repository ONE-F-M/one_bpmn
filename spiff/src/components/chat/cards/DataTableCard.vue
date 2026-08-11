<template>
	<div class="dt-card">
		<DataTable
			:title="value.title"
			:columns="value.columns"
			:rows="value.rows"
			:row-action="value.row_action"
			@row-action="(action, row) => $emit('action', action, row)"
		/>
	</div>
</template>
<script setup>
// onefm.table binds the DataTable primitive directly — no CardShell, per
// the contract note: it is data, not a proposal awaiting a decision.
import DataTable from "../primitives/DataTable.vue";
defineProps({
	value: { type: Object, required: true },
	busy: { type: Boolean, default: false },
	done: { type: Boolean, default: false },
});
defineEmits(["action"]);
</script>
<style scoped>
.dt-card { align-self: flex-start; width: 94%; background: #fff; border: 1px solid #e2e2e2;
	border-radius: 10px; padding: 10px 12px; }
:global([data-theme="dark"]) .dt-card { background: #1c1c1c; border-color: #343434; }
</style>
