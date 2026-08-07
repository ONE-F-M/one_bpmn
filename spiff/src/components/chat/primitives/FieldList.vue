<template>
	<table class="prim-fields">
		<tbody>
			<tr v-for="(f, i) in fields" :key="i">
				<td class="prim-fields-name">+ {{ f.label || f.fieldname }}</td>
				<td>{{ describe(f) }}</td>
			</tr>
		</tbody>
	</table>
</template>
<script setup>
// Display primitive (WI-001673): the human summary of a doctype IR's fields.
defineProps({ fields: { type: Array, default: () => [] } });
function describe(f) {
	const bits = [f.fieldtype || ""];
	if (f.options && ["Select", "Link", "Table"].includes(f.fieldtype)) bits.push(String(f.options).split("\n").join(", "));
	if (f.reqd) bits.push("required");
	return bits.filter(Boolean).join(" · ");
}
</script>
<style scoped>
.prim-fields { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.prim-fields td { padding: 4px 6px; border-bottom: 1px solid #ededed; vertical-align: top; }
.prim-fields tr:last-child td { border-bottom: none; }
.prim-fields-name { color: #278f5e; white-space: nowrap; width: 42%; }
@media (prefers-color-scheme: dark) {
	.prim-fields td { border-color: #232323; } .prim-fields-name { color: #58c08e; }
}
</style>
