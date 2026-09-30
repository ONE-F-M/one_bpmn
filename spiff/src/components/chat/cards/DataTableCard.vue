<template>
	<CardShell :title="value.title || ''">
		<DataTable
			:columns="value.columns"
			:rows="value.rows"
			:row-action="value.row_action"
			@row-action="(action, row) => $emit('action', action, row)"
		/>
		<template #expanded>
			<!-- WI-003124: same body, full width — the dialog's slot is not
			     squeezed to the small card's 94% column, so a wide table gets
			     room to breathe. Read-only, same as every other #expanded. -->
			<DataTable
				:columns="value.columns"
				:rows="value.rows"
				:row-action="value.row_action"
				@row-action="(action, row) => $emit('action', action, row)"
			/>
		</template>
	</CardShell>
</template>
<script setup>
// onefm.table now goes through CardShell too (WI-003124), so it can offer
// the shared #expanded dialog. The title moves to CardShell's header (so it
// is not repeated inside DataTable itself); it still carries no action bar
// and no done/doneText — it was never a proposal awaiting a decision, only
// data, and CardShell's action bar and done line stay hidden when unused.
import CardShell from "../primitives/CardShell.vue";
import DataTable from "../primitives/DataTable.vue";
defineProps({
	value: { type: Object, required: true },
	busy: { type: Boolean, default: false },
	done: { type: Boolean, default: false },
});
defineEmits(["action"]);
</script>
