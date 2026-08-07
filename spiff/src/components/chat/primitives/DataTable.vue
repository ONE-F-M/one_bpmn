<template>
	<div class="prim-dt">
		<div v-if="title" class="prim-dt-title">{{ title }}</div>
		<div class="prim-dt-scroll">
			<table>
				<thead>
					<tr>
						<th v-for="col in columns" :key="col.key" :style="{ textAlign: col.align || 'left' }">
							{{ col.label }}
						</th>
						<th v-if="rowAction" />
					</tr>
				</thead>
				<tbody>
					<tr v-for="(row, i) in rows" :key="i">
						<td v-for="col in columns" :key="col.key" :style="{ textAlign: col.align || 'left' }">
							{{ row[col.key] }}
						</td>
						<td v-if="rowAction" class="prim-dt-act">
							<ActionButton :label="rowAction.label" @press="$emit('row-action', rowAction.action, row)" />
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>
</template>
<script setup>
// Display primitive (WI-001673): the onefm.table renderer — structured or
// actionable tables. Display-only tables stay markdown in the text stream.
defineProps({
	title: { type: String, default: "" },
	columns: { type: Array, default: () => [] },
	rows: { type: Array, default: () => [] },
	rowAction: { type: Object, default: null }, // {label, action}
});
defineEmits(["row-action"]);
import ActionButton from "./ActionButton.vue";
</script>
<style scoped>
.prim-dt { min-width: 0; }
.prim-dt-title { font-weight: 600; font-size: 12px; margin-bottom: 6px; }
.prim-dt-scroll { overflow-x: auto; }
.prim-dt table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.prim-dt th { background: #f3f3f3; color: #525252; font-weight: 600; padding: 5px 8px; white-space: nowrap; }
.prim-dt td { padding: 5px 8px; border-bottom: 1px solid #ededed; font-variant-numeric: tabular-nums; }
.prim-dt tr:last-child td { border-bottom: none; }
.prim-dt-act { width: 1%; }
@media (prefers-color-scheme: dark) {
	.prim-dt th { background: #2b2b2b; color: #afafaf; } .prim-dt td { border-color: #232323; }
}
</style>
