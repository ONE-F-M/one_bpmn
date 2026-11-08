<template>
	<table class="prim-kv">
		<tbody>
			<tr v-for="(value, key) in rows" :key="key">
				<td class="prim-kv-key">{{ key }}</td>
				<td>{{ format(value) }}</td>
			</tr>
		</tbody>
	</table>
</template>
<script setup>
// Display primitive (WI-001673): two-column key/value listing.
defineProps({ rows: { type: Object, default: () => ({}) } });
function format(value) {
	if (Array.isArray(value)) return value.map((v) => (typeof v === "object" ? JSON.stringify(v) : v)).join(" • ");
	if (value && typeof value === "object") return JSON.stringify(value);
	return String(value ?? "");
}
</script>
<style scoped>
.prim-kv { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.prim-kv td { padding: 4px 6px; border-bottom: 1px solid #ededed; vertical-align: top; }
.prim-kv tr:last-child td { border-bottom: none; }
.prim-kv-key { color: #7c7c7c; white-space: nowrap; width: 38%; }
:global([data-theme="dark"]) .prim-kv td { border-color: #232323; }
:global([data-theme="dark"]) .prim-kv-key { color: #808080; }
</style>
